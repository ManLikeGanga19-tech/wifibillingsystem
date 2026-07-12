# Incident runbook

For the day something goes wrong with somebody else's money. Written now, calmly,
because nobody writes a good procedure at 2am with an ISP shouting on the phone.

**The first rule: STOP THE BLEEDING BEFORE YOU INVESTIGATE.** A withdrawal you prevent is
recoverable. A withdrawal you understand perfectly, after it left, is not.

---

## Emergency stops

```bash
cd /srv/wifios
C="docker compose -f deploy/docker-compose.prod.yml"

# Freeze ONE ISP (money in and out) — suspension flips can_transact to false.
$C exec api python manage.py shell -c "
from apps.core.models import Operator
op = Operator.objects.get(slug='acme')
op.status = Operator.Status.SUSPENDED; op.save()
print('suspended:', op.can_transact)"

# Freeze ONE user's payouts (a lost phone, a suspected takeover) — 24h freeze.
$C exec api python manage.py shell -c "
from django.utils import timezone
from apps.accounts.models import User
u = User.objects.get(email='owner@acme.co.ke')
u.mfa_reset_at = timezone.now(); u.save()
print('payouts frozen until', u.mfa_reset_at)"

# Freeze EVERYTHING. The whole platform stops taking and moving money; the consoles
# stay up so ISPs can see what is happening rather than staring at a dead site.
$C stop worker beat
```

Stopping `worker` halts provisioning and payouts. Payments already received are **not**
lost — callbacks still land and are recorded; they queue.

---

## "An ISP says money is missing"

The most common real incident, and usually **not** theft.

1. **Find the payment.** Every C2B payment lands whether or not we matched it:
   ```sql
   SELECT id, trans_id, amount, bill_ref_number, status, created_at
   FROM payments_c2bpayment
   WHERE msisdn LIKE '%712345678%' ORDER BY created_at DESC LIMIT 20;
   ```
2. **`status = 'unmatched'`** → they paid with a mistyped account number. The money is
   here and attributable. Fix the account number, re-run matching.
3. **`status = 'held'`** → their ISP had not added a settlement account yet. It is
   released automatically when they go live. Nobody lost anything.
4. **No row at all** → the money never reached us. Ask for the M-Pesa confirmation SMS.
   Check it went to *our* paybill and not the ISP's own (that bug existed once: the
   suspended-notice page sent PPPoE customers to the ISP's paybill, so payments bypassed
   the ledger entirely).
5. **A row, but no ledger entry** → *this is a real bug.* Stop and investigate; do not
   paper over it with a manual adjustment until you know why.

---

## "An ISP's payout account was changed and they didn't do it"

Assume takeover. Move fast.

1. **Freeze their payouts** (above).
2. **Read the audit log** — every step is recorded:
   ```sql
   SELECT created_at, action, actor_id, metadata FROM core_auditlog
   WHERE action LIKE 'settlement%' OR action LIKE 'mfa%'
   ORDER BY created_at DESC LIMIT 50;
   ```
   You are looking for `settlement_change_code_sent`, `settlement_account_changed`,
   `mfa_reset`. **Who** and **from where**.
3. **The cap held, probably.** A changed destination re-arms confirmation, so at most
   **one** payout can have left. Check `billing_payout` for anything `paid` with
   `confirmed_at IS NULL`.
4. Force a password reset, remove their MFA device (they re-enrol on a clean phone), and
   restore the correct settlement account.
5. If a payout *did* leave: it went to an M-Pesa paybill or a bank account, both of which
   are KYC'd to a real business. That is a police report with a name on it, and it is
   exactly why we settle only to accounts that carry identity.

---

## "A platform account is compromised"

The worst case. Every ISP's ledger is visible from Platform Control.

1. **Deactivate it immediately:**
   ```bash
   $C exec api python manage.py shell -c "
   from apps.accounts.models import User
   u = User.objects.get(email='...'); u.is_active = False; u.save()"
   ```
2. **Kill live impersonation grants** — this is how a platform account reaches tenants:
   ```bash
   $C exec api python manage.py shell -c "
   from django.utils import timezone
   from apps.core.models import ImpersonationGrant
   n = ImpersonationGrant.objects.filter(ended_at__isnull=True).update(ended_at=timezone.now())
   print('grants killed:', n)"
   ```
3. **Rotate `DJANGO_SECRET_KEY`** (invalidates every session on the platform) and restart.
4. Read `core_auditlog` for everything that actor did. **Money cannot have moved on their
   session** — `CanManageMoney` refuses every write while impersonating — but they could
   read everything, suspend tenants, and reset MFA devices. Check for `mfa_reset`.

---

## "Payments stopped arriving"

1. Is the API up? `curl -sI https://api.wifios.co.ke/api/v1/schema/`
2. Is Safaricom reaching us? Their callbacks hit `api.wifios.co.ke` — check Caddy's
   access log for POSTs to `/api/v1/payments/`.
3. **Did the callback URL change?** It is registered with Safaricom. If `api.wifios.co.ke`
   moved, they are posting into the void.
4. Reconciliation is the safety net: pending transactions older than 2 minutes get queried
   against Daraja every 5 minutes, so a *lost callback* is recovered automatically. If
   money is arriving in M-Pesa but not in the ledger, and reconciliation is running, the
   fault is in matching, not in delivery.

---

## "The server is gone"

1. New box, `docs/DEPLOYMENT.md`, same env file (**you kept `FIELD_ENCRYPTION_KEY`
   somewhere else — didn't you?**).
2. Restore the newest offsite dump (§6 of DEPLOYMENT).
3. **Reconcile before reopening.** Payments that landed after that dump exist at Safaricom
   and not in your database. Pull the M-Pesa statement for the gap and replay it. Do this
   *before* you let anybody withdraw.

---

## After every incident

Write down what happened and what would have caught it earlier. Then **add the test**.
Every safeguard in this system exists because something went wrong once — the C2B held
state, the one-payout cap, the impersonation money block. That is not embarrassing; that
is the system learning. What would be embarrassing is learning the same thing twice.
