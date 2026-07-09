"""Email via Django's mail framework: console backend in dev, SMTP in production
(EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD env vars)."""

from django.conf import settings
from django.core.mail import send_mail

from .base import MessageProvider, SendResult


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
