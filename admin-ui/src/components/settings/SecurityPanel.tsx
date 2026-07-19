import { useEffect, useState } from 'react';
import { Loader2, Check, Lock, ShieldCheck, Smartphone, Copy, AlertTriangle } from 'lucide-react';
import { api, ApiError, MfaStatus, MfaSetup } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-3 border border-[#B26B00]/40 bg-[#FFF8EC] p-3">
      <p className="flex items-center gap-1.5 text-xs font-bold text-[#7a4a00]">
        <AlertTriangle className="h-3.5 w-3.5" /> Save your recovery codes
      </p>
      <p className="mt-1 text-[11px] text-[#7a4a00]">
        These are the ONLY way back into your money if you lose your phone. Store them offline — we
        cannot show them again.
      </p>
      <div className="mt-2 grid grid-cols-2 gap-1.5">
        {codes.map((c) => (
          <code key={c} className="border border-[#141414]/15 bg-white px-2 py-1 text-center font-mono text-xs">
            {c}
          </code>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button
          onClick={() => {
            navigator.clipboard?.writeText(codes.join('\n'));
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="flex items-center gap-1 border border-[#141414] bg-[#141414] px-2.5 py-1.5 text-[10px] font-bold uppercase text-[#E4E3E0] hover:bg-[#228B22]"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? 'Copied' : 'Copy all'}
        </button>
        <button onClick={onDone} className="text-[11px] font-bold uppercase hover:underline">
          I've saved them
        </button>
      </div>
    </div>
  );
}

export default function SecurityPanel() {
  // Change password
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [savingPw, setSavingPw] = useState(false);

  // 2FA
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [enrolCode, setEnrolCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [manageCode, setManageCode] = useState('');

  const loadStatus = () =>
    api.mfa.status().then(setStatus).catch(() => toast('error', 'Could not load 2FA status.'));

  useEffect(() => {
    loadStatus();
  }, []);

  // --- change password -----------------------------------------------------
  const changePassword = async () => {
    if (savingPw) return;
    if (next.length < 8) {
      toast('error', 'Use at least 8 characters for your new password.');
      return;
    }
    if (next !== confirm) {
      toast('error', 'The new passwords do not match.');
      return;
    }
    setSavingPw(true);
    try {
      await api.changePassword(current, next);
      setCurrent('');
      setNext('');
      setConfirm('');
      toast('success', 'Your password was changed.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not change your password.');
    } finally {
      setSavingPw(false);
    }
  };

  // --- 2FA enrolment -------------------------------------------------------
  const startSetup = async () => {
    setBusy(true);
    try {
      setSetup(await api.mfa.setup());
      setEnrolCode('');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not start setup.');
    } finally {
      setBusy(false);
    }
  };

  const confirmSetup = async () => {
    setBusy(true);
    try {
      const { recovery_codes } = await api.mfa.confirm(enrolCode.trim());
      setCodes(recovery_codes);
      setSetup(null);
      setEnrolCode('');
      await loadStatus();
      toast('success', 'Authenticator is on.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'That code did not match. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    setBusy(true);
    try {
      const { recovery_codes } = await api.mfa.regenerate(manageCode.trim());
      setCodes(recovery_codes);
      setManageCode('');
      await loadStatus();
      toast('success', 'Fresh recovery codes issued.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'That code did not match.');
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    try {
      await api.mfa.disable(manageCode.trim());
      setManageCode('');
      setCodes(null);
      await loadStatus();
      toast('success', 'Authenticator removed.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'That code did not match.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-lg font-bold font-mono uppercase tracking-wide">Password &amp; 2FA</h2>
        <p className="text-sm text-[#141414]/60 mt-1">
          Change your password and manage the authenticator that protects your money.
        </p>
      </div>

      {/* ---- Change password --------------------------------------------- */}
      <Panel title="Change password">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-center gap-1.5">
          <Lock className="h-3.5 w-3.5" />
          You'll need your current password to set a new one.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Current password">
            <input type="password" autoComplete="current-password" className={inputCls}
              value={current} onChange={(e) => setCurrent(e.target.value)} />
          </Field>
          <Field label="New password">
            <input type="password" autoComplete="new-password" className={inputCls}
              value={next} onChange={(e) => setNext(e.target.value)} />
          </Field>
          <Field label="Confirm new password">
            <input type="password" autoComplete="new-password" className={inputCls}
              value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <Btn variant="green" onClick={changePassword}
            disabled={savingPw || !current || !next || !confirm}>
            {savingPw ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            Change password
          </Btn>
        </div>
      </Panel>

      {/* ---- Authenticator ----------------------------------------------- */}
      <Panel title="Authenticator app (2FA)">
        {!status ? (
          <div className="flex items-center gap-2 text-sm text-[#141414]/50">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : (
          <>
            <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-start gap-1.5">
              <Smartphone className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>{status.why}</span>
            </p>

            {/* Codes just issued — show once, then dismiss back to status. */}
            {codes && <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />}

            {!codes && status.enrolled && (
              <div className="space-y-4">
                <div className="flex items-center gap-2 border border-[#228B22]/40 bg-[#F0F7F0] px-3 py-2 text-sm">
                  <ShieldCheck className="h-4 w-4 text-[#228B22]" />
                  <span className="font-bold">Authenticator is on.</span>
                  <span className="text-[#141414]/55">
                    {status.recovery_codes_left} recovery code{status.recovery_codes_left === 1 ? '' : 's'} left.
                  </span>
                </div>

                <div className="border border-[#141414]/15 p-3">
                  <p className="text-xs text-[#141414]/60 mb-2">
                    Enter a current 6-digit code (or a recovery code) to manage 2FA:
                  </p>
                  <input
                    className={`${inputCls} w-40 font-mono`}
                    value={manageCode}
                    onChange={(e) => setManageCode(e.target.value)}
                    placeholder="123456"
                    inputMode="numeric"
                  />
                  <div className="mt-3 flex gap-2">
                    <Btn onClick={regenerate} disabled={busy || !manageCode.trim()}>
                      New recovery codes
                    </Btn>
                    <Btn variant="danger" onClick={disable} disabled={busy || !manageCode.trim()}>
                      Remove authenticator
                    </Btn>
                  </div>
                </div>
              </div>
            )}

            {!codes && !status.enrolled && (
              <>
                {!setup ? (
                  <Btn variant="green" onClick={startSetup} disabled={busy}>
                    {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Smartphone className="h-3.5 w-3.5" />}
                    Set up authenticator
                  </Btn>
                ) : (
                  <div className="border border-[#141414]/15 p-3">
                    <p className="text-xs text-[#141414]/60 mb-3">
                      Scan this with Google Authenticator (or any TOTP app), then enter the 6-digit
                      code to confirm.
                    </p>
                    <div className="flex flex-col sm:flex-row gap-4">
                      <img src={setup.qr} alt="Authenticator QR code"
                        className="h-40 w-40 border border-[#141414]/15 bg-white" />
                      <div className="flex-1">
                        <p className="text-[11px] text-[#141414]/50">Can't scan? Enter this key:</p>
                        <code className="mt-1 block break-all border border-[#141414]/15 bg-[#f4f4f2] p-2 font-mono text-xs">
                          {setup.secret}
                        </code>
                        <Field label="6-digit code" className="mt-3">
                          <input
                            className={`${inputCls} w-40 font-mono`}
                            value={enrolCode}
                            onChange={(e) => setEnrolCode(e.target.value)}
                            placeholder="123456"
                            inputMode="numeric"
                          />
                        </Field>
                        <div className="mt-3 flex gap-2">
                          <Btn variant="green" onClick={confirmSetup} disabled={busy || !enrolCode.trim()}>
                            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                            Confirm
                          </Btn>
                          <Btn onClick={() => setSetup(null)} disabled={busy}>Cancel</Btn>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </Panel>
    </div>
  );
}
