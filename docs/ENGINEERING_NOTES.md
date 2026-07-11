# Engineering Notes — traps that cost real time

A running list of things that **fail silently**: the config looks right, nothing
errors, and the wrong thing quietly happens. Each entry says what bit us, why, and
the fix. Add to it whenever something costs more than an hour.

---

## OpenAPI / drf-spectacular

### 1. `ENUM_NAME_OVERRIDES` cannot reference a nested class attribute

```python
# LOOKS right. Does NOTHING.
"ENUM_NAME_OVERRIDES": {
    "OperatorStatus": "apps.core.models.Operator.Status.choices",
}
```

Values are resolved with Django's `import_string`, which splits on the **last
dot**. The above is read as *"import the module `apps.core.models.Operator.Status`,
then get its `choices` attribute"* → `ImportError` → the override is **silently
ignored**. A nested `Model.Status.choices` path can never work.

**Fix:** re-export at module level — [`backend/apps/core/enums.py`](../backend/apps/core/enums.py).
Derive it from the real `.choices` so it can never drift from the model:

```python
# apps/core/enums.py
OPERATOR_STATUS_CHOICES = Operator.Status.choices
```
```python
"ENUM_NAME_OVERRIDES": {"OperatorStatus": "apps.core.enums.OPERATOR_STATUS_CHOICES"}
```

### 2. An enum name must not collide with a *serializer* component name

`"TransactionStatus"` collided with the component generated from
`TransactionStatusSerializer` → *"components with identical names and different
identities … will very likely result in an incorrect schema"*. Renamed the enum to
`PaymentStatus`.

### 3. Write endpoints need BOTH `request=` and `responses=`

```python
@extend_schema(responses=OBJECT_RESPONSE)   # NOT enough for a POST
```

Supplying only `responses` still leaves spectacular "unable to guess serializer",
and it **drops the endpoint from the schema entirely** — a generated client would
not know the endpoint exists. Always give a POST/PUT/PATCH both.

> **Why any of this matters:** the schema is the API contract we generate clients
> from. Left alone, spectacular was omitting 23 endpoints and advertising the rest
> as unauthenticated. "Graceful fallback" is not graceful when the output is a lie.

---

## Auth & tenancy

### 4. A public endpoint must not merely be `AllowAny` — it must not AUTHENTICATE

`permission_classes = [AllowAny]` still runs the authentication classes. Two
production bugs came from this:

- **Cookies ignore the port.** A staff member logged into the console on `:4600`
  had their auth cookie sent to the captive portal on `:4700`. DRF authenticated
  them, enforced CSRF, and a *customer buying WiFi* got
  `CSRF Failed: Origin checking failed`.
- **Worse:** `PlanViewSet.get_queryset()` branched on `is_staff`, so that same
  stray cookie made the portal resolve the tenant from the STAFF's acting tenant
  instead of the router the customer is standing in front of — showing, and
  selling, the **wrong ISP's plans**.

**Fix:** inherit [`PublicAPIView`](../backend/apps/core/public.py)
(`authentication_classes = []`). A public endpoint serves an anonymous person and
must never authenticate anybody, not even by accident. Portal traffic (`?router=`)
also now wins over any authenticated identity, always.

### 5. Cookie auth reintroduces CSRF; Bearer never had it

A Bearer token is CSRF-immune by construction (an attacker's site cannot set our
header). A **cookie is attached by the browser automatically**, so moving the token
into a cookie made every write forgeable. Protected with `SameSite=Lax` **plus** a
double-submit token, enforced inside `CookieJWTAuthentication` for
cookie-authenticated unsafe requests only. Bearer stays exempt so scripts/CI keep
working.

### 6. A `TenantModelViewSet` overriding `get_queryset` MUST chain `super()`

Returning `Model.objects.annotate(...)` directly drops the operator filter and
leaks every tenant's rows. Bit us in `TowerViewSet` / `AccessPointViewSet`.

---

## Tests & tooling

### 7. Run pytest with the test settings, explicitly

The `api` container sets `DJANGO_SETTINGS_MODULE=config.settings.dev`, which
**overrides** the value in `pyproject.toml` (pytest-django reads the env var
first). Under dev settings `CELERY_TASK_ALWAYS_EAGER` is off, so ~12 async tests
fail spuriously.

```bash
docker compose exec -T -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest -q
```

### 8. Django's test client disables CSRF unless you ask for it

`APIClient()` sets `_dont_enforce_csrf_checks`, so a CSRF test would pass no matter
what. Use `APIClient(enforce_csrf_checks=True)` when the CSRF behaviour *is* the
thing under test.

### 9. The tests read your files; the container might not

The Django dev server's autoreloader can miss a change. Tests passed while the
running API 500'd on the same code path. If live behaviour disagrees with a green
suite, `docker compose restart api` before believing either.
