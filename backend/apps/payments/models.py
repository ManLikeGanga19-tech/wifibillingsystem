import json
import uuid

from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import OperatorOwnedModel
from apps.plans.models import Plan


class Transaction(OperatorOwnedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        TIMEOUT = "timeout", "Timeout"
        RECONCILED = "reconciled", "Success (reconciled)"

    # Public UUID so the portal can poll status without exposing sequential IDs
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    subscriber = models.ForeignKey(
        "accounts.Subscriber",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transactions",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="transactions")
    router = models.ForeignKey(
        "provisioning.Router", null=True, blank=True, on_delete=models.SET_NULL
    )
    phone = models.CharField(max_length=12, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    account_reference = models.CharField(max_length=20, blank=True)
    mac_address = models.CharField(max_length=17, blank=True)

    # WHICH gateway took this money, and therefore WHERE it landed. Recorded on the
    # transaction rather than read from the operator, because an ISP who switches gateway
    # must not have their in-flight payments verified against the wrong account — and a
    # sale must be settled the way it was actually taken, forever, not the way the ISP is
    # configured today.
    gateway = models.CharField(max_length=20, default="wifios", db_index=True)
    settlement = models.CharField(
        max_length=8,
        choices=[("platform", "Held by WIFI.OS"), ("direct", "Paid straight to the ISP")],
        default="platform",
        db_index=True,
    )

    checkout_request_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    merchant_request_id = models.CharField(max_length=100, blank=True)
    mpesa_receipt = models.CharField(max_length=30, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)
    raw_callback = models.JSONField(null=True, blank=True)
    callback_received_at = models.DateTimeField(null=True, blank=True)
    reconcile_attempts = models.PositiveSmallIntegerField(default=0)
    # Set when provisioning permanently fails AFTER a successful payment — including
    # the case where no session could even be created (e.g. the ISP has no router).
    # Without this, a paid customer whose connection could not be built is invisible
    # to the portal, which then spins forever. This is the customer's proof that we
    # took the money and know the connection failed.
    provision_error = models.CharField(max_length=255, blank=True)
    # Estimated M-Pesa collection cost the platform (Danamo) bears. Not charged
    # to the ISP; used for true-margin reporting.
    platform_cost = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    SUCCESS_STATUSES = (Status.SUCCESS, Status.RECONCILED)
    TERMINAL_STATUSES = (Status.SUCCESS, Status.RECONCILED, Status.FAILED, Status.TIMEOUT)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"{self.phone} KSh {self.amount} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES


class C2BPayment(models.Model):
    """A paybill (C2B) payment received on Danamo's shortcode — how PPPoE clients
    pay. The BillRefNumber is the client's globally-unique account number, which
    routes the money to the right ISP + client. Idempotent on M-Pesa TransID."""

    class Status(models.TextChoices):
        MATCHED = "matched", "Matched to a client"
        UNMATCHED = "unmatched", "No matching account"
        # We know exactly whose money this is — but that ISP is not cleared to
        # receive it yet. We cannot refuse a C2B payment (Safaricom has already
        # taken it), so we HOLD it: recorded, attributed, but not credited and not
        # restoring service. Released automatically the moment the ISP goes live.
        HELD = "held", "Held — ISP not yet cleared to transact"

    trans_id = models.CharField(max_length=30, unique=True, db_index=True)
    bill_ref = models.CharField(max_length=30, db_index=True, help_text="Account number typed")
    msisdn = models.CharField(max_length=15, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    first_name = models.CharField(max_length=60, blank=True)
    # Set when matched; operator derived from the client
    operator = models.ForeignKey(
        "core.Operator", null=True, blank=True, on_delete=models.SET_NULL
    )
    client = models.ForeignKey(
        "pppoe.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="payments"
    )
    status = models.CharField(max_length=10, choices=Status.choices, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    platform_cost = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"C2B {self.trans_id} {self.bill_ref} KSh {self.amount} [{self.status}]"


class GatewayCredential(models.Model):
    """One ISP's credentials for ONE payment gateway.

    Kept per-gateway (not on Operator) so switching away from M-Pesa does not destroy the
    keys — an ISP trialling their own shortcode against our paybill should be able to
    switch back and forth without re-pasting a Daraja secret.

    The whole set is a single encrypted JSON blob, for the same reason as the SMS
    providers: gateways disagree about what a credential even IS (shortcode+key+secret+
    passkey, or a bearer token, or an API key + IPN id), and a column per field would be a
    migration tax on every gateway added.

    These are the most dangerous secrets in the system. A stolen Daraja consumer secret
    lets somebody collect money in the ISP's name. They are Fernet-encrypted at rest and
    NEVER returned by the API — a read reports which fields are set, not what they are.
    """

    operator = models.ForeignKey(
        "core.Operator", on_delete=models.CASCADE, related_name="gateway_credentials"
    )
    gateway = models.CharField(max_length=20)
    secrets = EncryptedTextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operator", "gateway"], name="one_credential_per_gateway"
            )
        ]

    def __str__(self):
        return f"{self.operator.slug} {self.gateway}"

    @property
    def values(self) -> dict:
        if not self.secrets:
            return {}
        try:
            return json.loads(self.secrets)
        except ValueError:
            return {}

    @values.setter
    def values(self, data: dict):
        self.secrets = json.dumps(data)
