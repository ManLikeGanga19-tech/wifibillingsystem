import secrets

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.core.permissions import RequireTenant, TenantCanTransact, TenantIsOperational
from apps.core.public import PublicAPIView
from apps.core.schema import OBJECT_REQUEST, OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant
from apps.core.viewsets import TenantModelViewSet, TenantReadOnlyViewSet
from apps.provisioning.adapters import ProvisioningError, get_adapter

from .capacity import capacity_warning
from .models import AccessPoint, Client, Invoice, ServicePlan, Tower
from .serializers import (
    AccessPointSerializer,
    ClientSerializer,
    InvoiceSerializer,
    ServicePlanSerializer,
    TowerSerializer,
)
from .services import (
    create_client,
    delete_client,
    provision_client,
    reset_pppoe_password,
    restore_client,
    suspend_client,
    update_client,
)


class ServicePlanViewSet(TenantModelViewSet):
    serializer_class = ServicePlanSerializer
    queryset = ServicePlan.objects.all()


class TowerViewSet(TenantModelViewSet):
    serializer_class = TowerSerializer
    queryset = Tower.objects.all()

    def get_queryset(self):
        # super() applies the tenant filter (TenantScopedMixin) — never bypass it
        return super().get_queryset().annotate(
            access_point_count=Count("access_points")
        ).order_by("name")


class AccessPointViewSet(TenantModelViewSet):
    serializer_class = AccessPointSerializer
    queryset = AccessPoint.objects.all()

    def get_queryset(self):
        # super() applies the tenant filter (TenantScopedMixin) — never bypass it
        return (
            super()
            .get_queryset()
            .select_related("tower")
            .annotate(
                client_count=Count(
                    "clients", filter=Q(clients__status__in=Client.ACTIVE_STATUSES)
                )
            )
            .order_by("tower__name", "name")
        )


class ClientViewSet(TenantModelViewSet):
    serializer_class = ClientSerializer
    queryset = Client.objects.select_related("plan", "router").order_by("-created_at")

    #: Switching a paying customer ON is the moment an ISP starts earning. An
    #: unverified ISP may build their whole client list — they simply cannot turn
    #: anyone on, because that would mean money flowing through our paybill for a
    #: business we have not checked.
    MONEY_ACTIONS = {"provision", "restore", "import_run", "import_csv"}

    def get_permissions(self):
        perms = super().get_permissions()
        if self.action in self.MONEY_ACTIONS:
            perms = [*perms, TenantCanTransact()]
        return perms

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        # Find one customer fast, however the ISP remembers them: the account number they
        # quote on the phone, their name, the number they call from, or their PPPoE login.
        # super() has already scoped to the tenant, so this only ever searches their own base.
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(account_number__icontains=search)
                | Q(full_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(pppoe_username__icontains=search)
            )
        return qs

    # --- sector capacity: a soft, audited over-subscription gate ------------------------
    @staticmethod
    def _forced(request) -> bool:
        return str(request.data.get("force", "")).lower() in ("1", "true", "yes")

    def _ap_from(self, request):
        ap_id = request.data.get("access_point")
        if not ap_id:
            return None
        return AccessPoint.objects.filter(operator=self.get_operator(), pk=ap_id).first()

    def create(self, request, *args, **kwargs):
        # Adding a client to a full sector over-subscribes it. Warn once (409); a re-submit
        # with force=true proceeds and is recorded, so the choice is on the ISP's books.
        warning = capacity_warning(self.get_operator(), self._ap_from(request))
        if warning and not self._forced(request):
            return Response(warning, status=status.HTTP_409_CONFLICT)
        resp = super().create(request, *args, **kwargs)
        if warning and resp.status_code == status.HTTP_201_CREATED:
            audit(
                "pppoe_over_capacity_add", operator=self.get_operator(), actor=request.user,
                sector=warning["sector"], count=warning["count"],
                capacity=warning["capacity"], account_number=resp.data.get("account_number"),
            )
        return resp

    def update(self, request, *args, **kwargs):
        # Only a MOVE onto a DIFFERENT full sector adds load; editing a client in place does
        # not, so it never warns.
        instance = self.get_object()
        ap = self._ap_from(request)
        warning = None
        if ap is not None and ap.pk != instance.access_point_id:
            warning = capacity_warning(self.get_operator(), ap, exclude_pk=instance.pk)
        if warning and not self._forced(request):
            return Response(warning, status=status.HTTP_409_CONFLICT)
        resp = super().update(request, *args, **kwargs)
        if warning and resp.status_code == status.HTTP_200_OK:
            audit(
                "pppoe_over_capacity_move", operator=self.get_operator(), actor=request.user,
                sector=warning["sector"], count=warning["count"],
                capacity=warning["capacity"], account_number=resp.data.get("account_number"),
            )
        return resp

    def perform_create(self, serializer):
        operator = self.get_operator()
        data = serializer.validated_data
        # Blank credentials mean "auto-generate": drop them so create_client's own generator
        # runs, rather than trying to set an empty username/password.
        if not data.get("pppoe_username"):
            data.pop("pppoe_username", None)
        if not data.get("pppoe_password"):
            data.pop("pppoe_password", None)
        client = create_client(
            operator=operator,
            plan=data.pop("plan"),
            router=data.pop("router"),
            created_by=self.request.user,
            **data,
        )
        serializer.instance = client

    def perform_update(self, serializer):
        # Credentials are set at create and changed only via reset_password (which re-pushes
        # to the router). A plain edit must never change them here, or the DB password would
        # silently diverge from the one on the MikroTik.
        data = dict(serializer.validated_data)
        data.pop("pppoe_username", None)
        data.pop("pppoe_password", None)
        # Route through the service so a plan/router change also reaches the ROUTER — a
        # DB-only save would leave the MikroTik enforcing the old plan (or holding the secret
        # on the old router) and nobody could tell which was true.
        # Serializers hand back model instances for FKs; the service works in *_id so it can
        # compare cheaply against the old values.
        FK_FIELDS = {"plan", "router", "access_point", "cpe_equipment"}
        changes = {}
        for field, value in data.items():
            if field in FK_FIELDS:
                changes[f"{field}_id"] = value.pk if value is not None else None
            else:
                changes[field] = value
        serializer.instance = update_client(
            self.get_object(), changes=changes, actor=self.request.user
        )

    def destroy(self, request, *args, **kwargs):
        # Remove the secret from the router BEFORE dropping the record — no orphaned
        # /ppp/secret. If the router is unreachable, keep the record and say so (502).
        instance = self.get_object()
        try:
            delete_client(instance, actor=request.user)
        except ProvisioningError as exc:
            return Response(
                {"detail": f"Couldn't remove the user from the router: {exc}. "
                           "Nothing was deleted — try again once the router is reachable."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE)
    @action(detail=True, methods=["post"])
    def reset_password(self, request, pk=None):
        """Set a new PPPoE password (supplied, or auto-generated) and push it to the router.
        Returns the new password so the ISP can read it back to the installer."""
        client = self.get_object()
        password = (request.data.get("password") or "").strip()
        if password and (any(c.isspace() for c in password) or len(password) < 6):
            return Response(
                {"detail": "Use 6+ characters and no spaces, or leave blank to auto-generate."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            new_password = reset_pppoe_password(client, password=password, actor=request.user)
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"pppoe_username": client.pppoe_username, "pppoe_password": new_password})

    @action(detail=True, methods=["post"])
    def provision(self, request, pk=None):
        client = self.get_object()
        try:
            provision_client(client)
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(ClientSerializer(client).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        client = self.get_object()
        try:
            suspend_client(client, reason="manual")
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"detail": "Suspended", "status": client.status})

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        client = self.get_object()
        try:
            restore_client(client)
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"detail": "Restored", "status": client.status})

    @action(detail=True, methods=["get"])
    def live_status(self, request, pk=None):
        """Is this client currently connected? (from /ppp/active)"""
        client = self.get_object()
        try:
            active = {s.username for s in get_adapter(client.router).get_active_pppoe()}
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"online": client.pppoe_username in active})

    # --- import (adopt existing router users) / export --------------------------------
    def _import_router(self, request):
        from apps.provisioning.models import Router

        return Router.objects.filter(
            operator=self.get_operator(), pk=request.data.get("router")
        ).first()

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE)
    @action(detail=False, methods=["post"], url_path="import-preview")
    def import_preview(self, request):
        """Read a router's existing PPPoE secrets and preview what an import would adopt —
        which are new, which are already managed, and the plan each maps to."""
        from .porting import preview_import

        router = self._import_router(request)
        if router is None:
            return Response({"detail": "Unknown router."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(preview_import(self.get_operator(), router))
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE)
    @action(detail=False, methods=["post"], url_path="import")
    def import_run(self, request):
        """Adopt the chosen router secrets as managed clients (DB-only, non-disruptive)."""
        from .porting import import_clients

        router = self._import_router(request)
        if router is None:
            return Response({"detail": "Unknown router."}, status=status.HTTP_400_BAD_REQUEST)
        items = request.data.get("items")
        if not isinstance(items, list):
            return Response(
                {"detail": "items must be a list."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            result = import_clients(
                self.get_operator(), router, items=items, actor=request.user
            )
        except ProvisioningError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)

    def _csv_rows(self, request):
        """Parse the posted CSV text, or raise a 400-shaped error message. The file arrives as
        TEXT in the JSON body (the browser reads it) rather than multipart — same CSRF and
        auth path as every other call, and no parser configuration to get subtly wrong."""
        from .porting import CsvImportError, parse_client_csv

        try:
            return parse_client_csv(request.data.get("csv") or ""), None
        except CsvImportError as exc:
            return None, Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE)
    @action(detail=False, methods=["post"], url_path="import-csv-preview")
    def import_csv_preview(self, request):
        """Read a CSV and describe exactly what importing it would do — per row, plus the
        plan names found in it. Writes nothing."""
        from .porting import preview_csv_import

        rows, error = self._csv_rows(request)
        if error:
            return error
        return Response(preview_csv_import(self.get_operator(), rows))

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE)
    @action(detail=False, methods=["post"], url_path="import-csv")
    def import_csv(self, request):
        """Create clients from a CSV — an ISP migrating in from another billing system."""
        from apps.provisioning.models import Router

        from .porting import import_clients_from_csv

        operator = self.get_operator()
        router = Router.objects.filter(
            operator=operator, pk=request.data.get("router")
        ).first()
        if router is None:
            return Response(
                {"detail": "Choose which router these clients belong to."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rows, error = self._csv_rows(request)
        if error:
            return error

        default_plan = ServicePlan.objects.filter(
            operator=operator, pk=request.data.get("default_plan")
        ).first()
        return Response(
            import_clients_from_csv(
                operator, router, rows=rows,
                plan_map=request.data.get("plan_map") or {},
                default_plan=default_plan, actor=request.user,
            )
        )

    @extend_schema(responses=OBJECT_RESPONSE)
    @action(detail=False, methods=["get"])
    def export(self, request):
        """Download this ISP's clients as CSV — a portable backup, and the way an ISP takes
        their data WITH them if they leave. Data portability is a promise, not a favour.

        Credentials are opt-in (`?include_credentials=true`) and, when asked for, restricted
        to the real ISP owner. The plain export stays open to anyone with read access,
        including platform support troubleshooting on a grant. Two reasons (audit F3):

          * one GET should not quietly hand over every customer's PPPoE password; and
          * a borrowed identity must never be able to bulk-export secrets — impersonation
            exists to TROUBLESHOOT. Note this cannot be left to CanManageMoney, which lets
            safe methods through and so would not stop a GET at all.

        The ISP's own owner can still take everything, whenever they want. It is simply a
        deliberate, audited act rather than a side effect of clicking Export.
        """
        from apps.core.offboarding import export_blocked_reason
        from apps.core.tenancy import is_impersonating

        from .porting import clients_csv

        operator = self.get_operator()

        # An ISP being offboarded with arrears cannot take its client list until it settles —
        # the data is leverage while money is owed (enforced server-side, both consoles).
        blocked = export_blocked_reason(operator)
        if blocked:
            return Response({"detail": blocked}, status=status.HTTP_403_FORBIDDEN)

        want_credentials = str(
            request.query_params.get("include_credentials", "")
        ).lower() in ("1", "true", "yes")

        if want_credentials and is_impersonating(request):
            return Response(
                {
                    "detail": "You are acting as another ISP. Their customers' PPPoE "
                    "passwords can only be exported by the ISP owner themselves."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        audit(
            "pppoe_clients_exported", operator=operator, actor=request.user,
            include_credentials=want_credentials,
        )
        return clients_csv(operator, include_credentials=want_credentials)


class InvoiceViewSet(TenantReadOnlyViewSet):
    serializer_class = InvoiceSerializer
    queryset = Invoice.objects.select_related("client").order_by("-issued_at")

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


@extend_schema(responses=OBJECT_RESPONSE, summary="Public: how a suspended subscriber pays")
class SuspendedNoticeView(PublicAPIView):
    """PUBLIC page a suspended PPPoE client is redirected to. Returns the ISP's
    pay instructions, and (if the client's account is known) their balance/status.

    Tenant context: ?router=<id> (the router that redirected them) or the
    subdomain. The client's account may be supplied as ?account=<no> OR resolved
    from their source IP via the router's live PPPoE sessions.

    Anonymous by design — a cut-off subscriber is never a logged-in staff user."""

    def get(self, request):
        from apps.provisioning.models import Router

        # Resolve the ISP
        operator = getattr(request, "tenant", None)
        router = None
        router_id = request.query_params.get("router", "")
        if router_id.isdigit():
            router = Router.objects.filter(pk=int(router_id), is_active=True).first()
            if router and operator is None:
                operator = router.operator
        if operator is None:
            return Response(
                {"detail": "Unknown provider."}, status=status.HTTP_404_NOT_FOUND
            )

        client = None
        account = (request.query_params.get("account") or "").strip().upper()
        if account:
            candidate = Client.objects.filter(
                operator=operator, account_number=account
            ).first()
            # SAME GATE AS account_lookup (pen-test F7): an account number TYPED by anyone is
            # not enough to reveal a customer's name and balance — it must be paired with
            # their phone digits. Without a match we fall through to the generic pay page.
            # (The source-IP path below needs no such gate: the customer is physically on the
            # cut-off connection, which is self-authenticating.)
            if candidate and _phone_last4_matches(
                candidate, request.query_params.get("phone", "")
            ):
                client = candidate
        # Fall back: identify by the client's current PPPoE IP on the router
        if client is None and router is not None:
            src_ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            src_ip = src_ip or request.META.get("REMOTE_ADDR", "")
            if src_ip:
                try:
                    active = get_adapter(router).get_active_pppoe()
                    username = next((a.username for a in active if a.ip_address == src_ip), None)
                    if username:
                        client = Client.objects.filter(
                            operator=operator, pppoe_username=username
                        ).first()
                except ProvisioningError:
                    pass

        # 🔴 THIS USED TO SEND THE MONEY INTO A VOID.
        #
        # It showed `operator.mpesa_shortcode` — the ISP's OWN paybill. But C2B
        # confirmations only ever arrive at DANAMO's shortcode. So a subscriber who
        # followed these instructions either paid the ISP directly (we never saw it,
        # the ledger never knew, and they STAYED CUT OFF despite having paid) or, if
        # the ISP had no shortcode set, was shown no paybill at all.
        #
        # The correct instruction is always: pay DANAMO's paybill, quoting the
        # client's globally-unique account number. That account number is the only
        # thing that routes the money to the right ISP and the right subscriber, and
        # it is exactly what the C2B matcher is built to receive.
        body = {
            "provider": operator.name,
            "paybill": settings.DARAJA_SHORTCODE or None,
            "how_to_pay": (
                "Go to M-Pesa → Lipa na M-Pesa → Pay Bill. Enter the paybill number, "
                "then YOUR ACCOUNT NUMBER shown below, then the amount. Your internet "
                "comes back automatically."
            ),
        }
        if client:
            body["client"] = {
                "account_number": client.account_number,  # the routing key
                "full_name": client.full_name,
                "plan": client.plan.name,
                "monthly": str(client.plan.price),
                "balance": str(client.balance),
                "status": client.status,
                "suspended": client.status == Client.Status.SUSPENDED,
            }
        return Response(body)


def _phone_last4_matches(client, raw_phone: str) -> bool:
    """True only if the supplied phone's last 4 digits match the client's on file.

    EVERY public path that reveals a customer's name/balance BY ACCOUNT NUMBER must gate on
    this. The account number is short and structured, so on its own it lets anyone enumerate
    an ISP's base; the phone digits are the thing only the real customer has. Shared between
    account_lookup and SuspendedNoticeView so the two can never drift apart again — which is
    exactly how the second one shipped ungated (pen-test F7)."""
    supplied = "".join(ch for ch in (raw_phone or "") if ch.isdigit())[-4:]
    on_file = "".join(ch for ch in (client.phone or "") if ch.isdigit())[-4:]
    return bool(supplied) and bool(on_file) and secrets.compare_digest(on_file, supplied)


class AccountLookupThrottle(AnonRateThrottle):
    """Tight, per-IP. This endpoint is anonymous and answers questions about a named
    customer, so it is the natural place to enumerate an ISP's whole base."""

    scope = "account-lookup"


@extend_schema(responses=OBJECT_RESPONSE, summary="Public: look up a subscriber account")
@api_view(["GET"])
@authentication_classes([])  # anonymous: a suspended subscriber, never staff
@permission_classes([AllowAny])
@throttle_classes([AccountLookupThrottle])
def account_lookup(request):
    """Public: a suspended client types their account number to see their balance and pay
    instructions. Scoped by ?router= or subdomain tenant.

    TWO THINGS ARE LOAD-BEARING HERE, because this endpoint is anonymous and returns a real
    person's name and debt (audit F2):

      * The caller must also prove they know the LAST 4 DIGITS OF THE ACCOUNT'S PHONE.
        Account numbers are short and structured, so on their own they are guessable — the
        phone digits are the thing only the actual customer (or someone holding their
        handset) has.
      * A wrong account and a wrong phone return the SAME 404. Distinguishing them would
        hand back an oracle — "this account exists, keep going" — which is most of what an
        enumerator wants.
    """
    from apps.provisioning.models import Router

    operator = getattr(request, "tenant", None)
    router_id = request.query_params.get("router", "")
    if operator is None and router_id.isdigit():
        router = Router.objects.filter(pk=int(router_id), is_active=True).first()
        operator = router.operator if router else None
    account = (request.query_params.get("account") or "").strip().upper()
    client = (
        Client.objects.filter(operator=operator, account_number=account).first()
        if operator and account
        else None
    )
    # One response for every failure mode: unknown account, wrong digits, or a client with
    # no phone on file (who cannot be verified this way at all, so support must help them).
    not_found = Response(
        {
            "detail": "We couldn't match that account number and phone number. "
            "Check both, or contact your provider."
        },
        status=status.HTTP_404_NOT_FOUND,
    )
    if client is None or not _phone_last4_matches(client, request.query_params.get("phone", "")):
        return not_found

    return Response(
        {
            "account_number": client.account_number,
            "full_name": client.full_name,
            "plan": client.plan.name,
            "monthly": str(client.plan.price),
            "balance": str(client.balance),
            "status": client.status,
            # Always DANAMO's paybill — never the ISP's. See SuspendedNoticeView.
            "paybill": settings.DARAJA_SHORTCODE or None,
        }
    )


class PppoeUsageSummaryView(APIView):
    """The dashboard tile: live fixed-line health at a glance — who is online, how much data
    the base is consuming this month, the heaviest users, and who has crossed their cap."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    @extend_schema(responses=OBJECT_RESPONSE, summary="PPPoE live usage summary (dashboard)")
    def get(self, request):

        from .metering import current_period_start
        from .models import ClientUsage

        operator = acting_tenant(request)
        clients = Client.objects.filter(operator=operator)
        active = clients.filter(status=Client.Status.ACTIVE)

        # Usage rows for THIS cycle. Clients bill on different days, so each has its own
        # period start — group by joining on the client's current period.
        usage_rows = (
            ClientUsage.objects.filter(operator=operator)
            .select_related("client", "client__plan")
        )
        today = timezone.localdate()
        this_cycle = [
            u for u in usage_rows
            if u.period_start == current_period_start(u.client, today)
        ]

        total_bytes = sum(u.total_bytes for u in this_cycle)
        over_fup = 0
        top = []
        for u in this_cycle:
            cap = u.client.plan.data_cap_gb
            pct = (100 * u.total_bytes / (cap * 1024**3)) if cap else None
            if pct is not None and pct >= 100:
                over_fup += 1
            top.append(
                {
                    "account_number": u.client.account_number,
                    "full_name": u.client.full_name,
                    "gb_total": round(u.total_bytes / 1024**3, 2),
                    "percent_used": round(pct, 1) if pct is not None else None,
                }
            )
        top.sort(key=lambda r: r["gb_total"], reverse=True)

        return Response(
            {
                "clients_total": clients.count(),
                "clients_active": active.count(),
                "online_now": active.filter(is_online=True).count(),
                "data_gb_this_cycle": round(total_bytes / 1024**3, 2),
                "over_fup": over_fup,
                "top_consumers": top[:5],
                "synced_at": (
                    active.exclude(usage_synced_at__isnull=True)
                    .order_by("-usage_synced_at")
                    .values_list("usage_synced_at", flat=True)
                    .first()
                ),
            }
        )


class PppoeChurnView(APIView):
    """Subscriber movement & churn: per-month new / lapsed / recovered / churned and the
    churn rate, plus the current standing. Answers "who didn't renew" and "what's my churn"
    — questions a status column can't, because they are about change over time."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "months", int, description="How many months back to include (1-24, default 6)."
            )
        ],
        responses=OBJECT_RESPONSE,
        summary="PPPoE churn & retention summary",
    )
    def get(self, request):
        from .analytics import churn_summary

        try:
            months = int(request.query_params.get("months", 6))
        except (TypeError, ValueError):
            months = 6
        return Response(churn_summary(acting_tenant(request), months=months))
