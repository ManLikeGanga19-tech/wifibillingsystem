"""Tenant-safe relation fields.

A plain ModelSerializer FK exposes `Model.objects.all()` as its writable queryset,
so a tenant could point a ticket at another tenant's subscriber, or an expense at
another tenant's router (confirmed in the isolation audit). This field constrains
the choices to the request's acting tenant.
"""

from rest_framework import serializers

from .tenancy import acting_tenant


class TenantPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """PK field whose queryset is filtered to the acting operator.

    `scope_field` is the path from the related model to its Operator (default
    "operator"); pass e.g. None to skip operator scoping for models that aren't
    operator-owned but still need request awareness.
    """

    def __init__(self, *args, scope_field="operator", **kwargs):
        self.scope_field = scope_field
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        if qs is None:
            return qs
        request = self.context.get("request")
        operator = acting_tenant(request) if request else None
        if operator is not None and self.scope_field:
            qs = qs.filter(**{self.scope_field: operator})
        return qs
