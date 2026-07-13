"""ISP-facing reporting endpoints: a custom-range summary, and CSV exports.

All tenant-scoped through acting_tenant — an ISP sees only its own money. Read-only, so
platform support may view them while impersonating (they move nothing).
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequireTenant, TenantIsOperational
from apps.core.schema import OBJECT_RESPONSE
from apps.core.tenancy import acting_tenant

from . import reports


class _ReportBase(APIView):
    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]


@extend_schema(responses=OBJECT_RESPONSE,
               summary="Revenue over a date range: totals, by plan, by source, daily")
class RevenueSummaryView(_ReportBase):
    def get(self, request):
        operator = acting_tenant(request)
        start, end = reports.parse_range(request)
        return Response(reports.revenue_summary(operator, start, end))


CSV_RESPONSE = {(200, "text/csv"): OpenApiResponse(OpenApiTypes.BINARY, description="CSV file")}


class _CsvExportView(_ReportBase):
    #: The reports.* function that streams the CSV for this export.
    export = None

    def get(self, request):
        operator = acting_tenant(request)
        start, end = reports.parse_range(request)
        return self.export(operator, start, end)


@extend_schema(responses=CSV_RESPONSE, summary="Export hotspot payments as CSV")
class TransactionsCsvView(_CsvExportView):
    export = staticmethod(reports.transactions_csv)


@extend_schema(responses=CSV_RESPONSE, summary="Export PPPoE (paybill) payments as CSV")
class PppoePaymentsCsvView(_CsvExportView):
    export = staticmethod(reports.pppoe_payments_csv)


@extend_schema(responses=CSV_RESPONSE, summary="Export the wallet ledger as CSV")
class LedgerCsvView(_CsvExportView):
    export = staticmethod(reports.ledger_csv)
