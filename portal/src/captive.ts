/**
 * MikroTik hotspot integration.
 *
 * The router's login page redirects here with device/router context:
 *   http://portal.example/?mac=$(mac)&ip=$(ip)&router=<id>
 *     &login=$(link-login-only)&orig=$(link-orig)
 * (configured once in the router's hotspot login.html template).
 *
 * NO BROWSER STORAGE (a system rule). The URL *is* the state: the router already
 * puts these params there, and we simply never strip them — so they survive a
 * refresh for free. Nothing is cached, so a deploy mid-payment cannot leave a
 * customer holding a stale object that crashes the page.
 */

export interface CaptiveParams {
  mac: string;
  ip: string;
  routerId: number | null;
  /** $(link-login-only) — POST credentials here to authenticate the device */
  loginUrl: string;
  /** $(link-orig) — where the customer was originally headed */
  origUrl: string;
}

export function getCaptiveParams(): CaptiveParams {
  const qs = new URLSearchParams(window.location.search);
  return {
    mac: qs.get('mac') ?? '',
    ip: qs.get('ip') ?? '',
    routerId: qs.get('router') ? Number(qs.get('router')) : null,
    loginUrl: qs.get('login') ?? '',
    origUrl: qs.get('orig') ?? '',
  };
}

/** The in-flight payment, kept in the URL so a refresh resumes polling. */
export interface PendingPayment {
  txId: string;
  planName: string;
  startedAt: number;
}

export function readPending(): PendingPayment | null {
  const qs = new URLSearchParams(window.location.search);
  const txId = qs.get('tx');
  if (!txId) return null;
  const startedAt = Number(qs.get('t') ?? 0);
  if (!startedAt) return null;
  return { txId, planName: qs.get('plan') ?? '', startedAt };
}

/** Reflect the payment into the URL without adding a history entry, so Back
 * doesn't walk the customer back into a half-finished payment. */
export function writePending(p: PendingPayment | null) {
  const url = new URL(window.location.href);
  if (p) {
    url.searchParams.set('tx', p.txId);
    url.searchParams.set('plan', p.planName);
    url.searchParams.set('t', String(p.startedAt));
  } else {
    url.searchParams.delete('tx');
    url.searchParams.delete('plan');
    url.searchParams.delete('t');
  }
  window.history.replaceState({}, '', url.toString());
}

/** Authenticate this device on the router by form-POSTing to link-login-only. */
export function submitRouterLogin(loginUrl: string, username: string, password: string, dst: string) {
  const form = document.createElement('form');
  form.method = 'POST';
  form.action = loginUrl;
  const add = (name: string, value: string) => {
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = name;
    input.value = value;
    form.appendChild(input);
  };
  add('username', username);
  add('password', password);
  if (dst) add('dst', dst);
  document.body.appendChild(form);
  form.submit();
}
