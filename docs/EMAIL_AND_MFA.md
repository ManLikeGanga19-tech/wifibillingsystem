# Email and two-factor

Two mechanisms, two different jobs. Confusing them is how you end up with a system that
feels secure and is not.

| | Email code | Authenticator (TOTP) |
|---|---|---|
| **Proves** | someone can read that inbox | someone holds that phone |
| **Used for** | verifying the address at signup; the *fallback* factor for a payout-account change | authorising the actions that move money |
| **Also** | the NOTIFICATION channel — tripwires, invoices, warnings | nothing else |

## Why email cannot be replaced by TOTP

Signup verification is not authentication. Its job is to prove *the address works*,
because that address is the ISP's login identifier and the channel every warning goes
down. TOTP proves possession of a phone; it says nothing about whether the mailbox is
real. Swap it in and you get ISPs whose contact address is a typo and who never receive
a single notification.

## Why TOTP is better than an emailed code *as a guard*

An emailed code inherits every weakness of email: it can be delayed, land in spam, or be
eaten by a provider — and it falls entirely to whoever owns the ISP owner's Gmail. An
authenticator depends on nothing, works offline, costs nothing to send, and survives an
email compromise.

## What is gated

Money only, deliberately. **Login stays password-only** — an ISP who loses their phone
must lose access to their *payouts*, not to their whole business. They still have a
network to run while they recover.

- **Withdrawing** — enforced at the withdraw endpoint (`apps/billing/views.py`), not
  inside `request_payout`, because that service is also driven by platform tooling where
  a code from someone's phone has no meaning.
- **Changing the payout account** — if enrolled, TOTP is required and the emailed code
  is *not offered as an alternative*. Offering both would make the change only as strong
  as the weaker one. If not enrolled, the emailed code remains the path.

A tripwire **email always fires** when the payout account changes, whether TOTP
authorised it or not. Being asked and being told are different things.

## Recovery

Ten single-use codes at enrolment, shown once, stored hashed. Using one emails the owner
a warning — a spent recovery code means either a lost phone or an intruder, and only the
owner knows which.

If an ISP loses both phone and codes, the path is platform support removing the device
after an identity check. That is deliberately a human step: an automated reset would be
a bypass of the whole mechanism.

## Implementation notes worth not re-learning

- **The enrolment code does not burn the TOTP window.** It authorises nothing but the
  enrolment itself. Burning it meant an ISP who enrolled and immediately withdrew was
  told "that code has already been used" — a confusing failure on the first thing they
  do, for nothing.
- **`is_enrolled()` queries the database, never `user.mfa_device`.** Django caches a
  *missed* reverse one-to-one lookup on the instance, so anything that asked before
  enrolment keeps getting a cached "no" for the life of that object.
- **The replay guard is real.** A TOTP code is valid for its whole 30-second window, so
  without recording the last-honoured counter the same six digits authorise two
  withdrawals.
- The TOTP seed is Fernet-encrypted at rest, like router passwords. A database dump must
  not hand out working second factors.

---

# Dev and staging mail: Mailpit

`docker compose up` runs **Mailpit**. It speaks real SMTP on `1025` and swallows
everything. Read the messages at **http://localhost:8025**.

This replaced Django's console backend, which printed mail to stdout — unusable (you had
to `grep` container logs for a signup code) and dishonest, because it never exercised
the real send path: Celery task → SMTP → headers, subject, body.

## The rule for staging

**Staging must point at Mailpit too, not at a real SMTP provider.**

Staging will hold real ISP email addresses. A staging box wired to a real provider will
cheerfully email actual people invoices, suspension notices and payout warnings
generated from test data. Mailpit is what stands between a test run and a customer's
inbox.

Production is the only environment that gets real SMTP credentials, and they arrive as
environment variables (`EMAIL_BACKEND`, `EMAIL_HOST`, …) — never in code.
