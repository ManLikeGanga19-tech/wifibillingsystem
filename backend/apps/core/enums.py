"""Choice sets re-exported at MODULE level, for drf-spectacular's ENUM_NAME_OVERRIDES.

Why this file exists: overrides are given as dotted strings and resolved with
Django's `import_string`, which splits on the LAST dot — so
`apps.core.models.Operator.Status.choices` is read as "import the module
`apps.core.models.Operator.Status`" and fails. Nested class attributes simply
cannot be referenced that way.

Binding them to module-level names here makes them importable, and keeps the
schema's enum names derived from the real choices rather than duplicated by hand
(which would silently drift the day someone adds a status).

Imported lazily during schema generation, so importing models here is safe.
"""

from apps.notifications.models import GATEWAY_MODE_CHOICES as _GATEWAY_MODE_CHOICES
from apps.payments.models import Transaction

from .models import Operator

#: pending / active / suspended
OPERATOR_STATUS_CHOICES = Operator.Status.choices

#: pending / success / failed / timeout / reconciled
TRANSACTION_STATUS_CHOICES = Transaction.Status.choices

#: platform / own — SMS and email share ONE gateway-mode choice set, so it needs one name
#: in the schema. Without this, spectacular sees the same choices under two names
#: (SmsModeEnum, EmailModeEnum) and warns.
GATEWAY_MODE_CHOICES = _GATEWAY_MODE_CHOICES
