/**
 * Auth — with NO BROWSER STORAGE. This is a hard rule for this system.
 *
 * We never hold a token. Signing in makes the server set httpOnly cookies; the
 * browser attaches them to every request from then on. JavaScript cannot read
 * them (so XSS cannot steal them), and — the reason this matters day to day —
 * there is nothing cached in the client that can go stale after a deploy. No user
 * is ever told to "clear your cache".
 *
 * "Am I signed in?" is therefore a question only the SERVER can answer: we ask it
 * (GET /me/) rather than inspecting storage.
 */

const BASE = (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE_URL ?? '';

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown
  ) {
    super(
      typeof body === 'object' && body && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `HTTP ${status}`
    );
  }
}

/** Send cookies on every call — this is what replaces the Authorization header. */
const withCookies: RequestInit = { credentials: 'include' };

/**
 * CSRF. Putting the token in a cookie reintroduces CSRF (a Bearer header never
 * could be forged; a cookie is sent automatically). The server hands us a CSRF
 * token in a READABLE cookie and requires it echoed back in a header on writes —
 * the double-submit pattern. An attacker's site cannot read our cookie, so it
 * cannot forge the header.
 *
 * Note this is NOT app state in the browser: the server owns it, we only echo it.
 */
const readCsrfToken = (): string =>
  document.cookie
    .split('; ')
    .find((c) => c.startsWith('csrftoken='))
    ?.split('=')[1] ?? '';

const UNSAFE = /^(POST|PUT|PATCH|DELETE)$/i;

const csrfHeader = (method?: string): Record<string, string> =>
  UNSAFE.test(method ?? 'GET') ? { 'X-CSRFToken': readCsrfToken() } : {};

export async function login(phone: string, password: string): Promise<void> {
  const resp = await fetch(`${BASE}/api/v1/auth/login/`, {
    ...withCookies,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, password }),
  });
  if (!resp.ok) {
    throw new Error(
      resp.status === 401 ? 'Wrong phone number or password.' : `Sign-in failed (${resp.status})`
    );
  }
  // Nothing to store. The cookies are already set.
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/api/v1/auth/logout/`, { ...withCookies, method: 'POST' }).catch(
    () => {}
  );
}

async function tryRefresh(): Promise<boolean> {
  const resp = await fetch(`${BASE}/api/v1/auth/refresh/`, {
    ...withCookies,
    method: 'POST',
  });
  return resp.ok;
}

export async function request<T>(
  path: string,
  init?: RequestInit,
  retried = false
): Promise<T> {
  const resp = await fetch(`${BASE}/api/v1${path}`, {
    ...withCookies,
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...csrfHeader(init?.method),
      ...init?.headers,
    },
  });

  // Access cookie expired -> renew silently and replay once.
  if (resp.status === 401 && !retried && (await tryRefresh())) {
    return request<T>(path, init, true);
  }
  if (!resp.ok) throw new ApiError(resp.status, await resp.json().catch(() => null));
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
