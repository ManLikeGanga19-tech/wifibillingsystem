"""Server-side pagination for every list endpoint.

Two shapes, one policy:

* `StandardPagination` — page-number pagination for the ordinary tables. Gives the UI a total
  count and jump-to-page, defaults to a small page, and — crucially — HARD-CAPS the page size so
  no client can ask for the whole table at once. That cap is the main lever that keeps GET load
  bounded as the number of ISPs grows.

* `LogCursorPagination` — cursor pagination for the big append-only logs (transactions, audit,
  location pings). Cursors are O(1) at any depth and stable under inserts, where deep OFFSETs and
  COUNT(*) on a growing table are not; the trade-off (no total count, no jump-to-page) is fine for
  a log you scroll.

Both enforce a deterministic order so a page can never shift under the reader — page-number needs
it for correctness, cursor pagination requires it outright.
"""

from rest_framework.pagination import CursorPagination, PageNumberPagination

#: Rows per page unless the client asks otherwise, and the ceiling it can ask up to. One place so
#: every table agrees. The cap is deliberately modest: a page is a screen, not a bulk export.
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class StandardPagination(PageNumberPagination):
    """Page-number pagination with a client-adjustable size, hard-capped at MAX_PAGE_SIZE."""

    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE

    def paginate_queryset(self, queryset, request, view=None):
        # A page must be reproducible: if a view handed us an unordered queryset, impose a stable
        # order (newest pk first) so rows can't reshuffle between pages. This is the safety net;
        # models still declare their own Meta.ordering for a meaningful default.
        if hasattr(queryset, "ordered") and not queryset.ordered:
            queryset = queryset.order_by("-pk")
        return super().paginate_queryset(queryset, request, view)


class LogCursorPagination(CursorPagination):
    """Cursor pagination for append-only logs. Newest first; a viewset overrides `ordering` to a
    field it actually has (with a unique tiebreaker), e.g. ('-created_at', '-id')."""

    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE
    ordering = ("-id",)
