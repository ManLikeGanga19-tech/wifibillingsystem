import { useCallback, useEffect, useRef, useState } from 'react';
import { Wifi, Smartphone, Ticket, ArrowLeft, Loader2, CheckCircle2, XCircle, RefreshCw, AlertTriangle } from 'lucide-react';
import {
  ApiError,
  getPaymentStatus,
  initiateStkPush,
  listPlans,
  redeemVoucher,
  retryProvision,
  getDeviceStatus,
  type PaymentStatus,
  type Plan,
  type SessionInfo,
} from './api/client';
import { getCaptiveParams, readPending, submitRouterLogin, writePending } from './captive';
import { formatCountdown, formatDuration, formatExpiry, formatKsh, formatSpeed, isValidKenyanPhone } from './format';

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 120_000;
// Last-resort net for the "connecting" phase: if the backend never resolves it to
// active or failed (Celery down, say), we still stop spinning and show the money-safe
// recovery screen. Generous, because the backend legitimately retries with backoff.
const CONNECT_GRACE_MS = 90_000;

type Stage =
  | { kind: 'browse' }
  | { kind: 'phone'; plan: Plan }
  | { kind: 'waiting'; planName: string; txId: string; startedAt: number }
  | { kind: 'paid'; status: PaymentStatus }
  // Paid, but we could not build the connection. A TERMINAL, money-safe, retryable
  // state — the thing that replaces the infinite spinner.
  | { kind: 'paid-not-connected'; txId: string; status: PaymentStatus }
  | { kind: 'failed'; reason: string; planName?: string }
  | { kind: 'voucher-ok'; session: SessionInfo };

export default function App() {
  const captive = getCaptiveParams();
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [tab, setTab] = useState<'mpesa' | 'voucher'>('mpesa');
  // The renewal prompt: set when the customer's previous session has ended (their tab
  // timed out to zero, or the router redirected them back here after cutting them off).
  // It turns the cold plan list into "your <plan> ended — tap to get back online".
  const [renew, setRenew] = useState<{ planName: string } | null>(null);
  // The phone they last paid with, kept in memory only (no storage) so a renewal in the
  // same tab is one tap. Not recovered across a fresh page load — a MAC-keyed lookup
  // returning phone numbers would be a PII leak on an open hotspot.
  const [lastPhone, setLastPhone] = useState('');
  const [stage, setStage] = useState<Stage>(() => {
    // Resume polling if the customer refreshed mid-payment. The in-flight payment
    // lives in the URL, not in storage — so a refresh (or a deploy) can never
    // leave them holding a stale object, and they never lose a payment they made.
    const pending = readPending();
    if (pending && Date.now() - pending.startedAt < POLL_TIMEOUT_MS) {
      return { kind: 'waiting', ...pending };
    }
    if (pending) writePending(null); // too old to still be in flight
    return { kind: 'browse' };
  });

  const loadPlans = useCallback(() => {
    setLoadError('');
    listPlans(captive.routerId)
      .then((r) => setPlans(r.results))
      .catch(() => setLoadError('Could not load plans. Check your connection and retry.'));
  }, [captive.routerId]);

  useEffect(loadPlans, [loadPlans]);

  // On load, greet a RETURNING device. If the router redirected them back here after
  // their session ended, show a renewal prompt instead of a cold plan list. Only when
  // we're browsing (not mid-payment), and only if they aren't already online.
  useEffect(() => {
    if (!captive.mac || stage.kind !== 'browse') return;
    getDeviceStatus(captive.mac, captive.routerId)
      .then((d) => {
        if (d.found && d.expired && d.plan_name) setRenew({ planName: d.plan_name });
      })
      .catch(() => {
        /* no prompt is fine — they still see the plan list */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- payment polling ----------------------------------------------------
  const pollRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (stage.kind !== 'waiting') return;
    const tick = async () => {
      let status: PaymentStatus;
      try {
        status = await getPaymentStatus(stage.txId);
      } catch {
        return; // transient network error — next tick retries
      }
      if (status.status === 'success' || status.status === 'reconciled') {
        // Payment landed. Now the connection — and this is where the old code could
        // spin forever, because it only recognised the ACTIVE case and had no exit
        // for a provisioning failure. The `provisioning` field gives us the three
        // real outcomes.
        if (status.provisioning === 'active') {
          writePending(null);
          setStage({ kind: 'paid', status });
        } else if (
          status.provisioning === 'failed' ||
          Date.now() - stage.startedAt > CONNECT_GRACE_MS
        ) {
          // Terminal, money-safe, retryable. NEVER leave them on a spinner after we
          // took their money.
          writePending(null);
          setStage({ kind: 'paid-not-connected', txId: stage.txId, status });
        }
        // else 'connecting' and still within grace — keep polling.
      } else if (status.status !== 'pending') {
        writePending(null);
        const reason =
          status.status === 'timeout'
            ? 'The M-Pesa prompt expired before the PIN was entered.'
            : status.result_desc || 'Payment was not completed.';
        setStage({ kind: 'failed', reason, planName: stage.planName });
      } else if (Date.now() - stage.startedAt > POLL_TIMEOUT_MS) {
        writePending(null);
        setStage({
          kind: 'failed',
          reason:
            'We have not received confirmation yet. If you entered your PIN, your access will be activated automatically within a few minutes — no need to pay again.',
          planName: stage.planName,
        });
      }
    };
    pollRef.current = window.setInterval(tick, POLL_INTERVAL_MS);
    tick();
    return () => window.clearInterval(pollRef.current);
  }, [stage]);

  const startPayment = async (plan: Plan, phone: string) => {
    setLastPhone(phone); // so an in-tab renewal is one tap
    setRenew(null);
    const resp = await initiateStkPush({
      phone,
      plan_id: plan.id,
      mac: captive.mac || undefined,
      router_id: captive.routerId,
    });
    const pending = { txId: resp.transaction_id, planName: plan.name, startedAt: Date.now() };
    writePending(pending);
    setStage({ kind: 'waiting', ...pending });
  };

  // Their time is up. Send them back to the plans to renew — this is the "redirect to
  // the payment screen instead of just disconnecting" the customer expects.
  const onExpired = (planName: string) => {
    writePending(null);
    setRenew({ planName });
    setTab('mpesa');
    setStage({ kind: 'browse' });
  };

  const connectDevice = (session: SessionInfo) => {
    if (captive.loginUrl) {
      submitRouterLogin(captive.loginUrl, session.hotspot_username, session.hotspot_password, captive.origUrl);
    }
  };

  // From the money-safe recovery screen: re-attempt the connection they paid for,
  // then resume polling so a success flips them straight to connected.
  const retryConnection = async (txId: string, planName: string) => {
    try {
      await retryProvision(txId);
    } catch {
      /* the poll below will still surface the real state */
    }
    const pending = { txId, planName, startedAt: Date.now() };
    writePending(pending);
    setStage({ kind: 'waiting', ...pending });
  };

  return (
    <div className="min-h-screen flex flex-col items-center px-4 py-6">
      {/* Brand header */}
      <header className="w-full max-w-md flex items-center gap-2.5 mb-6">
        <div className="w-9 h-9 bg-[#141414] flex items-center justify-center">
          <Wifi className="h-5 w-5 text-[#E4E3E0]" />
        </div>
        <div>
          <h1 className="font-bold text-lg leading-none tracking-tight">WIFI.OS</h1>
          <p className="text-xs text-[#141414]/60">Fast WiFi. Lipa na M-Pesa.</p>
        </div>
      </header>

      <main className="w-full max-w-md flex-1">
        {stage.kind === 'browse' && (
          <>
            <div className="flex border border-[#141414] mb-5">
              <TabButton active={tab === 'mpesa'} onClick={() => setTab('mpesa')} icon={<Smartphone className="h-4 w-4" />}>
                Buy with M-Pesa
              </TabButton>
              <TabButton active={tab === 'voucher'} onClick={() => setTab('voucher')} icon={<Ticket className="h-4 w-4" />}>
                Use a Voucher
              </TabButton>
            </div>

            {tab === 'mpesa' && (
              <PlanList
                plans={plans}
                loadError={loadError}
                renew={renew}
                onRetry={loadPlans}
                onSelect={(plan) => setStage({ kind: 'phone', plan })}
              />
            )}
            {tab === 'voucher' && (
              <VoucherForm
                onRedeemed={(session) => setStage({ kind: 'voucher-ok', session })}
                mac={captive.mac}
                routerId={captive.routerId}
              />
            )}
          </>
        )}

        {stage.kind === 'phone' && (
          <PhoneEntry
            plan={stage.plan}
            defaultPhone={lastPhone}
            onBack={() => setStage({ kind: 'browse' })}
            onSubmit={startPayment}
          />
        )}

        {stage.kind === 'waiting' && (
          <Card>
            <div className="flex flex-col items-center text-center py-6 gap-4">
              <Loader2 className="h-10 w-10 animate-spin text-[#141414]" />
              <div>
                <h2 className="font-bold text-lg">Check your phone</h2>
                <p className="text-sm text-[#141414]/70 mt-1.5 leading-relaxed">
                  We sent an M-Pesa prompt for <b>{stage.planName}</b>.
                  <br />
                  Enter your M-Pesa PIN to complete the payment.
                </p>
              </div>
              <p className="text-xs text-[#141414]/50">This page updates automatically — do not close it.</p>
            </div>
          </Card>
        )}

        {stage.kind === 'paid' && (
          <SuccessCard
            status={stage.status}
            hasRouterLogin={!!captive.loginUrl}
            onConnect={connectDevice}
            onExpired={onExpired}
          />
        )}

        {stage.kind === 'paid-not-connected' && (
          <Card>
            <div className="flex flex-col items-center text-center py-4 gap-3">
              {/* Amber, NOT red. Red says "your money is gone"; this is "money safe,
                  connection pending" — a completely different feeling, and the true one. */}
              <AlertTriangle className="h-12 w-12 text-[#B26B00]" />
              <h2 className="font-bold text-lg">Payment received — connecting you</h2>
              <p className="text-sm text-[#141414]/70 leading-relaxed">
                {stage.status.provision_message ||
                  "We received your payment, but couldn't connect you automatically. Your payment is safe."}
              </p>
              {stage.status.mpesa_receipt && (
                <p className="text-xs font-mono text-[#141414]/50">
                  M-Pesa receipt: <b>{stage.status.mpesa_receipt}</b>
                </p>
              )}
              <button
                onClick={() => retryConnection(stage.txId, '')}
                className="mt-2 w-full bg-[#228B22] text-white font-bold py-3.5 flex items-center justify-center gap-2 active:opacity-85"
              >
                <RefreshCw className="h-4 w-4" /> Retry connection
              </button>
              <p className="text-xs text-[#141414]/50 leading-relaxed">
                No need to pay again. If it still doesn&apos;t connect, show this screen to
                the WiFi operator — your receipt above proves your payment.
              </p>
            </div>
          </Card>
        )}

        {stage.kind === 'voucher-ok' && (
          <Card>
            <div className="flex flex-col items-center text-center py-4 gap-3">
              <CheckCircle2 className="h-12 w-12 text-[#228B22]" />
              <h2 className="font-bold text-lg">Voucher accepted!</h2>
              <p className="text-sm text-[#141414]/70">
                Your access is active until <b>{formatExpiry(stage.session.expires_at)}</b>.
              </p>
              <CredentialBox session={stage.session} />
              {captive.loginUrl && <ConnectButton onClick={() => connectDevice(stage.session)} />}
            </div>
          </Card>
        )}

        {stage.kind === 'failed' && (
          <Card>
            <div className="flex flex-col items-center text-center py-4 gap-3">
              <XCircle className="h-12 w-12 text-[#B22222]" />
              <h2 className="font-bold text-lg">Payment not completed</h2>
              <p className="text-sm text-[#141414]/70 leading-relaxed">{stage.reason}</p>
              <button
                onClick={() => setStage({ kind: 'browse' })}
                className="mt-2 w-full bg-[#141414] text-[#E4E3E0] font-bold py-3.5 flex items-center justify-center gap-2 active:opacity-80"
              >
                <RefreshCw className="h-4 w-4" /> Try again
              </button>
            </div>
          </Card>
        )}
      </main>

      <footer className="w-full max-w-md text-center text-xs text-[#141414]/40 mt-8">
        Need help? Talk to the site attendant or call your provider.
      </footer>
    </div>
  );
}

// ---- pieces ---------------------------------------------------------------

function Card({ children }: { children: React.ReactNode }) {
  return <div className="bg-white border border-[#141414] p-5">{children}</div>;
}

function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-3 text-sm font-bold flex items-center justify-center gap-2 transition ${
        active ? 'bg-[#141414] text-[#E4E3E0]' : 'bg-white text-[#141414]'
      }`}
    >
      {icon}
      {children}
    </button>
  );
}

function PlanList({
  plans,
  loadError,
  renew,
  onRetry,
  onSelect,
}: {
  plans: Plan[] | null;
  loadError: string;
  renew: { planName: string } | null;
  onRetry: () => void;
  onSelect: (plan: Plan) => void;
}) {
  if (loadError)
    return (
      <Card>
        <p className="text-sm text-center text-[#141414]/70">{loadError}</p>
        <button onClick={onRetry} className="mt-3 w-full bg-[#141414] text-[#E4E3E0] font-bold py-3">
          Retry
        </button>
      </Card>
    );
  if (plans === null)
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-[#141414]/50" />
      </div>
    );
  return (
    <div className="space-y-3">
      {renew && (
        <div className="border border-[#B26B00] bg-[#FFF8EC] p-3.5 flex items-start gap-2.5">
          <RefreshCw className="h-4 w-4 text-[#B26B00] shrink-0 mt-0.5" />
          <p className="text-sm leading-relaxed">
            <b>Your {renew.planName} has ended.</b>
            <br />
            <span className="text-[#141414]/70">Pick a plan below to get back online.</span>
          </p>
        </div>
      )}
      {plans.map((plan) => (
        <button
          key={plan.id}
          onClick={() => onSelect(plan)}
          className="w-full bg-white border border-[#141414] p-4 flex items-center justify-between text-left active:bg-[#f0efec] transition"
        >
          <div>
            <p className="font-bold">{plan.name}</p>
            <p className="text-xs text-[#141414]/60 mt-0.5">
              {formatDuration(plan.duration)} • {formatSpeed(plan.download_kbps)} down
              {plan.shared_users && plan.shared_users > 1 ? ` • ${plan.shared_users} devices` : ''}
            </p>
          </div>
          <span className="font-black text-lg text-[#228B22] whitespace-nowrap">{formatKsh(plan.price)}</span>
        </button>
      ))}
      {plans.length === 0 && (
        <Card>
          <p className="text-sm text-center text-[#141414]/60">
            No plans available. Please connect to the WiFi network first, then open this
            page from the login screen.
          </p>
        </Card>
      )}
    </div>
  );
}

function PhoneEntry({
  plan,
  defaultPhone,
  onBack,
  onSubmit,
}: {
  plan: Plan;
  defaultPhone?: string;
  onBack: () => void;
  onSubmit: (plan: Plan, phone: string) => Promise<void>;
}) {
  const [phone, setPhone] = useState(defaultPhone ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const valid = isValidKenyanPhone(phone);

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    setError('');
    try {
      await onSubmit(plan, phone);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach M-Pesa. Please try again.');
      setBusy(false);
    }
  };

  return (
    <Card>
      <button onClick={onBack} className="flex items-center gap-1 text-sm text-[#141414]/60 mb-4">
        <ArrowLeft className="h-4 w-4" /> All plans
      </button>
      <div className="flex items-center justify-between mb-5">
        <div>
          <p className="font-bold">{plan.name}</p>
          <p className="text-xs text-[#141414]/60">{formatDuration(plan.duration)} • {formatSpeed(plan.download_kbps)}</p>
        </div>
        <span className="font-black text-xl text-[#228B22]">{formatKsh(plan.price)}</span>
      </div>
      <label className="text-sm font-bold block mb-1.5">M-Pesa phone number</label>
      <input
        type="tel"
        inputMode="tel"
        autoFocus
        placeholder="07XX XXX XXX"
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
        className="w-full border border-[#141414] p-3.5 text-lg tracking-wide outline-none focus:bg-[#f8f8f6]"
      />
      {error && <p className="text-sm text-[#B22222] mt-2">{error}</p>}
      <button
        onClick={submit}
        disabled={!valid || busy}
        className="mt-4 w-full bg-[#228B22] disabled:bg-[#141414]/20 text-white font-bold py-4 text-base flex items-center justify-center gap-2 active:opacity-85 transition"
      >
        {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Smartphone className="h-5 w-5" />}
        {busy ? 'Sending prompt…' : `Pay ${formatKsh(plan.price)} with M-Pesa`}
      </button>
      <p className="text-xs text-[#141414]/50 mt-3 text-center">
        You will receive an M-Pesa prompt on this number. Enter your PIN to pay.
      </p>
    </Card>
  );
}

function SuccessCard({
  status,
  hasRouterLogin,
  onConnect,
  onExpired,
}: {
  status: PaymentStatus;
  hasRouterLogin: boolean;
  onConnect: (session: SessionInfo) => void;
  onExpired: (planName: string) => void;
}) {
  const session = status.session!;
  // Auto-connect the device shortly after success when the router gave us a login URL
  useEffect(() => {
    if (!hasRouterLogin) return;
    const t = window.setTimeout(() => onConnect(session), 2500);
    return () => window.clearTimeout(t);
  }, [hasRouterLogin, onConnect, session]);

  // Live countdown. When the paid time runs out AND the customer still has this tab
  // open, we send them straight back to the plans to renew — instead of them silently
  // dropping offline with no idea why or what to do.
  const [left, setLeft] = useState(() => formatCountdown(session.expires_at));
  useEffect(() => {
    const t = window.setInterval(() => {
      const c = formatCountdown(session.expires_at);
      setLeft(c);
      if (!c) {
        window.clearInterval(t);
        onExpired(status.plan_name || 'session');
      }
    }, 1000);
    return () => window.clearInterval(t);
  }, [session.expires_at, status.plan_name, onExpired]);

  return (
    <Card>
      <div className="flex flex-col items-center text-center py-4 gap-3">
        <CheckCircle2 className="h-12 w-12 text-[#228B22]" />
        <h2 className="font-bold text-lg">Payment received!</h2>
        <p className="text-sm text-[#141414]/70">
          Receipt <b className="font-mono">{status.mpesa_receipt}</b>
          <br />
          Access active until <b>{formatExpiry(session.expires_at)}</b>
        </p>
        {left && (
          <div className="w-full border border-[#228B22]/40 bg-[#228B22]/5 py-2">
            <p className="text-[11px] uppercase tracking-wide text-[#141414]/50">Time remaining</p>
            <p className="font-mono font-black text-2xl text-[#228B22] tabular-nums">{left}</p>
          </div>
        )}
        <CredentialBox session={session} />
        {hasRouterLogin ? (
          <>
            <p className="text-xs text-[#141414]/50">Connecting you automatically…</p>
            <ConnectButton onClick={() => onConnect(session)} />
          </>
        ) : (
          <p className="text-xs text-[#141414]/50">
            Use these details on the WiFi login page to connect other devices.
          </p>
        )}
      </div>
    </Card>
  );
}

function CredentialBox({ session }: { session: SessionInfo }) {
  return (
    <div className="w-full border border-[#141414]/30 bg-[#f8f8f6] p-3 font-mono text-sm space-y-1">
      <div className="flex justify-between"><span className="text-[#141414]/50">Username</span><b>{session.hotspot_username}</b></div>
      <div className="flex justify-between"><span className="text-[#141414]/50">Password</span><b>{session.hotspot_password}</b></div>
    </div>
  );
}

function ConnectButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full bg-[#141414] text-[#E4E3E0] font-bold py-3.5 flex items-center justify-center gap-2 active:opacity-80"
    >
      <Wifi className="h-4 w-4" /> Connect now
    </button>
  );
}

function VoucherForm({
  onRedeemed,
  mac,
  routerId,
}: {
  onRedeemed: (session: SessionInfo) => void;
  mac: string;
  routerId: number | null;
}) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async () => {
    if (code.trim().length < 4 || busy) return;
    setBusy(true);
    setError('');
    try {
      const resp = await redeemVoucher({ code: code.trim(), mac: mac || undefined, router_id: routerId });
      onRedeemed({
        hotspot_username: resp.hotspot_username,
        hotspot_password: resp.hotspot_password,
        expires_at: resp.expires_at,
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not redeem the voucher. Try again.');
      setBusy(false);
    }
  };

  return (
    <Card>
      <label className="text-sm font-bold block mb-1.5">Voucher code</label>
      <input
        type="text"
        autoCapitalize="characters"
        autoCorrect="off"
        placeholder="e.g. KIB7X2M4"
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
        className="w-full border border-[#141414] p-3.5 text-lg tracking-[0.2em] font-mono uppercase outline-none focus:bg-[#f8f8f6]"
      />
      {error && <p className="text-sm text-[#B22222] mt-2">{error}</p>}
      <button
        onClick={submit}
        disabled={code.trim().length < 4 || busy}
        className="mt-4 w-full bg-[#141414] disabled:bg-[#141414]/20 text-[#E4E3E0] font-bold py-4 flex items-center justify-center gap-2 active:opacity-85"
      >
        {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Ticket className="h-5 w-5" />}
        {busy ? 'Checking…' : 'Redeem voucher'}
      </button>
      <p className="text-xs text-[#141414]/50 mt-3 text-center">
        Voucher cards are sold by site attendants and local shops.
      </p>
    </Card>
  );
}
