"""Ingest the product docs into the RAG index (DocChunk).

Reads the docs-site markdown, splits each page into passages at its headings, embeds anything
that changed (content-hash guarded, so re-runs are cheap), and prunes passages whose source is
gone. Idempotent: run it after every docs change (a CI step in production).

    python manage.py ingest_docs            # from settings.DOCS_CONTENT_DIR
    python manage.py ingest_docs --path ... # explicit directory
"""

import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.assistant.models import DocChunk
from apps.assistant.rag import embed

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
TITLE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
HEADING = re.compile(r"^(#{2,3})\s+(.*)$", re.MULTILINE)
MDX_IMPORT = re.compile(r"^import\s.+$", re.MULTILINE)
JSX_TAG = re.compile(r"</?[A-Za-z][^>]*>")
MAX_CHARS = 1500  # split a very long section so no single passage dominates a retrieval


def _strip(md: str, is_mdx: bool) -> tuple[str, str]:
    """Return (title, body) — frontmatter removed, MDX components reduced to their text."""
    title = ""
    m = FRONTMATTER.match(md)
    if m:
        t = TITLE.search(m.group(1))
        title = t.group(1).strip().strip("\"'") if t else ""
        md = md[m.end():]
    if is_mdx:
        md = MDX_IMPORT.sub("", md)
        md = JSX_TAG.sub("", md)          # drop component tags, keep the text between them
    return title, md.strip()


def _sections(body: str) -> list[tuple[str, str]]:
    """Split into (heading, text) at ## / ### boundaries; the intro before the first heading
    keeps an empty heading."""
    out, pos, heading = [], 0, ""
    for m in HEADING.finditer(body):
        chunk = body[pos:m.start()].strip()
        if chunk:
            out.append((heading, chunk))
        heading = m.group(2).strip()
        pos = m.end()
    tail = body[pos:].strip()
    if tail:
        out.append((heading, tail))
    return out


def _paragraph_split(text: str) -> list[str]:
    """Keep passages reasonably sized: only split when a section is very long, at blank lines."""
    if len(text) <= MAX_CHARS:
        return [text]
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) > MAX_CHARS:
            parts.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _hash(content: str) -> str:
    return hashlib.sha256(f"{settings.ASSISTANT_EMBED_MODEL}\n{content}".encode()).hexdigest()


class Command(BaseCommand):
    help = "Ingest the product docs into the RAG index (DocChunk)."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=settings.DOCS_CONTENT_DIR,
                            help="Directory of docs markdown (.md/.mdx).")

    def handle(self, *args, **opts):
        root = Path(opts["path"])
        if not root.is_dir():
            raise CommandError(f"Docs directory not found: {root}")

        files = sorted([*root.glob("*.md"), *root.glob("*.mdx")])
        if not files:
            raise CommandError(f"No .md/.mdx files in {root}")

        # Build the desired set of passages keyed (slug, ordinal).
        desired: dict[tuple[str, int], dict] = {}
        for f in files:
            slug = f.stem
            title, body = _strip(f.read_text(encoding="utf-8"), f.suffix == ".mdx")
            title = title or slug
            ordinal = 0
            for heading, text in _sections(body):
                for piece in _paragraph_split(text):
                    # Prefix the heading into the embedded text so a passage carries its context.
                    content = f"{heading}\n\n{piece}".strip() if heading else piece
                    desired[(slug, ordinal)] = {
                        "slug": slug, "title": title, "heading": heading,
                        "content": content, "ordinal": ordinal, "content_hash": _hash(content),
                    }
                    ordinal += 1

        existing = {(c.slug, c.ordinal): c for c in DocChunk.objects.all()}

        # Only embed passages that are new or whose content changed.
        to_embed = [
            key for key, d in desired.items()
            if key not in existing or existing[key].content_hash != d["content_hash"]
        ]
        vectors = {}
        if to_embed:
            self.stdout.write(f"Embedding {len(to_embed)} new/changed passage(s)…")
            embedded = embed([desired[k]["content"] for k in to_embed])
            vectors = dict(zip(to_embed, embedded, strict=True))

        created = updated = 0
        with transaction.atomic():
            for key, d in desired.items():
                if key in vectors:
                    obj = existing.get(key) or DocChunk(slug=key[0], ordinal=key[1])
                    obj.title, obj.heading, obj.content = d["title"], d["heading"], d["content"]
                    obj.content_hash, obj.embedding = d["content_hash"], vectors[key]
                    obj.save()
                    created += key not in existing
                    updated += key in existing
            # Prune passages whose source line is gone (docs shortened or a page deleted).
            stale = [existing[k].pk for k in existing if k not in desired]
            if stale:
                DocChunk.objects.filter(pk__in=stale).delete()

        self.stdout.write(self.style.SUCCESS(
            f"Docs ingested: {len(desired)} passages across {len(files)} pages "
            f"({created} new, {updated} changed, {len(stale)} pruned)."
        ))
