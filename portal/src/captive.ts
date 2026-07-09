/**
 * MikroTik hotspot integration.
 *
 * The router's login page redirects here with device/router context:
 *   http://portal.example/?mac=$(mac)&ip=$(ip)&router=<id>
 *     &login=$(link-login-only)&orig=$(link-orig)
 * (configured once in the router's hotspot login.html template).
 *
 * Params are persisted to sessionStorage so they survive the payment flow's
 * navigations and page refreshes.
 */

const KEY = 'wifios_captive';

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
  const fromQuery: CaptiveParams = {
    mac: qs.get('mac') ?? '',
    ip: qs.get('ip') ?? '',
    routerId: qs.get('router') ? Number(qs.get('router')) : null,
    loginUrl: qs.get('login') ?? '',
    origUrl: qs.get('orig') ?? '',
  };
  if (fromQuery.mac || fromQuery.loginUrl) {
    sessionStorage.setItem(KEY, JSON.stringify(fromQuery));
    return fromQuery;
  }
  const saved = sessionStorage.getItem(KEY);
  return saved ? (JSON.parse(saved) as CaptiveParams) : fromQuery;
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
