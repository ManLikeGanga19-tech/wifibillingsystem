"""Email, in two flavours.

DjangoEmailProvider is the PLATFORM path: Django's configured mail backend (Mailpit in
dev and staging, real SMTP in production) sending from our address.

SmtpEmailProvider is the ISP's OWN path: their SMTP server, their From: address, so
receipts land in a customer's inbox from a name that customer recognises — and so
deliverability is their domain's reputation, not ours.
"""

from django.conf import settings
from django.core.mail import EmailMessage, get_connection, send_mail

from .base import MessageProvider, ProviderError, SendResult

# An SMTP server that hangs must not hold a Celery worker forever; the send is retried.
SMTP_TIMEOUT = 20


class DjangoEmailProvider(MessageProvider):
    def send(self, message) -> SendResult:
        if not message.to_email:
            return SendResult(ok=False, error="Recipient has no email address")
        try:
            sent = send_mail(
                subject=message.subject or "Message from your WiFi provider",
                message=message.body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[message.to_email],
                fail_silently=False,
            )
        except Exception as exc:  # SMTP errors -> retried by the task
            return SendResult(ok=False, error=str(exc)[:255])
        return SendResult(ok=sent == 1, error="" if sent == 1 else "SMTP accepted 0 recipients")


class SmtpEmailProvider(MessageProvider):
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool,
        from_email: str,
        from_name: str = "",
    ):
        if not host:
            raise ProviderError("No SMTP host is configured")
        if not from_email:
            raise ProviderError("No From address is configured")
        self.host = host
        self.port = port or 587
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_email = from_email
        self.from_name = from_name

    @property
    def sender(self) -> str:
        return f'"{self.from_name}" <{self.from_email}>' if self.from_name else self.from_email

    def send(self, message) -> SendResult:
        if not message.to_email:
            return SendResult(ok=False, error="Recipient has no email address")
        try:
            connection = get_connection(
                backend="django.core.mail.backends.smtp.EmailBackend",
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                use_tls=self.use_tls,
                timeout=SMTP_TIMEOUT,
                fail_silently=False,
            )
            sent = EmailMessage(
                subject=message.subject or "Message from your WiFi provider",
                body=message.body,
                from_email=self.sender,
                to=[message.to_email],
                connection=connection,
            ).send()
        except Exception as exc:  # bad host/credentials/TLS -> retried by the task
            return SendResult(ok=False, error=str(exc)[:255])
        return SendResult(ok=sent == 1, error="" if sent == 1 else "SMTP accepted 0 recipients")
