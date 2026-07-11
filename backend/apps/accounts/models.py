from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.core.models import Operator
from apps.core.phone import normalize_msisdn


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra):
        if not phone:
            raise ValueError("Phone number is required")
        user = self.model(phone=normalize_msisdn(phone), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(phone, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """LOGIN ACCOUNTS ONLY: platform admins and ISP staff. Phone is globally
    unique because it is the login username. Customers are NOT users — they are
    `Subscriber` rows (see below), so the same phone can be a customer of several
    ISPs and still register its own ISP account without colliding here."""

    operator = models.ForeignKey(
        Operator, null=True, blank=True, on_delete=models.CASCADE, related_name="users"
    )
    phone = models.CharField(max_length=12, unique=True, db_index=True)
    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.name or self.phone


class Subscriber(models.Model):
    """A CUSTOMER of one ISP: a phone number that buys WiFi. Not a login account.
    Unique per (operator, phone) — the same human/phone is a distinct subscriber
    at each ISP they use, and may separately hold a staff `User` login."""

    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="subscribers"
    )
    phone = models.CharField(max_length=12, db_index=True)
    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operator", "phone"], name="subscriber_unique_operator_phone"
            )
        ]
        indexes = [models.Index(fields=["operator", "phone"])]

    def __str__(self):
        return f"{self.name or self.phone} @ {self.operator.slug}"

    @classmethod
    def get_or_create_for(cls, operator, phone, **defaults):
        return cls.objects.get_or_create(
            operator=operator, phone=normalize_msisdn(phone), defaults=defaults
        )
