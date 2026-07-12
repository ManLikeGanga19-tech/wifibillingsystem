import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import {
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  Loader2,
  RefreshCw,
  ShieldCheck,
  X,
} from 'lucide-react';
import { STEPS, signup, SignupError, type Availability, type SignupState } from '../lib/signup';

/**
 * The 5-step ISP signup.
 *
 * THE SERVER OWNS THE WIZARD. We never decide which step to show — we ask
 * (GET /state/) and render what comes back. That is not ceremony: it is what makes a
 * refresh, a closed laptop, or a clicked email link resume exactly where they left
 * off, with no browser storage anywhere (the hard rule of this system).
 *
 * So this component holds only what is in front of the user's fingers right now: the
 * text in the inputs. Everything durable lives in Postgres behind an httpOnly cookie.
 */

const LABELS = ['You', 'Verify', 'Your ISP', 'Location', 'Password'];

export default function SignupWizard() {
  const [state, setState] = useState<SignupState | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ console_url: string; next: string } | null>(null);

  const refresh = useCallback(async () => {
    try {
      setState(await signup.state());
    } catch {
      setError('We could not reach the server. Check your connection and try again.');
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  /** One place where every step's submit lands, so every step gets the same error
   *  handling and nobody forgets to clear `busy` on a throw. */
  const run = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof SignupError ? err.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  };

  if (!state) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-ink/40" />
      </div>
    );
  }

  if (done || state.step === STEPS.DONE) {
    return <Finished consoleUrl={done?.console_url ?? state.console_url ?? ''} next={done?.next} />;
  }

  const step = state.step;

  return (
    <div className="border border-ink bg-card">
      <Progress step={step} />

      <div className="p-5 sm:p-7">
        {error && (
          <p
            role="alert"
            className="mb-4 flex items-start gap-2 border border-[#B22222] bg-[#B22222]/5 p-2.5 font-mono text-xs text-[#B22222]"
          >
            <X className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {error}
          </p>
        )}

        {step === STEPS.IDENTITY && <Identity state={state} busy={busy} run={run} />}
        {step === STEPS.VERIFY_EMAIL && <Verify state={state} busy={busy} run={run} />}
        {step === STEPS.COMPANY && <Company state={state} busy={busy} run={run} />}
        {step === STEPS.DETAILS && <Details state={state} busy={busy} run={run} />}
        {step === STEPS.SECURE && (
          <Secure state={state} busy={busy} run={run} onDone={setDone} setError={setError} />
        )}
      </div>
    </div>
  );
}

/* ---------- step 1: who are you ---------------------------------------------- */

function Identity({ state, busy, run }: StepProps) {
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    run(() => signup.start(String(f.get('full_name')), String(f.get('email'))));
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Head
        title="Start your ISP account"
        sub="Two fields. We'll email you a code to prove the address is yours."
      />
      <Field label="Your full name">
        <input
          name="full_name"
          required
          autoFocus
          autoComplete="name"
          defaultValue={state.known.full_name ?? ''}
          placeholder="Jane Wanjiru"
          className={INPUT}
        />
      </Field>
      <Field
        label="Work email"
        hint="This becomes your login, and where we send the code that protects your payouts."
      >
        <input
          name="email"
          type="email"
          required
          autoComplete="email"
          defaultValue={state.known.email ?? ''}
          placeholder="you@company.co.ke"
          className={INPUT}
        />
      </Field>
      <Submit busy={busy}>Send verification code</Submit>
    </form>
  );
}

/* ---------- step 2: the code -------------------------------------------------- */

function Verify({ state, busy, run }: StepProps) {
  const [code, setCode] = useState('');
  const [cooldown, setCooldown] = useState(state.resend_available_in ?? 0);
  const submitted = useRef(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  // AUTO-SUBMIT on the 6th digit. Nobody wants to type a code and then hunt for a
  // button. The ref stops a re-render from firing it twice.
  useEffect(() => {
    if (code.length === 6 && !submitted.current && !busy) {
      submitted.current = true;
      run(() => signup.verify(code));
    }
    if (code.length < 6) submitted.current = false;
  }, [code, busy, run]);

  return (
    <div className="space-y-4">
      <Head
        title="Check your email"
        sub={`We sent a 6-digit code to ${state.known.email ?? 'your address'}. It expires shortly.`}
      />
      <Field label="Verification code">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
          autoFocus
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="123456"
          className="mt-1 w-full border border-ink bg-white p-3 text-center font-mono text-2xl font-black tracking-[0.4em] outline-none focus:bg-hover"
        />
      </Field>

      <div className="flex items-center gap-3">
        {busy && <Loader2 className="h-4 w-4 animate-spin text-ink/50" />}
        <button
          type="button"
          disabled={cooldown > 0 || busy}
          onClick={() => {
            setCooldown(60);
            run(() => signup.resend());
          }}
          className="inline-flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase text-ink/70 underline-offset-4 hover:underline disabled:cursor-not-allowed disabled:no-underline disabled:opacity-40"
        >
          <RefreshCw className="h-3 w-3" />
          {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend the code'}
        </button>
      </div>

      <p className="font-mono text-[10px] leading-relaxed text-ink/50">
        No code? Check spam. We say the same thing whether or not an account already
        exists for that address — that is on purpose, so nobody can use this page to
        discover who our customers are.
      </p>
    </div>
  );
}

/* ---------- step 3: name it --------------------------------------------------- */

function Company({ state, busy, run }: StepProps) {
  const [name, setName] = useState(state.known.company_name ?? '');
  const [slug, setSlug] = useState(state.known.slug ?? '');
  const [touchedSlug, setTouchedSlug] = useState(Boolean(state.known.slug));
  const [check, setCheck] = useState<Availability | null>(null);
  const [checking, setChecking] = useState(false);

  // Debounced, because this fires as they type and the endpoint is rate-limited.
  useEffect(() => {
    if (!name && !slug) {
      setCheck(null);
      return;
    }
    setChecking(true);
    const t = setTimeout(async () => {
      try {
        const result = await signup.availability({
          name: name || undefined,
          slug: touchedSlug ? slug || undefined : undefined,
        });
        setCheck(result);
        // Server-suggested slug, until they take the wheel themselves.
        if (!touchedSlug && result.slug) setSlug(result.slug);
      } catch {
        setCheck(null); // advisory only — never block them on a failed check
      } finally {
        setChecking(false);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [name, slug, touchedSlug]);

  const nameTaken = check?.name_available === false;
  const slugTaken = check?.slug_available === false;
  const domain = check?.domain ?? (slug ? `${slug}.wifios.co.ke` : '');

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run(() => signup.company(name, slug));
      }}
      className="space-y-4"
    >
      <Head title="Name your ISP" sub="This is what your customers see, and it becomes your address." />

      <Field label="ISP / company name" error={nameTaken ? 'That name is already registered.' : ''}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          autoFocus
          placeholder="Acme Networks"
          className={INPUT}
        />
      </Field>

      <Field label="Your address">
        <div className="mt-1 flex items-stretch border border-ink bg-white">
          <input
            value={slug}
            onChange={(e) => {
              setTouchedSlug(true);
              setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''));
            }}
            required
            placeholder="acme"
            className="min-w-0 flex-1 bg-transparent p-2.5 font-mono text-sm outline-none"
          />
          <span className="flex items-center border-l border-ink bg-hover px-2.5 font-mono text-xs text-ink/60">
            .wifios.co.ke
          </span>
        </div>
      </Field>

      <div className="min-h-[20px] font-mono text-[11px]">
        {checking && <span className="text-ink/40">Checking…</span>}
        {!checking && slug && slugTaken && (
          <span className="text-[#B22222]">
            {domain} is taken.
            {check?.suggestion && (
              <>
                {' '}
                <button
                  type="button"
                  onClick={() => {
                    setTouchedSlug(true);
                    setSlug(check.suggestion!);
                  }}
                  className="font-bold underline"
                >
                  Take {check.suggestion} instead
                </button>
              </>
            )}
          </span>
        )}
        {!checking && slug && check?.slug_available && (
          <span className="inline-flex items-center gap-1 text-money">
            <Check className="h-3 w-3" /> {domain} is yours.
          </span>
        )}
      </div>

      <Submit busy={busy} disabled={!name || !slug || nameTaken || slugTaken}>
        Claim it
      </Submit>
    </form>
  );
}

/* ---------- step 4: where do you operate -------------------------------------- */

function Details({ state, busy, run }: StepProps) {
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    run(() =>
      signup.details({
        county: String(f.get('county')),
        phone: String(f.get('phone')),
        referral_source: String(f.get('referral_source') ?? ''),
      })
    );
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Head title="Where do you operate?" sub="So we can support you, and pay you, in the right place." />

      <Field label="County">
        <select name="county" required defaultValue={state.known.county ?? ''} className={INPUT}>
          <option value="" disabled>
            Select a county
          </option>
          {state.counties.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Phone number" hint="You can sign in with this or your email — whichever you remember.">
        <input
          name="phone"
          type="tel"
          required
          autoComplete="tel"
          defaultValue={state.known.phone ?? ''}
          placeholder="0712 345 678"
          className={INPUT}
        />
      </Field>

      <Field label="How did you hear about us?">
        <select
          name="referral_source"
          defaultValue={state.known.referral_source ?? ''}
          className={INPUT}
        >
          <option value="">Prefer not to say</option>
          {state.referral_sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </Field>

      <Submit busy={busy}>Continue</Submit>
    </form>
  );
}

/* ---------- step 5: secure it ------------------------------------------------- */

function Secure({
  state,
  busy,
  run,
  onDone,
  setError,
}: StepProps & {
  onDone: (r: { console_url: string; next: string }) => void;
  setError: (m: string) => void;
}) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [accept, setAccept] = useState(false);
  const [working, setWorking] = useState(false);

  const tooShort = password.length > 0 && password.length < 8;
  const mismatch = confirm.length > 0 && confirm !== password;

  // Not routed through `run`: on success there is no next step to refresh into —
  // the draft is spent and its cookie is gone. We go straight to the finish line.
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (working) return;
    setWorking(true);
    setError('');
    try {
      const result = await signup.complete(password, confirm, accept);
      onDone({ console_url: result.console_url, next: result.next });
    } catch (err) {
      setError(err instanceof SignupError ? err.message : 'Something went wrong.');
    } finally {
      setWorking(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Head title="Secure your account" sub="Last step. Then your console is live." />

      <Field label="Password" error={tooShort ? 'At least 8 characters.' : ''}>
        <div className="relative">
          <input
            type={show ? 'text' : 'password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoFocus
            autoComplete="new-password"
            className={`${INPUT} pr-10`}
          />
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            aria-label={show ? 'Hide password' : 'Show password'}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-ink/50 hover:text-ink"
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </Field>

      <Field label="Confirm password" error={mismatch ? 'These do not match.' : ''}>
        <input
          type={show ? 'text' : 'password'}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
          autoComplete="new-password"
          className={INPUT}
        />
      </Field>

      <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
        <input
          type="checkbox"
          checked={accept}
          onChange={(e) => setAccept(e.target.checked)}
          required
          className="mt-0.5 h-4 w-4 shrink-0 accent-[#141414]"
        />
        <span className="text-ink/80">
          I agree to the{' '}
          <a href="/terms" target="_blank" className="font-bold underline">
            Terms of Service
          </a>{' '}
          and{' '}
          <a href="/privacy" target="_blank" className="font-bold underline">
            Privacy Policy
          </a>
          .
        </span>
      </label>

      <Submit busy={busy || working} disabled={!accept || tooShort || mismatch || !password}>
        Create my ISP
      </Submit>

      <p className="font-mono text-[10px] leading-relaxed text-ink/50">
        Your first month is free. You can build everything before you take a single
        payment — no card, no sales call.
      </p>
    </form>
  );
}

/* ---------- done -------------------------------------------------------------- */

function Finished({ consoleUrl, next }: { consoleUrl: string; next?: string }) {
  return (
    <div className="border border-ink bg-card p-6 text-center sm:p-10">
      <div className="mx-auto grid h-12 w-12 place-items-center border border-money bg-money text-white">
        <Check className="h-6 w-6" />
      </div>
      <h2 className="mt-4 font-serif text-2xl font-bold">Your ISP is live.</h2>
      <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink/70">
        {next ??
          'Add your settlement account to switch payments on. Until then you can configure everything else — your first month is free.'}
      </p>

      {consoleUrl && (
        <>
          <p className="mt-5 font-mono text-[10px] font-bold uppercase tracking-widest text-ink/50">
            Your console
          </p>
          <p className="mt-1 break-all font-mono text-sm font-bold">{consoleUrl}</p>
          <a
            href={consoleUrl}
            className="mt-5 inline-flex items-center gap-2 border border-money bg-money px-5 py-3 font-mono text-xs font-bold uppercase text-white transition hover:opacity-85"
          >
            Open my console
            <ArrowRight className="h-3.5 w-3.5" />
          </a>
        </>
      )}
    </div>
  );
}

/* ---------- chrome ------------------------------------------------------------ */

interface StepProps {
  state: SignupState;
  busy: boolean;
  run: (action: () => Promise<unknown>) => Promise<void>;
}

const INPUT =
  'mt-1 w-full border border-ink bg-white p-2.5 font-mono text-sm outline-none focus:bg-hover';

function Progress({ step }: { step: number }) {
  return (
    <ol className="flex border-b border-ink">
      {LABELS.map((label, i) => {
        const n = i + 1;
        const state = n < step ? 'done' : n === step ? 'now' : 'todo';
        return (
          <li
            key={label}
            aria-current={state === 'now' ? 'step' : undefined}
            className={`flex flex-1 items-center justify-center gap-1.5 border-r border-ink px-1 py-2.5 font-mono text-[10px] font-bold uppercase last:border-r-0 ${
              state === 'now'
                ? 'bg-ink text-paper'
                : state === 'done'
                  ? 'bg-money/10 text-money'
                  : 'text-ink/35'
            }`}
          >
            {state === 'done' ? <Check className="h-3 w-3" /> : <span>{n}</span>}
            <span className="hidden sm:inline">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function Head({ title, sub }: { title: string; sub: string }) {
  return (
    <div>
      <h1 className="font-serif text-xl font-bold sm:text-2xl">{title}</h1>
      <p className="mt-1 text-xs leading-relaxed text-ink/60">{sub}</p>
    </div>
  );
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="font-mono text-[10px] font-bold uppercase tracking-wide text-ink/60">
        {label}
      </span>
      {children}
      {error ? (
        <span className="mt-1 block font-mono text-[10px] text-[#B22222]">{error}</span>
      ) : (
        hint && <span className="mt-1 block font-mono text-[10px] text-ink/45">{hint}</span>
      )}
    </label>
  );
}

function Submit({
  busy,
  disabled,
  children,
}: {
  busy: boolean;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="submit"
      disabled={busy || disabled}
      className="inline-flex w-full items-center justify-center gap-2 border border-money bg-money px-4 py-3 font-mono text-xs font-bold uppercase text-white transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
      {children}
    </button>
  );
}
