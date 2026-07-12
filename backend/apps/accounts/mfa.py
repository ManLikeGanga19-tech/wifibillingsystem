"""Two-factor authentication for the actions that move money.

WHY TOTP AND NOT AN EMAILED CODE.

An emailed code proves someone can read an inbox. That is a real factor, and it is why
signup verifies the address — we must know the address works, because it is the login
identifier and the channel every warning goes down. But as the guard on a *payout*, an
emailed code inherits every weakness of email: it depends on delivery (spam folders, a
down SMTP provider, a Safaricom-hosted mailbox that eats us), and it falls the moment
somebody owns the ISP owner's Gmail.

An authenticator app depends on nothing. It works offline, it costs nothing to send, it
cannot be delayed, and an attacker who owns the email account still cannot produce a
code. Every Kenyan business owner already has the app.

So the two do different jobs, and we keep both:
  - EMAIL proves the address, and remains the NOTIFICATION channel. A tripwire mail
    fires when the payout account changes whether or not TOTP authorised it — being
    told is not the same as being asked.
  - TOTP is the AUTHORISATION factor for money: withdrawing, and changing where the
    money goes.

SCOPE, deliberately narrow: money actions only. Login stays password-only. An ISP who
loses their phone must lose access to their *payouts*, not to their whole business —
they still need to see their clients and keep the network running while they recover.

RECOVERY is not an afterthought. Lose the phone with no way back and we have locked an
ISP out of their own money, which is the worst thing this system could do. Ten
single-use recovery codes are issued at enrolment, shown exactly once, stored hashed.
"""

import logging
import secrets

import pyotp
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models, transaction
from django.utils import timezone

from apps.core.fields import EncryptedTextField

logger = logging.getLogger(__name__)

ISSUER = "WIFI.OS"
RECOVERY_CODE_COUNT = 10

#: How many 30s windows either side of now we accept. One step = up to 30s of clock
#: drift on the phone, which is common and not the user's fault. More than one starts
#: widening the window an attacker can guess into.
VALID_WINDOW = 1


class MfaError(Exception):
    """Safe to show the user."""


class MfaRequired(MfaError):
    """Not a failure — a demand. The client must collect a code and retry."""


class MfaDevice(models.Model):
    """One authenticator per user. The secret IS the account, so it is encrypted at
    rest with the same Fernet key as router passwords — a leaked database dump must
    not hand out working second factors."""

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="mfa_device"
    )
    secret = EncryptedTextField()
    #: Null until they have proved they can actually generate a code from it. An
    #: unconfirmed device must never gate anything — otherwise a botched enrolment
    #: locks them out with a secret they never successfully scanned.
    confirmed_at = models.DateTimeField(null=True, blank=True)

    #: THE REPLAY GUARD. A TOTP code stays valid for its whole 30-second window, so a
    #: code shoulder-surfed (or captured in a log, or reused by a racing double-click)
    #: works twice unless we remember the last one we honoured.
    last_used_counter = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_mfadevice"

    def __str__(self):
        return f"MFA for {self.user}"

    @property
    def is_active(self) -> bool:
        return self.confirmed_at is not None

    def provisioning_uri(self) -> str:
        """The otpauth:// URI behind the QR code."""
        label = self.user.email or self.user.phone
        return pyotp.TOTP(self.secret).provisioning_uri(name=label, issuer_name=ISSUER)


class RecoveryCode(models.Model):
    """Single-use, hashed, and the only thing between a lost phone and a locked wallet."""

    device = models.ForeignKey(
        MfaDevice, on_delete=models.CASCADE, related_name="recovery_codes"
    )
    code_hash = models.CharField(max_length=128)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_recoverycode"

    def __str__(self):
        return f"Recovery code for {self.device.user} ({'used' if self.used_at else 'unused'})"


# ---- enrolment ---------------------------------------------------------------


def begin_enrolment(user) -> MfaDevice:
    """Create (or reset) an UNCONFIRMED device and hand back the secret to scan.

    Re-running this before confirmation throws the old secret away, which is what you
    want: someone who half-scanned a QR code and gave up should get a clean one, not be
    stuck with a secret they no longer have.
    """
    device, _ = MfaDevice.objects.get_or_create(
        user=user, defaults={"secret": pyotp.random_base32()}
    )
    if device.is_active:
        raise MfaError("Your authenticator is already set up. Remove it first to re-enrol.")
    device.secret = pyotp.random_base32()
    device.save(update_fields=["secret"])
    return device


@transaction.atomic
def confirm_enrolment(user, code: str) -> list[str]:
    """Prove the app works, switch the device on, and issue the recovery codes.

    Returns the PLAINTEXT recovery codes. This is the only moment they exist in a form
    anybody can read — we store hashes. If the user loses them, they generate new ones;
    we cannot show them these again, and a system that could is a system where a
    database leak hands out wallets.
    """
    device = MfaDevice.objects.select_for_update().filter(user=user).first()
    if device is None:
        raise MfaError("Start setup first.")
    if device.is_active:
        raise MfaError("Your authenticator is already set up.")

    # record=False: the enrolment code authorises nothing but the enrolment itself, so
    # it must not burn the current 30-second window. Burning it would mean an ISP who
    # enrols and immediately withdraws is told "that code has already been used" and
    # made to stare at a countdown — a confusing failure, on the first thing they do,
    # in exchange for nothing (the money paths still burn their own codes).
    _check_totp(device, code, record=False)

    device.confirmed_at = timezone.now()
    device.save(update_fields=["confirmed_at"])
    return _issue_recovery_codes(device)


@transaction.atomic
def regenerate_recovery_codes(user, code: str) -> list[str]:
    """Needs a live code — otherwise anyone sitting at an unlocked console could mint
    themselves a permanent bypass of the second factor."""
    device = _active_device(user)
    verify(user, code)
    device.recovery_codes.all().delete()
    return _issue_recovery_codes(device)


@transaction.atomic
def disable(user, code: str) -> None:
    """Turning the guard OFF is itself a guarded action. An attacker who could simply
    disable MFA would not need to defeat it."""
    _active_device(user)
    verify(user, code)
    MfaDevice.objects.filter(user=user).delete()  # cascades the recovery codes
    logger.warning("MFA disabled for %s", user.pk)


def _issue_recovery_codes(device: MfaDevice) -> list[str]:
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(RECOVERY_CODE_COUNT)]
    RecoveryCode.objects.bulk_create(
        [RecoveryCode(device=device, code_hash=make_password(c)) for c in codes]
    )
    return codes


# ---- verification ------------------------------------------------------------


def is_enrolled(user) -> bool:
    """Asks the DATABASE, not the instance.

    `user.mfa_device` looks equivalent and is not: Django caches a *missed* reverse
    one-to-one lookup on the model instance, so anything that asked "do they have an
    authenticator?" before they enrolled keeps getting a cached "no" for the life of
    that object — even after they enrol. Invisible where every request loads a fresh
    user, and a silent, unreproducible hole in the money gate anywhere else.
    """
    return MfaDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()


def _active_device(user) -> MfaDevice:
    device = MfaDevice.objects.filter(user=user, confirmed_at__isnull=False).first()
    if device is None:
        raise MfaError("You have not set up an authenticator app.")
    return device


def verify(user, code: str) -> None:
    """Accept a TOTP code OR a single-use recovery code. Raises on anything else."""
    device = _active_device(user)
    submitted = (code or "").strip().replace(" ", "")
    if not submitted:
        raise MfaRequired("Enter the 6-digit code from your authenticator app.")

    if "-" in submitted:  # recovery codes carry a dash; TOTP codes never do
        _burn_recovery_code(device, submitted)
        return
    _check_totp(device, submitted)


def _check_totp(device: MfaDevice, code: str, *, record: bool = True) -> None:
    totp = pyotp.TOTP(device.secret)
    if not totp.verify(code, valid_window=VALID_WINDOW):
        raise MfaError("That code is not right. Check your authenticator app and try again.")

    if not record:
        return

    # Replay guard: a code is good for a 30-second window, so without this the same
    # six digits authorise two withdrawals.
    counter = int(timezone.now().timestamp()) // totp.interval
    if counter <= device.last_used_counter:
        raise MfaError("That code has already been used. Wait for the next one.")
    device.last_used_counter = counter
    device.save(update_fields=["last_used_counter"])


def _burn_recovery_code(device: MfaDevice, submitted: str) -> None:
    for candidate in device.recovery_codes.filter(used_at__isnull=True):
        if check_password(submitted, candidate.code_hash):
            candidate.used_at = timezone.now()
            candidate.save(update_fields=["used_at"])
            remaining = device.recovery_codes.filter(used_at__isnull=True).count()
            logger.warning(
                "Recovery code used for user %s — %s left", device.user_id, remaining
            )
            _warn_recovery_used(device.user, remaining)
            return
    raise MfaError("That code is not right. Check your authenticator app and try again.")


def _warn_recovery_used(user, remaining: int) -> None:
    """A recovery code being spent means either a lost phone or an intruder. The owner
    is the only one who knows which, so the owner gets told."""
    from django.core.mail import send_mail

    if not user.email:
        return
    try:
        send_mail(
            "A recovery code was used on your WIFI.OS account",
            f"Hi,\n\n"
            f"Someone signed a money action on your WIFI.OS account using a recovery "
            f"code instead of your authenticator app. You have {remaining} left.\n\n"
            "If this was you (a new phone, perhaps), you can ignore this.\n\n"
            "IF IT WASN'T, someone else has your recovery codes. Change your password "
            "and remove your authenticator immediately, then contact us.\n\n"
            "— WIFI.OS",
            getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@wifios.co.ke"),
            [user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Could not send the recovery-code warning for %s", user.pk)


def require(user, code: str) -> None:
    """The gate the money paths call.

    If they have an authenticator, it must be used. If they do not, we do NOT silently
    wave them through — we tell them to set one up, because this is the moment it
    matters and any other time they will not bother.
    """
    if not is_enrolled(user):
        raise MfaRequired(
            "Set up an authenticator app before moving money. It takes about a minute, "
            "and it is what stops somebody who gets into your console from emptying "
            "your wallet."
        )
    verify(user, code)
