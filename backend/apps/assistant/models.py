"""Settings > AI Assistant — which model powers an ISP's dashboard assistant, and (optionally)
their own API key.

The key is the ISP's OWN credential: if set, the assistant calls their chosen provider on their
account and their bill. Left blank, the ISP rides the platform default (Danamo's key, from the
environment — never in code). Stored Fernet-encrypted and never returned in full after saving.
"""

from django.db import models
from pgvector.django import HnswIndex, VectorField

from apps.core.fields import EncryptedTextField
from apps.core.models import Operator

#: Dimension of the self-hosted embedding model (BAAI/bge-small-en-v1.5). One source of truth so
#: the model, the column and the query vector can never silently disagree.
EMBEDDING_DIM = 384


class Provider(models.TextChoices):
    CLAUDE = "claude", "Claude (Anthropic)"
    OPENAI = "openai", "OpenAI"


class AISettings(models.Model):
    operator = models.OneToOneField(
        Operator, on_delete=models.CASCADE, related_name="ai_settings"
    )
    provider = models.CharField(
        max_length=10, choices=Provider.choices, default=Provider.CLAUDE
    )
    #: The ISP's OWN provider key. Blank = use the platform default. Encrypted at rest.
    api_key = EncryptedTextField(blank=True, default="")
    #: Pro AI add-on: platform-paid, unlocks the stronger model, actions and memory, and lifts the
    #: free monthly question budget. Set when the ISP buys the add-on (billing wires this later).
    pro_ai = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AI settings for {self.operator.slug}"


class PlatformAISettings(models.Model):
    """The platform's OWN cross-tenant key — what every free/Pro tenant rides when they haven't
    brought their own. Danamo pays this bill, so it's rate-limited platform-wide to bound the cost
    of a spike across all ISPs at once. A singleton (one row), managed by platform staff.

    The key is stored encrypted, and takes precedence over the ANTHROPIC_API_KEY/OPENAI_API_KEY
    environment fallback so it can be rotated from the console without a redeploy.
    """

    provider = models.CharField(
        max_length=10, choices=Provider.choices, default=Provider.CLAUDE
    )
    api_key = EncryptedTextField(blank=True, default="")
    enabled = models.BooleanField(default=True)
    #: Platform-wide ceiling on requests per minute on the shared key. 0 = no extra limit (the
    #: per-tenant monthly budget still applies). Guards the platform bill against a global spike.
    rate_limit_per_min = models.PositiveIntegerField(default=60)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Platform AI settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce the singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "PlatformAISettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class DocChunk(models.Model):
    """One retrievable passage of the product docs, with its embedding.

    GLOBAL, not tenant-scoped: the docs are identical for every ISP, so this index is shared and
    carries no private data. The ingest command rebuilds it from the docs-site markdown; retrieval
    embeds the question and finds the nearest chunks by cosine distance.
    """

    slug = models.CharField(max_length=120, db_index=True)      # the doc page, e.g. "fibre-plant"
    title = models.CharField(max_length=200)                    # page title, for citation
    heading = models.CharField(max_length=200, blank=True)      # nearest section heading
    content = models.TextField()                                # the passage itself
    ordinal = models.PositiveIntegerField(default=0)            # position within the page
    #: Hash of (content + model) so re-ingest re-embeds only what actually changed.
    content_hash = models.CharField(max_length=64, db_index=True)
    embedding = VectorField(dimensions=EMBEDDING_DIM)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["slug", "ordinal"], name="docchunk_slug_ordinal"),
        ]
        indexes = [
            # Approximate-nearest-neighbour index for cosine distance — fast retrieval as the
            # corpus grows. Cosine because the embeddings aren't unit-normalised by us.
            HnswIndex(
                name="docchunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.slug}#{self.ordinal} — {self.heading or self.title}"


class AssistantQuestion(models.Model):
    """Analytics for one assistant turn — the signal behind the platform "docs gaps" report.

    Tenant-scoped: the raw question is THIS ISP's data and never leaves their tenant. Only the
    derived, non-identifying fields (topic, grounded, rating) are aggregated across tenants, and
    that aggregation never reads the question text.
    """

    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="assistant_questions"
    )
    question = models.TextField()                               # tenant-private; for their history
    #: Did retrieval find a usable passage? The core "did we have an answer" signal for docs gaps.
    grounded = models.BooleanField(default=False)
    top_score = models.FloatField(null=True, blank=True)        # best retrieval similarity
    #: A coarse, non-identifying topic label (derived), safe to aggregate across tenants.
    topic = models.CharField(max_length=60, blank=True, db_index=True)
    #: Optional 👍 / 👎 the operator gives the answer: +1, -1, or null.
    rating = models.SmallIntegerField(null=True, blank=True)
    #: Provider token usage for this turn — feeds cost tracking and the usage meter.
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["grounded", "created_at"])]

    def __str__(self):
        return f"Q[{self.operator_id}] grounded={self.grounded}"


class Conversation(models.Model):
    """A saved assistant chat — one named thread for one task. Scoped to the tenant AND the staff
    member who owns it, so each person's chats are private to them (server-owned, no browser
    storage). The server keeps the transcript so it survives reloads and sign-ins."""

    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="ai_conversations"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="ai_conversations"
    )
    title = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Conversation[{self.operator_id}/{self.user_id}] {self.title!r}"


class ConversationMessage(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10)  # "user" | "assistant"
    content = models.TextField()
    #: For assistant turns: the docs it cited, and the AssistantQuestion id to attach a rating to.
    sources = models.JSONField(default=list, blank=True)
    question_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"
