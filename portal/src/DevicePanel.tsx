import { useCallback, useEffect, useState } from 'react';
import {
  Laptop,
  Loader2,
  Plus,
  RefreshCw,
  Smartphone,
  Trash2,
  Tv,
  Wifi,
  XCircle,
} from 'lucide-react';
import {
  addDevice,
  listDevices,
  removeDevice,
  type DeviceRow,
  type DeviceState,
  type SessionInfo,
} from './api/client';
import { formatExpiry } from './format';

/**
 * "Add your other devices" — the tap-to-approve surface a customer sees after paying.
 *
 * They paid on one phone; the plan covers several devices. This lets them put their
 * laptop or TV on the SAME paid session — no second payment, no typing credentials on the
 * TV — by tapping a device the router already sees on the Wi-Fi. Gated entirely by the
 * session's device_token, which only this (paying) device holds.
 */
export default function DevicePanel({ session }: { session: SessionInfo }) {
  const token = session.device_token;
  const [state, setState] = useState<DeviceState | null>(null);
  const [scanning, setScanning] = useState(false);
  const [busyMac, setBusyMac] = useState('');
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async () => {
    if (!token) return;
    setScanning(true);
    setError('');
    try {
      setState(await listDevices(token));
    } catch {
      setError('Could not check your devices. Try again in a moment.');
    } finally {
      setScanning(false);
    }
  }, [token]);

  useEffect(() => {
    // Load the current list once (without the network scan feeling), quietly.
    if (token) listDevices(token).then(setState).catch(() => {});
  }, [token]);

  if (!token || !session.device_allowance) return null;
  const { general, tv } = session.device_allowance;
  const total = general + tv;
  // Only worth showing when the plan actually allows more than the paying device.
  if (total <= 1) return null;

  const add = async (mac: string, kind: DeviceRow['kind'], hostname: string) => {
    setBusyMac(mac);
    setError('');
    try {
      setState(await addDevice(token, mac, kind, hostname));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not add that device.');
    } finally {
      setBusyMac('');
    }
  };

  const drop = async (mac: string) => {
    setBusyMac(mac);
    setError('');
    try {
      setState(await removeDevice(token, mac));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove that device.');
    } finally {
      setBusyMac('');
    }
  };

  const usedGeneral = state?.used.general ?? 1;
  const usedTv = state?.used.tv ?? 0;
  const generalFull = usedGeneral >= general;
  const tvFree = tv > usedTv;

  return (
    <div className="w-full mt-4 border-t border-[#141414]/15 pt-4 text-left">
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-sm">Your devices</h3>
        <span className="text-[11px] text-[#141414]/50 tabular-nums">
          {usedGeneral}/{general} device{general === 1 ? '' : 's'}
          {tv > 0 && ` · ${usedTv}/${tv} TV`}
        </span>
      </div>
      <p className="text-[11px] text-[#141414]/50 mt-0.5 leading-relaxed">
        This plan covers {general} device{general === 1 ? '' : 's'}
        {tv > 0 && ` and ${tv} TV`}. Put your other devices online here — no need to pay again.
      </p>

      {/* current devices */}
      <div className="mt-3 space-y-1.5">
        {(state?.devices ?? []).map((d) => (
          <div
            key={d.mac_address}
            className="flex items-center gap-2.5 border border-[#141414]/15 bg-[#f8f8f6] px-2.5 py-2"
          >
            <KindIcon kind={d.kind} />
            <div className="min-w-0 flex-1">
              <div className="text-xs font-bold truncate">{d.hostname || deviceLabel(d.kind)}</div>
              <div className="text-[10px] font-mono text-[#141414]/40 truncate">{d.mac_address}</div>
            </div>
            {d.is_paying_device ? (
              <span className="text-[10px] font-bold uppercase text-[#228B22]">You paid</span>
            ) : (
              <button
                onClick={() => drop(d.mac_address)}
                disabled={busyMac === d.mac_address}
                className="p-1 text-[#B22222] active:opacity-60 disabled:opacity-40"
                aria-label="Remove device"
              >
                {busyMac === d.mac_address ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
              </button>
            )}
          </div>
        ))}
      </div>

      {/* find + add */}
      {!open ? (
        <button
          onClick={() => {
            setOpen(true);
            refresh();
          }}
          className="mt-3 w-full border border-[#141414] py-2.5 text-xs font-bold flex items-center justify-center gap-2 active:opacity-70"
        >
          <Plus className="h-4 w-4" /> Add another device
        </button>
      ) : (
        <div className="mt-3">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[11px] text-[#141414]/60">
              Connect the device to the Wi-Fi, then pick it below.
            </p>
            <button
              onClick={refresh}
              disabled={scanning}
              className="text-[#141414]/60 active:opacity-60 disabled:opacity-40 flex items-center gap-1 text-[11px] font-bold"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${scanning ? 'animate-spin' : ''}`} /> Rescan
            </button>
          </div>

          {scanning && !state?.available ? (
            <div className="flex items-center gap-2 text-xs text-[#141414]/50 py-3 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> Looking for devices…
            </div>
          ) : (state?.available ?? []).length === 0 ? (
            <div className="text-center text-[11px] text-[#141414]/50 border border-dashed border-[#141414]/25 py-4 px-3">
              <Wifi className="h-5 w-5 mx-auto mb-1 text-[#141414]/30" />
              No new devices found. Make sure the device is connected to the Wi-Fi, then Rescan.
            </div>
          ) : (
            <div className="space-y-1.5">
              {(state?.available ?? []).map((h) => (
                <div
                  key={h.mac_address}
                  className="flex items-center gap-2.5 border border-[#141414]/15 px-2.5 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-bold truncate">{h.hostname || 'Unknown device'}</div>
                    <div className="text-[10px] font-mono text-[#141414]/40 truncate">{h.mac_address}</div>
                  </div>
                  {/* Add as a normal device, or as the TV if a TV slot is free. */}
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => add(h.mac_address, 'laptop', h.hostname)}
                      disabled={generalFull || busyMac === h.mac_address}
                      className="border border-[#141414] px-2 py-1 text-[11px] font-bold active:opacity-70 disabled:opacity-30 flex items-center gap-1"
                    >
                      {busyMac === h.mac_address ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plus className="h-3.5 w-3.5" />
                      )}
                      Add
                    </button>
                    {tvFree && (
                      <button
                        onClick={() => add(h.mac_address, 'tv', h.hostname)}
                        disabled={busyMac === h.mac_address}
                        className="border border-[#141414] px-2 py-1 text-[11px] font-bold active:opacity-70 disabled:opacity-30 flex items-center gap-1"
                      >
                        <Tv className="h-3.5 w-3.5" /> TV
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {error && <p className="mt-2 text-[11px] text-[#B22222]">{error}</p>}
    </div>
  );
}

/**
 * The full-screen "manage my devices" view a customer lands on from the recovery URL
 * (?manage=<token>) or the SMS link — so closing the original tab no longer strands them.
 * Validates the token, then shows their live plan + the same add/remove panel.
 */
export function ManageScreen({ token, onDone }: { token: string; onDone: () => void }) {
  const [state, setState] = useState<DeviceState | null>(null);
  const [status, setStatus] = useState<'loading' | 'ok' | 'gone'>('loading');

  useEffect(() => {
    listDevices(token)
      .then((s) => {
        setState(s);
        setStatus('ok');
      })
      .catch(() => setStatus('gone'));
  }, [token]);

  if (status === 'loading') {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-sm text-[#141414]/50">
        <Loader2 className="h-5 w-5 animate-spin" /> Loading your plan…
      </div>
    );
  }

  if (status === 'gone' || !state) {
    return (
      <div className="flex flex-col items-center text-center py-8 gap-3">
        <XCircle className="h-10 w-10 text-[#B26B00]" />
        <h2 className="font-bold text-lg">This link has expired</h2>
        <p className="text-sm text-[#141414]/70 leading-relaxed">
          Your plan may have ended, or the link is no longer valid.
        </p>
        <button
          onClick={onDone}
          className="mt-1 w-full bg-[#141414] text-[#E4E3E0] font-bold py-3 active:opacity-80"
        >
          See plans
        </button>
      </div>
    );
  }

  // Construct the SessionInfo the panel needs from the recovered state.
  const session: SessionInfo = {
    hotspot_username: state.session?.username ?? '',
    hotspot_password: '',
    expires_at: state.session?.expires_at ?? '',
    device_token: token,
    device_allowance: state.allowance,
  };

  return (
    <div className="flex flex-col items-center text-center py-2 gap-2">
      <Wifi className="h-10 w-10 text-[#228B22]" />
      <h2 className="font-bold text-lg">Your devices</h2>
      {session.expires_at && (
        <p className="text-sm text-[#141414]/70">
          Online until <b>{formatExpiry(session.expires_at)}</b>
        </p>
      )}
      <DevicePanel session={session} />
      <button
        onClick={onDone}
        className="mt-3 w-full border border-[#141414] text-[#141414] font-bold py-2.5 text-sm active:opacity-70"
      >
        Done
      </button>
    </div>
  );
}

function KindIcon({ kind }: { kind: DeviceRow['kind'] }) {
  const cls = 'h-4 w-4 text-[#141414]/60 shrink-0';
  if (kind === 'tv') return <Tv className={cls} />;
  if (kind === 'laptop') return <Laptop className={cls} />;
  return <Smartphone className={cls} />;
}

function deviceLabel(kind: DeviceRow['kind']): string {
  return { phone: 'Phone', laptop: 'Laptop', tv: 'TV', other: 'Device' }[kind];
}
