/**
 * ISP console API client.
 *
 * NO BROWSER STORAGE — a hard rule for this system. We hold no token and no
 * acting-tenant: signing in makes the SERVER set httpOnly cookies, and the
 * browser attaches them from then on. JavaScript cannot read them (XSS cannot
 * steal them), and nothing cached in the client can go stale after a deploy, so
 * no ISP is ever told to "clear your cache".
 *
 * "Am I signed in?" and "which ISP am I acting for?" are questions only the
 * server can answer now — we ask it (GET /me/) instead of reading storage. That
 * is what makes a stale/expired session impossible to get wedged on.
 *
 * Calls go through the Vite dev proxy (/api -> Django) in dev, so the cookies are
 * same-origin; VITE_API_BASE_URL overrides in production builds.
 */

const BASE = (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE_URL ?? '';

// ---- auth -------------------------------------------------------------

/** Send cookies on every call — this replaces the Authorization header. */
const withCookies: RequestInit = { credentials: 'include' };

/**
 * CSRF. Moving the token into a cookie reintroduces CSRF (a Bearer header could
 * never be forged; a cookie is attached automatically). The server issues a CSRF
 * token in a READABLE cookie and requires it echoed in a header on writes — the
 * double-submit pattern. An attacker's site cannot read our cookie, so it cannot
 * forge the header. This is not app state we own; the server does.
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
      resp.status === 401 ? 'Wrong phone/email or password.' : `Login failed (HTTP ${resp.status})`
    );
  }
  // Nothing to store — the cookies are already set.
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/api/v1/auth/logout/`, { ...withCookies, method: 'POST' }).catch(() => {});
}

/**
 * One-click entry to the read-only demo. Succeeds ONLY on a demo host — the server decides,
 * so we can try it unconditionally when there's no session and fall back to the login screen
 * on any normal host. Returns true if a demo session was established.
 */
export async function demoLogin(): Promise<boolean> {
  try {
    const resp = await fetch(`${BASE}/api/v1/auth/demo/`, { ...withCookies, method: 'POST' });
    return resp.ok;
  } catch {
    return false;
  }
}

// Single-flight: when the access cookie expires, a dashboard fires several requests
// at once and they ALL get 401. Without this, each one would POST its own refresh —
// a thundering herd, and with a rotating refresh token, a race that logs you out.
// Instead every caller awaits the SAME in-flight refresh.
let refreshInFlight: Promise<boolean> | null = null;
async function tryRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${BASE}/api/v1/auth/refresh/`, { ...withCookies, method: 'POST' })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

/**
 * Keep the session alive so returning from inactivity never dumps you at the login
 * screen. Two triggers:
 *   - the tab becoming visible again (you came back to it), and
 *   - a heartbeat while it stays open,
 * both well inside the access-token lifetime. Renewing PROACTIVELY means data calls
 * never hit an expired token in the first place. Returns a cleanup function.
 */
export function keepSessionFresh(): () => void {
  const renewIfVisible = () => {
    if (document.visibilityState === 'visible') void tryRefresh();
  };
  document.addEventListener('visibilitychange', renewIfVisible);
  window.addEventListener('focus', renewIfVisible);
  const heartbeat = window.setInterval(renewIfVisible, 30 * 60 * 1000); // every 30 min
  return () => {
    document.removeEventListener('visibilitychange', renewIfVisible);
    window.removeEventListener('focus', renewIfVisible);
    window.clearInterval(heartbeat);
  };
}

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

/**
 * A 401 that a silent refresh could NOT recover — the session is genuinely over.
 * Distinct from ApiError so views can stay quiet (the app is returning you to sign-in)
 * instead of each one showing a misleading "could not load — is the API running?".
 */
export class SessionExpiredError extends ApiError {
  constructor(body: unknown) {
    super(401, body);
    this.name = 'SessionExpiredError';
  }
}

// The app registers a single handler; we call it ONCE when a request finds the session
// truly gone, so the whole app returns to the sign-in screen centrally rather than every
// data call surfacing its own error.
let onSessionExpired: (() => void) | null = null;
export function setOnSessionExpired(cb: (() => void) | null): void {
  onSessionExpired = cb;
}

// ---- connection resilience -----------------------------------------------------------
// A short API blip (a deploy rolling the container, a momentary overload) used to surface
// as "could not load — is the API running?" in every view, which reads as the backend being
// broken and forces a manual refresh. Instead: GETs retry briefly, a "Reconnecting…" state
// is published for a subtle banner, and the moment the API answers again every subscribed
// view re-fetches on its own — no refresh, no scary error. This matters at tenant scale.

export type ConnState = 'ok' | 'reconnecting';
let onConnectionChange: ((s: ConnState) => void) | null = null;
export function setOnConnectionChange(cb: ((s: ConnState) => void) | null): void {
  onConnectionChange = cb;
}

const reconnectSubs = new Set<() => void>();
/** Subscribe to "the API just came back" so a view can silently reload. Returns an unsub. */
export function onReconnect(cb: () => void): () => void {
  reconnectSubs.add(cb);
  return () => reconnectSubs.delete(cb);
}

const TRANSIENT_STATUS = new Set([502, 503, 504]);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let connectionDown = false;
let probeTimer: number | null = null;
function markConnection(down: boolean): void {
  if (down === connectionDown) return;
  connectionDown = down;
  onConnectionChange?.(down ? 'reconnecting' : 'ok');
  if (down) {
    // Probe a cheap unauthenticated endpoint until the API answers, then recover fast.
    if (probeTimer === null) {
      probeTimer = window.setInterval(() => {
        // Hit an API path (not the static server, which would 200 even when the API is down).
        fetch(`${BASE}/api/v1/health/`, { ...withCookies })
          .then((r) => { if (r.ok) markConnection(false); })
          .catch(() => { /* still down */ });
      }, 3000);
    }
  } else {
    if (probeTimer !== null) { window.clearInterval(probeTimer); probeTimer = null; }
    reconnectSubs.forEach((cb) => cb()); // recovered → every subscribed view re-fetches
  }
}

async function request<T>(path: string, init?: RequestInit, retried = false): Promise<T> {
  const isGet = !init?.method || init.method.toUpperCase() === 'GET';
  for (let attempt = 0; ; attempt++) {
    let resp: Response;
    try {
      resp = await fetch(`${BASE}/api/v1${path}`, {
        ...withCookies,
        ...init,
        headers: {
          'Content-Type': 'application/json',
          ...csrfHeader(init?.method),
          ...init?.headers,
        },
      });
    } catch (err) {
      // An intentional cancel (e.g. the map search aborting a superseded keystroke) is NOT a
      // connectivity problem — rethrow it quietly so it never trips the "Reconnecting…" banner
      // or the retry loop. The caller recognises it by err.name === 'AbortError'.
      if ((err as { name?: string })?.name === 'AbortError' || init?.signal?.aborted) throw err;
      // Network-level failure — the server is unreachable (mid-deploy, blip). Retry GETs a
      // few times so a brief outage is invisible; writes fail fast so we never double-submit.
      if (isGet && attempt < 4) {
        markConnection(true);
        await sleep(400 * 2 ** attempt); // 0.4s, 0.8s, 1.6s, 3.2s
        continue;
      }
      markConnection(true);
      throw new ApiError(0, { detail: 'Could not reach the server. Reconnecting…' });
    }
    // A gateway error means "not ready yet" (e.g. a container just restarting) — retry GETs.
    if (isGet && TRANSIENT_STATUS.has(resp.status) && attempt < 4) {
      markConnection(true);
      await sleep(400 * 2 ** attempt);
      continue;
    }
    markConnection(false); // we reached the server
    // Access cookie expired: renew silently and replay once. If the refresh ALSO fails the
    // session is genuinely over — tell the app (which returns to sign-in) and throw a quiet,
    // typed error, instead of a generic one every view would read as "the API is down".
    if (resp.status === 401 && !retried) {
      if (await tryRefresh()) return request<T>(path, init, true);
      const expiredBody = await resp.json().catch(() => null);
      onSessionExpired?.();
      throw new SessionExpiredError(expiredBody);
    }
    const body = resp.status === 204 ? null : await resp.json().catch(() => null);
    if (!resp.ok) throw new ApiError(resp.status, body);
    return body as T;
  }
}

// ---- types (mirroring the DRF serializers) ------------------------------

export interface ApiPlan {
  id: number;
  name: string;
  plan_type: 'hotspot' | 'pppoe';
  price: string;
  duration: string;
  duration_seconds: number;
  data_cap_mb: number | null;
  download_kbps: number;
  upload_kbps: number;
  shared_users: number;
  mikrotik_profile: string;
  description: string;
  is_active: boolean;
  sort_order: number;
}

/** One row from the unified payments search (hotspot + PPPoE). */
export interface PaymentSearchResult {
  kind: 'hotspot' | 'pppoe';
  phone: string;
  code: string;
  /** PPPoE account number the customer typed (empty for hotspot). */
  reference: string;
  amount: string;
  status: string;
  date: string;
}

export interface ApiTransaction {
  id: number;
  public_id: string;
  phone: string;
  plan_name: string;
  amount: string;
  status: 'pending' | 'success' | 'reconciled' | 'failed' | 'timeout';
  mpesa_receipt: string;
  checkout_request_id: string | null;
  result_code: number | null;
  result_desc: string;
  created_at: string;
  callback_received_at: string | null;
  /** Whether the paid customer actually got online. `failed` (or a paid tx with no
   *  active session) is the "they paid but never connected" case the reconnect flow
   *  exists for. */
  provisioning: 'pending' | 'connecting' | 'active' | 'failed';
  session_expires_at: string | null;
}

export interface ApiCampaign {
  id: number;
  name: string;
  channel: 'sms' | 'whatsapp' | 'email';
  audience: 'all' | 'active' | 'expired';
  subject: string;
  body: string;
  status: 'queued' | 'sending' | 'done';
  total_recipients: number;
  sent_count: number;
  failed_count: number;
  created_at: string;
}

export interface ApiMessage {
  id: number;
  campaign: number | null;
  to_phone: string;
  to_email: string;
  channel: 'sms' | 'whatsapp' | 'email';
  subject: string;
  body: string;
  status: 'queued' | 'sent' | 'failed';
  provider_ref: string;
  error: string;
  sent_at: string | null;
  created_at: string;
}

export interface ApiSessionDevice {
  mac_address: string;
  hostname: string;
  kind: 'phone' | 'laptop' | 'tv' | 'other';
  is_paying_device: boolean;
}

export interface ApiSession {
  id: number;
  phone: string;
  hotspot_username: string;
  plan_name: string;
  router_name: string;
  status: 'pending' | 'active' | 'expired' | 'suspended' | 'failed';
  starts_at: string;
  expires_at: string;
  mac_address: string;
  ip_address: string | null;
  data_used_mb: number;
  provision_error: string;
  devices: ApiSessionDevice[];
  device_allowance: { general: number; tv: number };
}

/** A live connection normalised across service types (hotspot, PPPoE, later static/Ruijie),
 *  as shown on the Active Users page. Hotspot rows carry devices/expiry; PPPoE rows carry
 *  uptime — the shared core is always present. */
export type LiveServiceType = 'hotspot' | 'pppoe';
export interface LiveConnection {
  service_type: LiveServiceType;
  id: number;
  identifier: string; // hotspot_username or PPPoE account_number
  name: string; // subscriber phone or client full name
  plan_name: string;
  router_name: string;
  status: string;
  since: string | null;
  uptime: string; // router-reported (PPPoE); '' for hotspot
  ip: string | null;
  mac_address: string;
  expires_at: string | null;
  provision_error: string;
  devices: ApiSessionDevice[];
  device_allowance: { general: number; tv: number } | null;
}
export interface LiveConnectionsResponse {
  counts: Record<string, number>;
  results: LiveConnection[];
}

export interface ApiVoucher {
  id: number;
  code: string;
  plan: number;
  plan_name: string;
  batch_id: string;
  status: 'unused' | 'redeemed' | 'expired' | 'void';
  redeemed_at: string | null;
  printed: boolean;
  created_at: string;
}

export interface ApiRouter {
  id: number;
  name: string;
  gps_lat: string | null;
  gps_lng: string | null;
  management_host: string;
  api_port: number;
  username: string;
  use_tls: boolean;
  verify_tls: boolean;
  provisioning_backend: 'mikrotik_rest' | 'dummy';
  status: 'online' | 'offline' | 'pending' | 'unknown';
  last_seen_at: string | null;
  last_sync_at: string | null;
  enrolled_at: string | null;
  routeros_version: string;
  board_name: string;
  serial_number: string;
  architecture: string;
  identity_updated_at: string | null;
  is_enrolled: boolean;
  is_reachable: boolean;
  needs_onboarding: boolean;
  is_active: boolean;
  /** WAN uplink capacity in Mbps — powers the oversubscription check. */
  uplink_mbps: number | null;
}

export interface RouterInterfaceRate {
  name: string;
  rx_mbps: number;
  tx_mbps: number;
}

export interface RouterDiagnostics {
  reachable: boolean;
  cpu_load: number | null;
  mem_used_pct: number | null;
  uptime: string;
  mss_clamp_present: boolean | null;
  simple_queue_count: number | null;
  pppoe_active_count: number | null;
  top_interfaces: RouterInterfaceRate[];
  notes: string[];
  active_clients: number;
  sold_download_mbps: number;
  uplink_mbps: number | null;
  oversubscription_ratio: number | null;
}

export interface RouterHealthTrend {
  samples: { at: string; cpu_load: number | null; mem_used_pct: number | null; active_users: number | null }[];
  peak_cpu_24h: number | null;
  peak_mem_24h: number | null;
  peak_users_24h: number | null;
}

export interface DeviceInfo {
  routeros_version: string;
  board_name: string;
  serial_number: string;
  architecture: string;
  identity_name: string;
  uptime: string;
  cpu_load: number | null;
  free_memory: number | null;
  total_memory: number | null;
  active_users: number | null;
}

export interface ApiTicket {
  id: number;
  subject: string;
  description: string;
  /** Where the job is — lets an assigned technician navigate to it. */
  gps_lat: string | null;
  gps_lng: string | null;
  subscriber: number | null;
  subscriber_phone: string;
  status: 'open' | 'in_progress' | 'resolved' | 'closed';
  priority: 'low' | 'normal' | 'high' | 'urgent';
  assigned_to: number | null;
  assigned_to_name: string;
  created_at: string;
  resolved_at: string | null;
}
export interface TicketAssignee {
  id: number;
  name: string;
  phone: string;
}

export interface ApiLead {
  id: number;
  name: string;
  phone: string;
  location: string;
  gps_lat: string | null;
  gps_lng: string | null;
  source: string;
  status: 'new' | 'contacted' | 'converted' | 'lost';
  notes: string;
  created_at: string;
}

/** The auto "WIFI.OS platform fees" line on the Expenses page. */
export interface PlatformFees {
  month: string;
  total: string;
  lines: { key: string; label: string; amount: string }[];
}

export interface ApiExpense {
  id: number;
  date: string;
  category: 'bandwidth' | 'power' | 'rent' | 'salaries' | 'equipment' | 'transport' | 'other';
  description: string;
  amount: string;
  router: number | null;
  router_name: string;
  created_at: string;
}

export interface ApiEquipment {
  id: number;
  name: string;
  equipment_type: 'router' | 'antenna' | 'switch' | 'cpe' | 'cable' | 'power' | 'other';
  serial_number: string;
  status: 'in_store' | 'deployed' | 'faulty' | 'retired';
  router: number | null;
  router_name: string;
  cost: string | null;
  notes: string;
  created_at: string;
}

export type Role =
  | 'platform_owner'
  | 'platform_support'
  /** ISP side: the owner, plus the delegated workforce roles (see backend accounts/rbac.py).
   *  Each maps to a concrete job; reach is defined by the capability map, not by branching. */
  | 'tenant_owner'
  | 'tenant_admin'
  | 'tenant_care'
  | 'tenant_technician';

/** A capability string the server grants a role (resource.action). The console hides what the
 *  API would refuse anyway; the server stays authoritative. Kept as a widened string so a new
 *  backend capability never breaks the build. */
export type Capability = string;

/** How each role presents in the UI: a short label + an accent colour for the badge. */
export const ROLE_META: Record<Role, { label: string; color: string }> = {
  platform_owner: { label: 'Platform Owner', color: '#6D28D9' },
  platform_support: { label: 'Platform Support', color: '#6B7280' },
  tenant_owner: { label: 'Owner', color: '#6D28D9' },
  tenant_admin: { label: 'Administrator', color: '#2563EB' },
  tenant_care: { label: 'Customer Care', color: '#0F766E' },
  tenant_technician: { label: 'Technician', color: '#B26B00' },
};

export interface StaffMember {
  id: number;
  name: string;
  phone: string;
  email: string;
  role: Role;
  is_active: boolean;
  must_change_password: boolean;
  last_login: string | null;
  date_joined: string;
}

/** Access Control (owner-only): the editable role→capability model. */
export interface CapabilityCatalogEntry {
  group: string;
  capability: Capability;
  label: string;
}
export interface RoleState {
  role: Role;
  label: string;
  capabilities: Capability[];
  default_capabilities: Capability[];
  /** true once the owner has customised this role away from the recommended defaults. */
  is_custom: boolean;
}
export interface AccessControlData {
  catalog: CapabilityCatalogEntry[];
  roles: RoleState[];
  /** Powers that can never be granted to a delegated role (money.manage, rbac.manage). */
  non_delegable: Capability[];
}

export interface GoLiveBlocker {
  key: string;
  label: string;
  detail: string;
  /** Already satisfied. */
  done: boolean;
  /** True if the ISP can do something about it themselves, right now. */
  actionable: boolean;
}

export interface Settlement {
  method: 'mpesa' | 'paybill' | 'bank' | null;
  destination: string | null;
  /** Raw registered destination, so the settlement form can pre-fill it. */
  payout_phone: string;
  paybill: string;
  paybill_account: string;
  bank_name: string;
  bank_account_number: string;
  bank_account_name: string;
  has_account: boolean;
  /** The first payout's code has been read back — payouts are unlocked for good. */
  confirmed: boolean;
  confirmed_at: string | null;
  can_transact: boolean;
  /** Changing an existing payout account takes a code emailed to the owner's login
   *  address — the one inbox an attacker inside the console cannot reach. */
  change_requires_code: boolean;
  /** Set while a paid-out payout is still unconfirmed. While it is, NO further
   *  payout leaves — that caps a wrong or hijacked destination at one payout. */
  awaiting_confirmation: {
    payout_id: number;
    amount: string;
    sent_at: string | null;
    destination: string;
    attempts_left: number;
  } | null;
  explainer: string;
}

/** Past-due state, derived live from what the ISP owes vs their credit limit. Drives the
 *  banner and explains why writes are refused when locked. */
export interface BillingState {
  owed: string;
  credit_limit: string;
  level: 'current' | 'warned' | 'restricted' | 'locked';
  restrict_at: string;
  lock_at: string;
}

export interface MeOperator {
  id: number;
  name: string;
  slug: string;
  status: 'pending' | 'active' | 'suspended';
  is_platform_owned: boolean;
  /** Read-only showcase tenant: the console shows a demo banner and the API refuses writes. */
  is_demo: boolean;
  /** THE MONEY GATE. False => this ISP cannot collect, provision or withdraw. */
  can_transact: boolean;
  /** Why not, and what to do about it. Empty when they're live. */
  go_live_blockers: GoLiveBlocker[];
  billing: BillingState;
}

export interface Me {
  phone: string;
  name: string;
  is_staff: boolean;
  role: Role;
  is_platform_staff: boolean;
  is_read_only: boolean;
  can_manage_money: boolean;
  /** The resolved capability set for this role — drives which nav items and controls show. */
  capabilities: Capability[];
  /** Onboarding gates the console renders full-screen before letting the user work. */
  must_change_password: boolean;
  must_enrol_2fa: boolean;
  /** The user's home ISP (null for platform-only staff). */
  operator: MeOperator | null;
  /** The ISP this session is currently acting for (platform staff can switch). */
  acting_operator: MeOperator | null;
}

/** Does this session hold `cap`? The single check every nav filter and control guard uses.
 *  Server is authoritative — this only decides what to SHOW. */
export function can(me: Me | null, cap: Capability): boolean {
  return !!me && me.capabilities.includes(cap);
}

export interface PlatformOverview {
  scope: 'all_isps';
  tenants_total: number;
  tenants_pending: number;
  tenants_active: number;
  tenants_suspended: number;
  platform_revenue_month: string | number;
  gross_volume_month: string | number;
  transactions_month: number;
  routers_online: number;
  routers_total: number;
  active_sessions: number;
  new_tenants_30d: number;
}

export interface WalletSummary {
  balance: string | number;
  minimum_payout: string | number;
  month_gross: string | number;
  month_commission: string | number;
  month_fees: string | number;
  month_withdrawn: string | number;
  pending_payouts: string | number;
  commission_rate: string | number;
}

export interface RevenueReport {
  from: string;
  to: string;
  total: number;
  hotspot_total: number;
  pppoe_total: number;
  hotspot_count: number;
  pppoe_count: number;
  by_plan: { plan: string; revenue: number; count: number }[];
  daily: { day: string; revenue: number }[];
}

export interface ApiLedgerEntry {
  id: number;
  entry_type: 'sale' | 'commission' | 'base_fee' | 'pppoe_fee' | 'setup_fee' | 'payout' | 'adjustment';
  amount: string;
  memo: string;
  period: string;
  created_at: string;
}

export interface ApiPayout {
  id: number;
  operator_name: string;
  operator_slug: string;
  amount: string;
  method: 'mpesa' | 'bank';
  phone: string;
  bank_name: string;
  bank_account_number: string;
  bank_account_name: string;
  destination: string;
  status: 'requested' | 'paid' | 'rejected';
  mpesa_reference: string;
  note: string;
  created_at: string;
  processed_at: string | null;
}

/** Preview of a withdrawal's transfer cost, before committing. */
export interface PayoutQuote {
  amount: string;
  /** The transfer cost the ISP bears (charged by the rail, not WIFI.OS). */
  cost: string;
  /** What actually reaches them: amount − cost. */
  net: string;
  cost_destination: string;
  /** Where the money is going — the verified settlement account. */
  destination: string | null;
  has_account: boolean;
  note: string;
}

export interface WithdrawPayload {
  amount: string;
  /** Six digits from the owner's authenticator app — or one of their recovery codes.
   *  Money does not leave without it. The DESTINATION is not sent: it's the verified
   *  settlement account, decided server-side. */
  mfa_code?: string;
}

export interface MfaStatus {
  enrolled: boolean;
  confirmed_at: string | null;
  recovery_codes_left: number;
  why: string;
}

export interface MfaSetup {
  /** A PNG data URI. Rendered server-side — our CSP forbids fetching a QR library
   *  from a CDN, and bundling one to draw a picture of a secret the server already
   *  has would be silly. */
  qr: string;
  uri: string;
  /** For anyone who cannot scan (a desktop authenticator, say). */
  secret: string;
}

/** A 403 the console must not render as a red error: it means "ask for a code", or
 *  "send them to enrol", depending on `enrolled`. */
export interface MfaChallenge {
  mfa_required: true;
  enrolled: boolean;
  detail: string;
}

export function asMfaChallenge(err: unknown): MfaChallenge | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as Partial<MfaChallenge> | null;
  return body?.mfa_required ? (body as MfaChallenge) : null;
}

export interface ApiTenant {
  id: number;
  name: string;
  slug: string;
  status: 'pending' | 'active' | 'suspended';
  owner_name: string;
  contact_phone: string;
  contact_email: string;
  base_fee: string;
  hotspot_commission_pct: string;
  pppoe_user_fee: string;
  setup_fee: string;
  trial_ends_at: string | null;
  approved_at: string | null;
  created_at: string;
  router_count: number;
  staff_count: number;
}

export interface Branding {
  display_name: string;
  name_for_customers: string;
  tagline: string;
  logo: string;
  primary_color: string;
  accent_color: string;
  support_phone: string;
  support_email: string;
  // Captive-portal look
  portal_template: string;
  background_image: string;
  portal_language: string;
  post_purchase_redirect: string;
  /** [id, label] pairs — the catalogue the portal-template picker renders. */
  portal_templates: [string, string][];
}

export interface HotspotSettings {
  timer_start_mode: 'on_purchase' | 'on_login';
  inactive_prune_days: number | null;
  username_prefix: string;
  voucher_expiry_days: number;
  choices: {
    timer_start_modes: { value: string; label: string }[];
    prune_days: number[];
  };
}

export type HotspotSettingsUpdate = Omit<HotspotSettings, 'choices'>;

export interface MessageTemplate {
  key: string;
  group: string;
  label: string;
  description: string;
  default_body: string;
  body: string;
  is_customized: boolean;
  is_enabled: boolean;
  variables: { name: string; sample: string }[];
}

export interface MessageTemplatesResponse {
  groups: string[];
  templates: MessageTemplate[];
}

export interface LoyaltySettings {
  is_enabled: boolean;
  spend_per_point: number;
  points_per_threshold: number;
  min_redeem_points: number;
  value_per_point: string;
}

export interface LoyaltySummary {
  accounts: number;
  points_outstanding: number;
  top: { phone: string; points: number }[];
}

export type MapLayer = 'towers' | 'clients' | 'routers' | 'leads' | 'fibre';
/** The 8 fibre-plant point types (mirrors backend FibrePoint.Type). */
export type FibreType =
  | 'olt_pop' | 'cabinet' | 'splice_closure' | 'splitter' | 'odp' | 'pole' | 'handhole' | 'other';
export interface MapPoint {
  id: number;
  lat: number;
  lng: number;
  label: string;
  status: string;
  account?: string;
  connection?: string;
  phone?: string;
  plan?: string;
  source?: string;
  // fibre points carry their type + capacity
  ptype?: FibreType;
  capacity?: number;
  used?: number;
  free?: number | null;
  // routers carry a live count of active hotspot sessions (for the on-pin badge)
  hotspot?: number;
}
/** A fibre span drawn as a line between its two placed endpoints. */
export interface FibreSpanSeg {
  id: number;
  cable_type: 'adss' | 'buried' | 'drop';
  status: string;
  from_lat: number;
  from_lng: number;
  to_lat: number;
  to_lng: number;
}
/** A shortest cable route through the plant (Dijkstra result). */
export interface FibreRoutePoint { id: number; label: string; type: FibreType; lat: number | null; lng: number | null; }
export interface FibreRoute {
  from_snapped: { point: FibreRoutePoint; distance_m: number } | null;
  points: FibreRoutePoint[];
  spans: { id: number; from_point: number; to_point: number; length_m: number | null; cable_type: string }[];
  total_m: number;
  span_count: number;
  splice_count: number;
}
export interface MapData {
  business_location: { lat: number; lng: number } | null;
  layers: Record<MapLayer, MapPoint[]>;
  fibre_spans: FibreSpanSeg[];
  counts: Record<MapLayer, number>;
  unplaced: Record<MapLayer, number>;
  center: { lat: number; lng: number } | null;
}
export interface BusinessLocation {
  gps_lat: number | null;
  gps_lng: number | null;
}
// One place suggestion from the map search box. `label` is the primary line, `secondary` the
// grey context line beneath it (locality, region, country) — Google/Apple style.
export interface GeoResult {
  label: string;
  secondary: string;
  lat: number;
  lng: number;
  type: string;
}

// ---- Fibre plant (console CRUD) -----------------------------------------------
export type PlantStatus = 'ok' | 'needs_attention' | 'down';
export interface FibrePoint {
  id: number;
  type: FibreType;
  type_display: string;
  label: string;
  gps_lat: string | null;
  gps_lng: string | null;
  status: PlantStatus;
  port_capacity: number;
  splitter_ratio: string;
  notes: string;
  is_active: boolean;
  used: number;
  free: number | null;
  created_at: string;
}
export interface FibreSpan {
  id: number;
  from_point: number;
  to_point: number;
  from_label: string;
  to_label: string;
  cable_type: 'adss' | 'buried' | 'drop';
  fibre_count: number;
  length_m: number | null;
  status: PlantStatus;
  notes: string;
  is_active: boolean;
  created_at: string;
}
export interface AffectedClient {
  id: number;
  full_name: string;
  account_number: string;
  phone: string;
  status: string;
  plan: string;
}
export interface BlastRadius {
  point: { id: number; label: string; status: string };
  count: number;
  clients: AffectedClient[];
}

// ---- Fleet tracking -----------------------------------------------------------
export interface FleetMember {
  technician_id: number;
  name: string;
  phone: string;
  lat: string;
  lng: string;
  accuracy: number | null;
  heading: string | null;
  recorded_at: string;
  is_live: boolean;
}
export interface FleetData {
  live_window_minutes: number;
  members: FleetMember[];
}
export interface NearestTech {
  technician_id: number;
  name: string;
  phone: string;
  lat: string;
  lng: string;
  recorded_at: string;
  distance_km: number;
}
export interface NearestData {
  target: { lat: number; lng: number };
  count: number;
  technicians: NearestTech[];
}

export interface LoyaltyRedeemablePlan {
  plan_id: number;
  plan_name: string;
  price: string;
  points_cost: number;
  affordable: boolean;
}
export interface LoyaltyAccountView {
  phone: string;
  found: boolean;
  points_balance: number;
  value_kes: string;
  min_redeem_points: number;
  redeemable_plans: LoyaltyRedeemablePlan[];
  recent: { kind: string; points: number; reason: string; created_at: string }[];
}

/** Settings > Developer — API tokens & webhooks. */
export interface ApiToken {
  id: number;
  name: string;
  prefix: string;
  last_used_at: string | null;
  created_at: string;
  is_active: boolean;
}
/** Returned by create — the plaintext token, shown exactly once. */
export interface NewApiToken extends ApiToken {
  token: string;
}
export interface Webhook {
  id: number;
  label: string;
  url: string;
  events: string[];
  is_active: boolean;
  secret_preview: string;
  last_delivered_at: string | null;
  last_status: number | null;
  last_error: string;
  created_at: string;
}
export interface WebhookEvent {
  key: string;
  label: string;
}

/** Settings > AI Assistant. */
export interface AISettings {
  provider: 'claude' | 'openai';
  has_own_key: boolean;
  /** Masked hint (e.g. "sk-ant-…4f2a"); never the whole key. */
  key_preview: string;
  platform_default_available: boolean;
  platform_default_provider: 'claude' | 'openai';
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}
/** A doc passage the assistant grounded its answer in (shown as a citation). */
export interface ChatSource {
  slug: string;
  title: string;
  heading: string;
}
/** The ISP's assistant tier and this month's usage — drives the widget meter + upgrade prompt. */
export interface AIUsage {
  tier: 'free' | 'pro' | 'byo';
  unlimited: boolean;
  used: number;
  limit: number | null;
  remaining: number | null;
  pro_monthly_fee: string;
  pro_self_serve: boolean;
}
/** The assistant's reply: the text, the docs it cited, the id to attach a 👍/👎 to, and usage. */
export interface ChatReply {
  reply: string;
  sources: ChatSource[];
  question_id: number;
  usage: AIUsage;
}
/** A saved chat thread (multi-conversation), and its stored messages. */
export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}
export interface ConvMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  sources: ChatSource[];
  question_id: number | null;
  created_at: string;
}
export interface ConversationDetail extends Conversation {
  messages: ConvMessage[];
}
export interface SendResult {
  message: ConvMessage;
  usage: AIUsage;
}

/** Settings > Operator alerts. */
export interface OperatorAlertSettings {
  router_alerts_enabled: boolean;
  /** Normalised 2547XXXXXXXX. Empty = notify every admin. */
  router_alert_phones: string[];
  prefer_whatsapp: boolean;
  compensate_outages: boolean;
  sales_digest_enabled: boolean;
}

/** Returned as a 409 when adding/moving a client onto a full sector. */
export interface CapacityWarning {
  code: 'sector_at_capacity';
  detail: string;
  sector: string;
  count: number;
  capacity: number;
  tower: string;
  tower_utilization: number | null;
}

export interface OperatorSettings {
  name: string;
  slug: string;
  status: string;
  owner_name: string;
  contact_phone: string;
  contact_email: string;
  commission_rate: string;
}

/** A gateway an ISP can send through.
 *
 *  Note what is NOT here: the credential values. The API never returns a saved secret —
 *  only whether one is `set`. A secret field submits blank unless it is being changed,
 *  which the server reads as "keep the one you have". So an SMS key is never sitting in
 *  a browser. */
export interface ProviderField {
  key: string;
  label: string;
  secret: boolean;
  placeholder: string;
  required: boolean;
  /** Echoed for plain fields so the form is editable; always "" for a secret. */
  value: string;
  /** Whether a value is stored. For a secret this is all we are told. */
  set: boolean;
}

export interface ProviderCard {
  id: string;
  name: string;
  region: string;
  /** The WIFI.OS gateway: no credentials, paid for in credits. */
  managed: boolean;
  note: string;
  active: boolean;
  configured: boolean;
  fields: ProviderField[];
}

export interface CreditBundle {
  id: string;
  /** What they pay by STK. */
  price: string;
  /** What we credit — larger than `price` on the bigger bundles. The volume discount is
   *  expressed as bonus credit, because the balance is in shillings and an SMS has one
   *  price. */
  credit: string;
  bonus: string;
  sms: number;
  per_sms: string;
}

/** The ISP's account WITH US — what they owe, or have prepaid. NOT the wallet (which is
 *  money we hold FOR them). It may be NEGATIVE: this is postpaid. */
export interface PlatformAccount {
  balance: string;
  /** The same number in messages, because "KSh 640" does not tell an ISP whether tonight's
   *  reminders will go out. */
  sms_remaining: number;
  sms_price: string;
  low: boolean;
  can_send_sms: boolean;
  low_balance_threshold: string;
  alert_phones: string[];
  bundles: CreditBundle[];
  min_topup: string;
}

export interface PlatformInvoiceLine {
  label: string;
  amount: string;
  /** False for the aggregator commission we already took — shown, but not owed. */
  due: boolean;
}
export interface PlatformInvoice {
  period: string;
  issued_at: string;
  status: 'outstanding' | 'paid';
  paid_at: string | null;
  total: string;
  lines: PlatformInvoiceLine[];
}

export interface TopUpStarted {
  id: number;
  amount: string;
  credit: string;
  status: string;
  detail: string;
}

export interface TopUpStatus {
  id: number;
  status: 'pending' | 'success' | 'failed' | 'timeout';
  amount: string;
  credit: string;
  mpesa_receipt: string;
  result_desc: string;
  account: PlatformAccount;
}

export interface ProvidersResponse {
  channel: 'sms' | 'whatsapp';
  active: string;
  providers: ProviderCard[];
  /** SMS only. */
  account?: PlatformAccount;
  /** WhatsApp only. */
  note?: string;
}

/** A field on a payment-gateway credential form. Same shape as ProviderField, plus the
 *  M-Pesa specifics (choices for paybill-vs-till, help text). */
export interface GatewayField {
  key: string;
  label: string;
  secret: boolean;
  placeholder: string;
  required: boolean;
  help: string;
  choices: { value: string; label: string }[];
  /** Echoed for plain fields so the form is editable; always "" for a secret. */
  value: string;
  set: boolean;
}

/** A payment gateway an ISP can collect through. The `settlement` flag is the whole
 *  finance refactor: `platform` money lands with us (we withhold 3%, they withdraw);
 *  `direct` lands in their own account instantly and we invoice our fee. */
export interface PaymentGatewayCard {
  id: string;
  name: string;
  region: string;
  methods: string[];
  settles: string;
  settlement: 'platform' | 'direct';
  managed: boolean;
  note: string;
  available: boolean;
  active: boolean;
  configured: boolean;
  fields: GatewayField[];
  /** The URL the ISP must register with Safaricom. Empty for the managed gateway. */
  webhook_url: string;
}

export interface PaymentGatewaysState {
  active: string;
  gateways: PaymentGatewayCard[];
}

/** A router, and whether it is actually sending customers to the ISP's CURRENT address.
 *  An offline router keeps redirecting to the old one — which is exactly the thing the
 *  ISP needs to see rather than assume. */
export interface DomainRouter {
  id: number;
  name: string;
  online: boolean;
  portal_url: string;
  synced_at: string | null;
  error: string;
  on_current_domain: boolean;
}

/** Settings > PPPoE. The `choices` drive the chip options; `fup_metering_ready` lets the
 *  UI be honest that FUP thresholds are stored but not yet firing. */
export interface PppoeSettings {
  inactive_prune_days: number | null;
  /** Auto-mark a suspended (overdue) account as cancelled/churned after this many days.
   *  null = never (the ISP decides who has truly left). */
  churn_after_suspended_days: number | null;
  pre_expiry_reminder_hours: number[];
  fup_alert_percents: number[];
  auto_generate_invoices: boolean;
  invoice_prefix: string;
  choices: { prune_days: number[]; churn_days: number[]; reminder_hours: number[]; fup_percents: number[] };
  fup_metering_ready: boolean;
}
export type PppoeSettingsUpdate = Omit<PppoeSettings, 'choices' | 'fup_metering_ready'>;

export interface DomainState {
  slug: string;
  domain: string;
  url: string;
  base_domain: string;
  /** Where routers actually send phones. Differs from `url` only in dev/staging. */
  portal_url: string;
  previous_slug: string;
  /** Non-empty only while the old address still resolves. */
  previous_url: string;
  grace_ends: string | null;
  grace_days: number;
  routers: DomainRouter[];
  routers_queued?: number;
}

export interface DomainCheck {
  slug: string;
  available: boolean;
  current: boolean;
  url: string;
  reason: string;
}

export interface EmailSettings {
  email_mode: 'platform' | 'own';
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_use_tls: boolean;
  from_email: string;
  from_name: string;
  smtp_password_configured: boolean;
}

export type EmailSettingsUpdate = Partial<Omit<EmailSettings, 'smtp_password_configured'>> & {
  smtp_password?: string;
};

// ---- PPPoE / Broadband ----------------------------------------------------

export interface PppoePlan {
  id: number;
  name: string;
  price: string;
  download_kbps: number;
  upload_kbps: number;
  data_cap_gb: number | null;
  mikrotik_profile: string;
  is_active: boolean;
  sort_order: number;
}

/** Off-system payment methods — money the ISP collected directly, not through the paybill. */
export type OffSystemMethod = 'cash' | 'mpesa_direct' | 'bank' | 'other';

export const OFF_SYSTEM_METHODS: { value: OffSystemMethod; label: string }[] = [
  { value: 'cash', label: 'Cash' },
  { value: 'mpesa_direct', label: 'M-Pesa (to your number)' },
  { value: 'bank', label: 'Bank transfer' },
  { value: 'other', label: 'Other' },
];

export interface PppoeClient {
  id: number;
  account_number: string;
  full_name: string;
  phone: string;
  email: string;
  physical_address: string;
  gps_lat: string | null;
  gps_lng: string | null;
  plan: number;
  plan_name: string;
  router: number;
  pppoe_username: string;
  pppoe_password: string;
  static_ip: string | null;
  connection_type: 'pppoe' | 'static';
  delivery_method: 'fibre' | 'ethernet' | 'wireless_ptp' | 'wireless_ptmp';
  access_point: number | null;
  cpe_equipment: number | null;
  /** For fibre customers: the ODP/splitter that feeds them (blast-radius). */
  fibre_point: number | null;
  fibre_point_label?: string;
  status: 'pending_install' | 'active' | 'suspended' | 'cancelled' | 'disabled';
  billing_day: number;
  balance: string;
  next_due_date: string | null;
  /** Never blank: the real invoice due date, or one projected from their billing day. */
  next_billing_date: string;
  next_due_is_projected: boolean;
  installed_at: string | null;
  notes: string;
  created_at: string;
  // Live metering (read-only). is_online + usage refreshed every ~5 min by the poller.
  is_online: boolean;
  last_online_at: string | null;
  wan_ip: string | null;
  session_uptime: string;
  usage_synced_at: string | null;
  data_cap_gb: number | null;
  usage: {
    period_start: string;
    bytes_total: number;
    gb_total: number;
    cap_gb: number | null;
    percent_used: number | null;
  };
}

/** The PPPoE dashboard tile — live fixed-line health for the acting ISP. */
export interface PppoeUsageSummary {
  clients_total: number;
  clients_active: number;
  online_now: number;
  data_gb_this_cycle: number;
  over_fup: number;
  top_consumers: {
    account_number: string;
    full_name: string;
    gb_total: number;
    percent_used: number | null;
  }[];
  synced_at: string | null;
}

/** Subscriber movement over time — the churn/retention picture a status column can't give. */
export interface PppoeChurnMonth {
  month: string; // "YYYY-MM"
  active_start: number;
  new: number;
  reactivated: number;
  suspended: number;
  restored: number;
  churned: number;
  net: number;
  churn_rate: number | null; // churned / active_start, or null when the base was empty
}
export interface PppoeChurnSummary {
  as_of: string;
  standing: Record<'pending_install' | 'active' | 'suspended' | 'cancelled' | 'disabled', number>;
  months: PppoeChurnMonth[];
}

export interface PppoeCsvRow {
  line: number;
  full_name: string;
  phone: string;
  account_number: string;
  pppoe_username: string;
  csv_plan: string;
  has_password: boolean;
  problem: string;
  importable: boolean;
}
export interface PppoeCsvPlan {
  csv_plan: string;
  plan: number | null;
  plan_name: string | null;
}
export interface PppoeCsvPreview {
  rows: PppoeCsvRow[];
  importable: number;
  blocked: number;
  plans: PppoeCsvPlan[];
}

export interface PppoeImportRow {
  username: string;
  profile: string;
  comment: string;
  already_managed: boolean;
  suggested_plan: number | null;
  suggested_plan_name: string | null;
}
export interface PppoeImportItem {
  username: string;
  full_name?: string;
  plan: number;
}
export interface PppoeImportResult {
  imported: { username: string; account_number: string }[];
  skipped: { username: string; reason: string }[];
  failed: { username: string; reason: string }[];
}

export interface PppoeInvoice {
  id: number;
  number: string;
  account_number: string;
  client_name: string;
  period_start: string;
  period_end: string;
  amount: string;
  due_date: string;
  status: 'unpaid' | 'paid' | 'overdue' | 'cancelled';
  issued_at: string;
  paid_at: string | null;
}

export interface Tower {
  id: number;
  name: string;
  gps_lat: string | null;
  gps_lng: string | null;
  notes: string;
  is_active: boolean;
  access_point_count: number;
}

export interface AccessPoint {
  id: number;
  tower: number;
  tower_name: string;
  name: string;
  mode: 'ap' | 'ptp' | 'ptmp';
  band: string;
  capacity: number;
  router: number | null;
  ssid: string;
  is_active: boolean;
  client_count: number;
  utilization: number | null;
}

export interface Reconciliation {
  scope: 'all_isps';
  total_collected: string | number;
  platform_earnings: string | number;
  transaction_costs: string | number;
  collection_costs: string | number;
  payout_costs: string | number;
  net_margin: string | number;
  owed_to_isps: string | number;
  total_disbursed: string | number;
  pending_payouts: string | number;
  current_float: string | number;
}

export interface NavCounts {
  active_users: number;
  users: number;
  tickets: number;
  leads: number;
  packages: number;
  vouchers: number;
  campaigns: number;
  mikrotik: number;
  equipment: number;
}

export interface ApiSubscriber {
  id: number;
  phone: string;
  name: string;
  email: string;
  date_joined: string;
  last_session_expires: string | null;
  active_sessions: number;
}

export interface DashboardStats {
  kpis: {
    revenue_today: number | string;
    revenue_7d: number | string;
    revenue_month: number | string;
    revenue_prev_month: number | string;
    transactions_today: number;
    failed_today: number;
    success_rate_7d: number | null;
    /** Everyone online now across ALL service types (hotspot + PPPoE + future). */
    active_sessions: number;
    /** Per-service breakdown of active_sessions, e.g. { hotspot: 90, pppoe: 52 }. */
    active_by_service: Record<string, number>;
    sessions_expiring_1h: number;
    total_subscribers: number;
    new_subscribers_7d: number;
    arpu_month: number | null;
    unused_vouchers: number;
    vouchers_redeemed_7d: number;
  };
  /** Fixed-line (PPPoE) KPI row — a recurring-revenue business, so its own metric family. */
  pppoe: {
    mrr: number | string;
    outstanding: number | string;
    collected_month: number | string;
    renewals_due_7d: number;
    renewals_due_7d_value: number | string;
    active_subscribers: number;
    new_this_month: number;
    churn_rate: number | null;
    churned_this_month: number;
    suspended: number;
  };
  revenue_daily: { day: string; revenue: string; transactions: number }[];
  tx_by_hour: { hour: number; count: number }[];
  plan_breakdown: { plan__name: string; count: number; revenue: string }[];
  payment_split: { mpesa: number; voucher: number };
  sessions_daily: { day: string; sessions: number }[];
  routers: {
    id: number;
    name: string;
    status: 'online' | 'offline' | 'unknown';
    last_seen_at: string | null;
    active_sessions: number;
  }[];
  generated_at: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// ---- endpoints ----------------------------------------------------------

function crud<T>(base: string) {
  return {
    list: (query = '') => request<Paginated<T>>(`${base}/${query}`),
    create: (data: Partial<T>) => request<T>(`${base}/`, { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<T>) =>
      request<T>(`${base}/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
    remove: (id: number) => request<null>(`${base}/${id}/`, { method: 'DELETE' }),
  };
}

export function signup(data: {
  business_name: string;
  slug?: string;
  owner_name: string;
  phone: string;
  email: string;
  password: string;
}): Promise<{ slug: string; status: string; detail: string }> {
  return fetch(`${BASE}/api/v1/tenants/signup/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(async (resp) => {
    const body = await resp.json().catch(() => null);
    if (!resp.ok) throw new ApiError(resp.status, body);
    return body;
  });
}

export interface Broadcast {
  id: number;
  title: string;
  body: string;
  level: 'info' | 'warning' | 'critical';
  dismissable: boolean;
  starts_at: string;
}

export const api = {
  stats: () => request<DashboardStats>('/stats/'),
  navCounts: () => request<NavCounts>('/nav/'),

  /** Platform-wide notices Danamo pushes to every ISP console (maintenance, price changes,
   *  outages). Live + not-yet-dismissed-by-me. */
  activeBroadcasts: () => request<Broadcast[]>('/broadcasts/active/'),
  dismissBroadcast: (id: number) =>
    request<{ detail: string }>(`/broadcasts/${id}/dismiss/`, { method: 'POST', body: '{}' }),
  /** Also the "am I signed in / which ISP am I in?" probe — only the server knows. */
  me: () => request<Me>('/me/'),

  /** Employee management (Owner/Admin). The server enforces the guardrails — you may only
   *  assign admin/care/technician, never the owner or yourself. */
  staff: {
    list: () => request<Paginated<StaffMember>>('/staff/').then((r) => r.results),
    create: (data: { name: string; phone: string; email?: string; role: Role; password: string }) =>
      request<StaffMember>('/staff/', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<Pick<StaffMember, 'name' | 'role' | 'is_active'>>) =>
      request<StaffMember>(`/staff/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
    offboard: (id: number) => request<null>(`/staff/${id}/`, { method: 'DELETE' }),
    resetPassword: (id: number, password: string) =>
      request<{ detail: string }>(`/staff/${id}/reset-password/`, {
        method: 'POST',
        body: JSON.stringify({ password }),
      }),
  },

  /** Fibre outside-plant CRUD (fibre.write). Points, spans, and a point's blast radius. */
  fibre: {
    points: {
      list: (query = '') => request<Paginated<FibrePoint>>(`/fibre/points/${query}`),
      create: (data: Partial<FibrePoint>) =>
        request<FibrePoint>('/fibre/points/', { method: 'POST', body: JSON.stringify(data) }),
      update: (id: number, data: Partial<FibrePoint>) =>
        request<FibrePoint>(`/fibre/points/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
      remove: (id: number) => request<null>(`/fibre/points/${id}/`, { method: 'DELETE' }),
      restore: (id: number) =>
        request<FibrePoint>(`/fibre/points/${id}/restore/`, { method: 'POST', body: '{}' }),
      affected: (id: number) => request<BlastRadius>(`/fibre/points/${id}/affected/`),
    },
    spans: {
      list: (query = '') => request<Paginated<FibreSpan>>(`/fibre/spans/${query}`),
      create: (data: Partial<FibreSpan>) =>
        request<FibreSpan>('/fibre/spans/', { method: 'POST', body: JSON.stringify(data) }),
      update: (id: number, data: Partial<FibreSpan>) =>
        request<FibreSpan>(`/fibre/spans/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
      remove: (id: number) => request<null>(`/fibre/spans/${id}/`, { method: 'DELETE' }),
    },
    // Shortest CABLE route through the plant (Dijkstra, server-side). Source is a point or a raw
    // coordinate that snaps to the nearest point; target is a point or a customer (→ their ODP).
    route: (params: {
      fromPoint?: number; fromLat?: number; fromLng?: number;
      toPoint?: number; toClient?: number;
    }) => {
      const p = new URLSearchParams();
      if (params.fromPoint != null) p.set('from_point', String(params.fromPoint));
      if (params.fromLat != null && params.fromLng != null) {
        p.set('from_lat', String(params.fromLat));
        p.set('from_lng', String(params.fromLng));
      }
      if (params.toPoint != null) p.set('to_point', String(params.toPoint));
      if (params.toClient != null) p.set('to_client', String(params.toClient));
      return request<FibreRoute>(`/fibre/route/?${p.toString()}`);
    },
  },

  /** Fleet tracking. A technician reports their own position; a dispatcher sees the fleet. */
  fleet: {
    ping: (data: { lat: string; lng: string; accuracy?: number; heading?: number }) =>
      request<{ detail: string }>('/fleet/ping/', { method: 'POST', body: JSON.stringify(data) }),
    list: () => request<FleetData>('/fleet/'),
    nearest: (lat: number, lng: number) =>
      request<NearestData>(`/fleet/nearest/?lat=${lat}&lng=${lng}`),
    dispatch: (ticketId: number, lat: number, lng: number) =>
      request<{ detail: string; technician_id: number; technician_name: string; distance_km: number }>(
        `/ops/tickets/${ticketId}/dispatch/`,
        { method: 'POST', body: JSON.stringify({ lat, lng }) },
      ),
  },

  /** Access Control (Owner only): edit what each delegated role may do. */
  rbac: {
    get: () => request<AccessControlData>('/rbac/'),
    setRole: (role: Role, capabilities: Capability[]) =>
      request<RoleState>(`/rbac/${role}/`, { method: 'PUT', body: JSON.stringify({ capabilities }) }),
    resetRole: (role: Role) => request<RoleState>(`/rbac/${role}/`, { method: 'DELETE' }),
  },

  /** Leave an ISP we were granted access to. The server clears the acting-tenant
   * cookie, so the next request is back in our own console — nothing to clean up
   * on this side. */
  endImpersonation: () =>
    request<{ ended: number }>('/platform/impersonation/end/', {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  /** Where WE pay THEM. Registering is INSTANT — that's what switches payments on.
   *  The first payout then carries a code they read back, which unlocks the rest. */
  /** Change the signed-in user's password (needs the current one). */
  changePassword: (current_password: string, new_password: string) =>
    request<{ detail: string }>('/auth/change-password/', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),

  mfa: {
    status: () => request<MfaStatus>('/auth/mfa/'),
    setup: () => request<MfaSetup>('/auth/mfa/setup/', { method: 'POST' }),
    confirm: (code: string) =>
      request<{ detail: string; recovery_codes: string[]; warning: string }>(
        '/auth/mfa/confirm/',
        { method: 'POST', body: JSON.stringify({ code }) }
      ),
    regenerate: (code: string) =>
      request<{ recovery_codes: string[]; detail: string }>('/auth/mfa/recovery-codes/', {
        method: 'POST',
        body: JSON.stringify({ code }),
      }),
    disable: (code: string) =>
      request<{ detail: string }>('/auth/mfa/disable/', {
        method: 'POST',
        body: JSON.stringify({ code }),
      }),
  },

  settlement: {
    get: () => request<Settlement>('/operator/settlement/'),
    set: (body: Record<string, string>) =>
      request<Settlement & { detail: string }>('/operator/settlement/', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    confirm: (code: string) =>
      request<Settlement & { detail: string }>('/operator/settlement/confirm/', {
        method: 'POST',
        body: JSON.stringify({ code }),
      }),
  },

  operatorSettings: {
    get: () => request<OperatorSettings>('/operator/settings/'),
    update: (data: Record<string, string>) =>
      request<OperatorSettings>('/operator/settings/', { method: 'PATCH', body: JSON.stringify(data) }),
  },

  branding: {
    get: () => request<Branding>('/operator/branding/'),
    update: (data: Partial<Branding>) =>
      request<Branding>('/operator/branding/', { method: 'PATCH', body: JSON.stringify(data) }),
    /** Multipart upload — the browser sets the boundary Content-Type, so we bypass the
     *  JSON request helper but keep the cookie + CSRF token. */
    uploadLogo: async (file: File): Promise<{ logo: string }> => {
      const form = new FormData();
      form.append('logo', file);
      const resp = await fetch(`${BASE}/api/v1/operator/branding/logo/`, {
        ...withCookies,
        method: 'POST',
        headers: { 'X-CSRFToken': readCsrfToken() },
        body: form,
      });
      const body = await resp.json().catch(() => null);
      if (!resp.ok) throw new ApiError(resp.status, body);
      return body as { logo: string };
    },
    deleteLogo: () =>
      request<{ logo: string }>('/operator/branding/logo/', { method: 'DELETE' }),
    uploadBackground: async (file: File): Promise<{ background_image: string }> => {
      const form = new FormData();
      form.append('background', file);
      const resp = await fetch(`${BASE}/api/v1/operator/branding/background/`, {
        ...withCookies,
        method: 'POST',
        headers: { 'X-CSRFToken': readCsrfToken() },
        body: form,
      });
      const body = await resp.json().catch(() => null);
      if (!resp.ok) throw new ApiError(resp.status, body);
      return body as { background_image: string };
    },
    deleteBackground: () =>
      request<{ background_image: string }>('/operator/branding/background/', {
        method: 'DELETE',
      }),
  },

  hotspotSettings: {
    get: () => request<HotspotSettings>('/operator/hotspot/'),
    update: (data: Partial<HotspotSettingsUpdate>) =>
      request<HotspotSettings>('/operator/hotspot/', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
  },

  account: {
    /** The ISP's balance with us, and the bundles they can buy. */
    get: () => request<PlatformAccount>('/billing/account/'),

    /** Start an STK push so the ISP can pay US. No TOTP: money is coming IN, from their
     *  own phone, and Safaricom already demands their M-Pesa PIN. */
    topUp: (params: { phone: string; bundle?: string; amount?: string }) =>
      request<TopUpStarted>('/billing/topup/', {
        method: 'POST',
        body: JSON.stringify(params),
      }),

    /** Polled while they enter their PIN. */
    topUpStatus: (id: number) => request<TopUpStatus>(`/billing/topup/${id}/`),

    alerts: (data: { low_balance_threshold?: string; alert_phones?: string[] }) =>
      request<PlatformAccount>('/billing/account/alerts/', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),

    /** Monthly statements — the itemised record of every fee WIFI.OS charged this ISP. */
    invoices: () => request<{ invoices: PlatformInvoice[] }>('/billing/account/invoices/'),
  },

  pppoeSettings: {
    get: () => request<PppoeSettings>('/pppoe/settings/'),
    update: (data: Partial<PppoeSettingsUpdate>) =>
      request<PppoeSettings>('/pppoe/settings/', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
  },

  loyalty: {
    get: () => request<LoyaltySettings>('/loyalty/settings/'),
    update: (data: Partial<LoyaltySettings>) =>
      request<LoyaltySettings>('/loyalty/settings/', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    summary: (q = '') => request<LoyaltySummary>(`/loyalty/summary/${q ? `?q=${encodeURIComponent(q)}` : ''}`),
    account: (phone: string) =>
      request<LoyaltyAccountView>(`/loyalty/account/?phone=${encodeURIComponent(phone)}`),
    redeem: (phone: string, plan_id: number) =>
      request<{ detail: string; voucher_code: string; plan: string; points_spent: number; points_balance: number }>(
        '/loyalty/redeem/', { method: 'POST', body: JSON.stringify({ phone, plan_id }) }),
    adjust: (phone: string, points: number, reason: string) =>
      request<{ detail: string; points_balance: number }>(
        '/loyalty/adjust/', { method: 'POST', body: JSON.stringify({ phone, points, reason }) }),
  },

  /** The Map page: every geolocated thing this ISP owns, tenant-scoped. */
  map: {
    points: () => request<MapData>('/map/points/'),
    businessLocation: () => request<BusinessLocation>('/map/business-location/'),
    setBusinessLocation: (gps_lat: number | null, gps_lng: number | null) =>
      request<{ detail: string; gps_lat: number | null; gps_lng: number | null }>(
        '/map/business-location/', { method: 'POST', body: JSON.stringify({ gps_lat, gps_lng }) }),
    // Place/address autocomplete for the map search box. lat/lng bias the ranking toward the
    // current viewport (nearby first); they never restrict results to a region.
    search: (q: string, lat?: number, lng?: number, signal?: AbortSignal) => {
      const p = new URLSearchParams({ q });
      if (lat != null && lng != null) { p.set('lat', String(lat)); p.set('lng', String(lng)); }
      return request<{ results: GeoResult[] }>(`/map/search/?${p.toString()}`, { signal });
    },
  },

  developer: {
    tokens: {
      list: () => request<Paginated<ApiToken>>('/developer/tokens/').then((r) => r.results),
      create: (name: string) =>
        request<NewApiToken>('/developer/tokens/', {
          method: 'POST',
          body: JSON.stringify({ name }),
        }),
      revoke: (id: number) =>
        request<void>(`/developer/tokens/${id}/`, { method: 'DELETE' }),
    },
    webhooks: {
      list: () => request<Paginated<Webhook>>('/developer/webhooks/').then((r) => r.results),
      create: (data: { label: string; url: string; secret?: string; events: string[] }) =>
        request<Webhook & { secret: string }>('/developer/webhooks/', {
          method: 'POST',
          body: JSON.stringify(data),
        }),
      remove: (id: number) =>
        request<void>(`/developer/webhooks/${id}/`, { method: 'DELETE' }),
    },
    events: () =>
      request<{ events: WebhookEvent[] }>('/developer/webhook-events/').then((r) => r.events),
  },

  assistant: {
    get: () => request<AISettings>('/assistant/settings/'),
    update: (data: Partial<{ provider: string; api_key: string }>) =>
      request<AISettings>('/assistant/settings/', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    chat: (messages: ChatMessage[]) =>
      request<ChatReply>('/assistant/chat/', {
        method: 'POST',
        body: JSON.stringify({ messages }),
      }),
    rate: (questionId: number, rating: 1 | -1 | 0) =>
      request<{ rating: number | null }>(`/assistant/questions/${questionId}/rate/`, {
        method: 'POST',
        body: JSON.stringify({ rating }),
      }),
    usage: () => request<AIUsage>('/assistant/usage/'),
    // Owner-only: turn the paid Pro tier on/off (adds a monthly platform fee, postpaid).
    togglePro: (enabled: boolean) =>
      request<AIUsage & { monthly_fee: string }>('/assistant/pro/', {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      }),
    // Saved, named chat threads (multi-conversation), private to each staff member.
    conversations: {
      list: () => request<Paginated<Conversation>>('/assistant/conversations/'),
      create: () =>
        request<ConversationDetail>('/assistant/conversations/', { method: 'POST', body: '{}' }),
      get: (id: number) => request<ConversationDetail>(`/assistant/conversations/${id}/`),
      rename: (id: number, title: string) =>
        request<Conversation>(`/assistant/conversations/${id}/`, {
          method: 'PATCH',
          body: JSON.stringify({ title }),
        }),
      remove: (id: number) =>
        request<null>(`/assistant/conversations/${id}/`, { method: 'DELETE' }),
      send: (id: number, content: string) =>
        request<SendResult>(`/assistant/conversations/${id}/messages/`, {
          method: 'POST',
          body: JSON.stringify({ content }),
        }),
    },
  },

  alerts: {
    get: () => request<OperatorAlertSettings>('/notifications/settings/alerts/'),
    update: (data: Partial<OperatorAlertSettings>) =>
      request<OperatorAlertSettings>('/notifications/settings/alerts/', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
  },

  domain: {
    get: () => request<DomainState>('/operator/domain/'),
    check: (slug: string) =>
      request<DomainCheck>(`/operator/domain/check/?slug=${encodeURIComponent(slug)}`),
    /** Moves the ISP AND re-pushes the captive portal to every router. */
    change: (slug: string) =>
      request<DomainState>('/operator/domain/change/', {
        method: 'POST',
        body: JSON.stringify({ slug }),
      }),
  },

  paymentGateways: {
    /** Every gateway an ISP can collect through, and where they stand with each. */
    get: () => request<PaymentGatewaysState>('/payments/gateways/'),

    /** Store credentials for a gateway. Secrets left blank keep their stored value. */
    configure: (gatewayId: string, credentials: Record<string, string>, activate = false) =>
      request<PaymentGatewaysState>(`/payments/gateways/${gatewayId}/`, {
        method: 'POST',
        body: JSON.stringify({ credentials, activate }),
      }),

    /** Make this the gateway subscribers pay through. One at a time. */
    activate: (gatewayId: string) =>
      request<PaymentGatewaysState>(`/payments/gateways/${gatewayId}/activate/`, {
        method: 'POST',
        body: '{}',
      }),

    /** Prove the credentials work by charging KSh 1 to the ISP's own phone — wrong keys
     *  fail SILENTLY in production, at a customer, so surface them now. */
    test: (gatewayId: string, phone: string) =>
      request<{ detail: string }>(`/payments/gateways/${gatewayId}/test/`, {
        method: 'POST',
        body: JSON.stringify({ phone }),
      }),
  },

  messaging: {
    /** Every gateway on this channel, and where this ISP stands with each. */
    providers: (channel: 'sms' | 'whatsapp') =>
      request<ProvidersResponse>(`/notifications/settings/${channel}/`),

    /** Save credentials for one gateway. Secrets left blank keep their stored value. */
    configure: (
      channel: 'sms' | 'whatsapp',
      providerId: string,
      credentials: Record<string, string>,
      activate = false
    ) =>
      request<{ providers: ProviderCard[]; active: string }>(
        `/notifications/settings/${channel}/${providerId}/`,
        { method: 'POST', body: JSON.stringify({ credentials, activate }) }
      ),

    /** Make a gateway the live one. Only one sends at a time. */
    activate: (channel: 'sms' | 'whatsapp', providerId: string) =>
      request<{ providers: ProviderCard[]; active: string }>(
        `/notifications/settings/${channel}/${providerId}/activate/`,
        { method: 'POST', body: '{}' }
      ),

    disconnect: (channel: 'sms' | 'whatsapp', providerId: string) =>
      request<{ providers: ProviderCard[]; active: string }>(
        `/notifications/settings/${channel}/${providerId}/disconnect/`,
        { method: 'DELETE' }
      ),

    email: {
      get: () => request<EmailSettings>('/notifications/settings/email/'),
      update: (data: EmailSettingsUpdate) =>
        request<EmailSettings>('/notifications/settings/email/', {
          method: 'PATCH',
          body: JSON.stringify(data),
        }),
    },

    /** Send a real message to yourself. Wrong credentials fail SILENTLY in production —
     *  this is how the ISP finds out now instead of via an angry customer. */
    test: (channel: 'sms' | 'email' | 'whatsapp', to: string) =>
      request<{ detail: string }>('/notifications/settings/test/', {
        method: 'POST',
        body: JSON.stringify({ channel, to }),
      }),
  },

  billing: {
    wallet: () => request<WalletSummary>('/billing/wallet/'),
    ledger: (query = '') => request<Paginated<ApiLedgerEntry>>(`/billing/ledger/${query}`),
    payouts: {
      list: (query = '') => request<Paginated<ApiPayout>>(`/billing/payouts/${query}`),
      /** Preview the transfer cost before committing (no money moves). The rail follows
       *  the verified settlement account, so no method is passed. */
      quote: (amount: string) =>
        request<PayoutQuote>(`/billing/payouts/quote/?amount=${encodeURIComponent(amount)}`),
      withdraw: (data: WithdrawPayload) =>
        request<ApiPayout>('/billing/payouts/withdraw/', { method: 'POST', body: JSON.stringify(data) }),
    },
  },

  reports: {
    revenue: (from: string, to: string) =>
      request<RevenueReport>(`/billing/reports/revenue/?from=${from}&to=${to}`),
    /** Cookie-authenticated same-origin download URL — used as an <a href>. */
    csvUrl: (kind: 'transactions' | 'pppoe-payments' | 'ledger', from: string, to: string) =>
      `${BASE}/api/v1/billing/reports/${kind}.csv?from=${from}&to=${to}`,
  },

  platform: {
    overview: () => request<PlatformOverview>('/platform/overview/'),
    reconciliation: () => request<Reconciliation>('/platform/reconciliation/'),
    tenants: {
      list: () => request<Paginated<ApiTenant>>('/platform/tenants/'),
      update: (id: number, data: Partial<ApiTenant>) =>
        request<ApiTenant>(`/platform/tenants/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
      approve: (id: number) =>
        request<{ status: string }>(`/platform/tenants/${id}/approve/`, { method: 'POST' }),
      suspend: (id: number) =>
        request<{ status: string }>(`/platform/tenants/${id}/suspend/`, { method: 'POST' }),
    },
    payouts: {
      list: (query = '') => request<Paginated<ApiPayout>>(`/billing/platform/payouts/${query}`),
      markPaid: (id: number, mpesa_reference: string) =>
        request<ApiPayout>(`/billing/platform/payouts/${id}/mark_paid/`, {
          method: 'POST',
          body: JSON.stringify({ mpesa_reference }),
        }),
      reject: (id: number, note: string) =>
        request<ApiPayout>(`/billing/platform/payouts/${id}/reject/`, {
          method: 'POST',
          body: JSON.stringify({ note }),
        }),
    },
  },

  plans: {
    list: () => request<Paginated<ApiPlan>>('/plans/'),
    create: (data: Partial<ApiPlan>) =>
      request<ApiPlan>('/plans/', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<ApiPlan>) =>
      request<ApiPlan>(`/plans/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
    remove: (id: number) => request<null>(`/plans/${id}/`, { method: 'DELETE' }),
  },

  transactions: {
    list: (query = '') =>
      request<Paginated<ApiTransaction>>(`/payments/transactions/${query}`),
    /** Search across hotspot + PPPoE payments by phone / M-Pesa code / account number. */
    search: (q: string) =>
      request<{ results: PaymentSearchResult[] }>(`/payments/search/?q=${encodeURIComponent(q)}`),
    /** The "paid but never connected" queue — paid (incl. reconciled) with no active session. */
    unconnected: () =>
      request<Paginated<ApiTransaction>>('/payments/transactions/?unconnected=1'),
    /** Reconnect a paid customer with a fresh full window (compensation). */
    reconnect: (id: number) =>
      request<ApiTransaction & { detail: string; new_expiry: string }>(
        `/payments/transactions/${id}/reconnect/`,
        { method: 'POST' }
      ),
  },

  campaigns: {
    list: () => request<Paginated<ApiCampaign>>('/notifications/campaigns/'),
    create: (data: { name: string; channel: string; audience: string; body: string; subject?: string }) =>
      request<ApiCampaign>('/notifications/campaigns/', { method: 'POST', body: JSON.stringify(data) }),
    audience: (channel = 'sms') =>
      request<{ all: number; active: number; expired: number }>(
        `/notifications/campaigns/audience/?channel=${channel}`
      ),
  },

  messages: {
    list: (query = '') => request<Paginated<ApiMessage>>(`/notifications/messages/${query}`),
  },

  subscribers: {
    list: (query = '') => request<Paginated<ApiSubscriber>>(`/subscribers/${query}`),
  },

  sessions: {
    list: (query = '') => request<Paginated<ApiSession>>(`/sessions/${query}`),
    suspend: (id: number) => request<{ detail: string }>(`/sessions/${id}/suspend/`, { method: 'POST' }),
  },

  // Everyone online now across ALL service types — powers the Active Users page.
  liveConnections: (type: 'all' | LiveServiceType = 'all') =>
    request<LiveConnectionsResponse>(`/live-connections/?type=${type}`),

  vouchers: {
    list: (query = '') => request<Paginated<ApiVoucher>>(`/vouchers/${query}`),
    generate: (data: { plan_id: number; count: number; prefix?: string }) =>
      request<ApiVoucher[]>('/vouchers/generate/', { method: 'POST', body: JSON.stringify(data) }),
    sendSms: (id: number, phone: string) =>
      request<{ detail: string }>(`/vouchers/${id}/send-sms/`, {
        method: 'POST',
        body: JSON.stringify({ phone }),
      }),
  },

  messageTemplates: {
    get: () => request<MessageTemplatesResponse>('/notifications/settings/templates/'),
    update: (data: { key: string; body?: string; is_enabled?: boolean }) =>
      request<MessageTemplatesResponse>('/notifications/settings/templates/', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
  },

  routers: {
    ...crud<ApiRouter>('/routers'),
    testConnection: (id: number) =>
      request<{ ok: boolean; detail?: string }>(`/routers/${id}/test_connection/`, { method: 'POST' }),
    setupScript: (id: number) =>
      request<{ script: string; enrolled: boolean; status: string }>(`/routers/${id}/setup_script/`),
    resync: (id: number) =>
      request<{ detail: string }>(`/routers/${id}/resync/`, { method: 'POST' }),
    deviceInfo: (id: number) => request<DeviceInfo>(`/routers/${id}/device_info/`),
    /** Read-only slow-speed diagnostics: CPU, MSS clamp, queues, throughput, oversubscription. */
    diagnose: (id: number) => request<RouterDiagnostics>(`/routers/${id}/diagnose/`),
    /** Recent CPU/mem/active-user samples + 24h peaks, for the load trend. */
    healthTrend: (id: number) => request<RouterHealthTrend>(`/routers/${id}/health-trend/`),
    /** Re-assert the PPPoE TCP-MSS clamp now (idempotent), instead of waiting for the nightly heal. */
    healMssClamp: (id: number) =>
      request<{ detail: string }>(`/routers/${id}/heal-mss-clamp/`, { method: 'POST' }),
  },

  tickets: {
    ...crud<ApiTicket>('/ops/tickets'),
    /** The technicians a ticket can be assigned to (tickets.assign). */
    assignees: () => request<TicketAssignee[]>('/ops/tickets/assignees/'),
  },
  leads: crud<ApiLead>('/ops/leads'),
  expenses: {
    ...crud<ApiExpense>('/ops/expenses'),
    /** What this ISP paid WIFI.OS (fees + SMS) for a month — the auto expense line. */
    platformFees: (month?: string) =>
      request<PlatformFees>(`/ops/platform-fees/${month ? `?month=${month}` : ''}`),
    /** Server-side month total — correct regardless of pagination. */
    summary: () => request<{ month_total: string }>('/ops/expenses/summary/'),
  },
  equipment: crud<ApiEquipment>('/ops/equipment'),

  pppoe: {
    plans: crud<PppoePlan>('/pppoe/plans'),
    clients: {
      ...crud<PppoeClient>('/pppoe/clients'),
      // create/update accept `force` — the sector-capacity gate returns 409 unless the ISP
      // chooses to over-subscribe on purpose (force: true), which the server then audits.
      create: (data: Partial<PppoeClient> & { force?: boolean }) =>
        request<PppoeClient>('/pppoe/clients/', { method: 'POST', body: JSON.stringify(data) }),
      update: (id: number, data: Partial<PppoeClient> & { force?: boolean }) =>
        request<PppoeClient>(`/pppoe/clients/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
      provision: (id: number) =>
        request<PppoeClient>(`/pppoe/clients/${id}/provision/`, { method: 'POST' }),
      suspend: (id: number) =>
        request<{ detail: string }>(`/pppoe/clients/${id}/suspend/`, { method: 'POST' }),
      restore: (id: number) =>
        request<{ detail: string }>(`/pppoe/clients/${id}/restore/`, { method: 'POST' }),
      // Record a payment the customer made OUTSIDE the platform (cash, M-Pesa to the ISP's own
      // number, bank). Settles their bill and reconnects them like a paybill payment, but the
      // platform never held this money so it is not credited to the withdrawable wallet.
      recordPayment: (id: number, data: { amount: string; method: OffSystemMethod; note?: string }) =>
        request<{ detail: string; status: string; balance: string }>(
          `/pppoe/clients/${id}/record-payment/`,
          { method: 'POST', body: JSON.stringify(data) },
        ),
      liveStatus: (id: number) =>
        request<{ online: boolean }>(`/pppoe/clients/${id}/live_status/`),
      // Hybrid reset: pass a password to set it, or omit to have the server generate one.
      // Returns the new credentials so the ISP can read them back to the installer.
      resetPassword: (id: number, password?: string) =>
        request<{ pppoe_username: string; pppoe_password: string }>(
          `/pppoe/clients/${id}/reset_password/`,
          { method: 'POST', body: JSON.stringify(password ? { password } : {}) },
        ),
      // Adopt an ISP's pre-existing router PPPoE users. Preview first (what's new / already
      // managed / suggested plan), then import the chosen rows — DB-only, never disrupts them.
      importPreview: (router: number) =>
        request<PppoeImportRow[]>('/pppoe/clients/import-preview/', {
          method: 'POST', body: JSON.stringify({ router }),
        }),
      // Migrating in from another billing system: the file carries the PEOPLE (names,
      // phones, billing days) that a router never knows about.
      importCsvPreview: (csv: string) =>
        request<PppoeCsvPreview>('/pppoe/clients/import-csv-preview/', {
          method: 'POST', body: JSON.stringify({ csv }),
        }),
      importCsv: (csv: string, router: number, planMap: Record<string, number>) =>
        request<PppoeImportResult>('/pppoe/clients/import-csv/', {
          method: 'POST',
          body: JSON.stringify({ csv, router, plan_map: planMap }),
        }),
      importRun: (router: number, items: PppoeImportItem[]) =>
        request<PppoeImportResult>('/pppoe/clients/import/', {
          method: 'POST', body: JSON.stringify({ router, items }),
        }),
      // A CSV backup of every client. Cookie-auth GET, so a plain download link works.
      // Credentials are opt-in and owner-only on the server: one click should not
      // quietly hand over every customer's PPPoE password.
      exportUrl: (includeCredentials = false) =>
        `${BASE}/api/v1/pppoe/clients/export/${includeCredentials ? '?include_credentials=true' : ''}`,
    },
    usageSummary: () => request<PppoeUsageSummary>('/pppoe/usage-summary/'),
    churnSummary: (months = 6) =>
      request<PppoeChurnSummary>(`/pppoe/churn-summary/?months=${months}`),
    invoices: {
      list: (query = '') => request<Paginated<PppoeInvoice>>(`/pppoe/invoices/${query}`),
    },
    towers: crud<Tower>('/pppoe/towers'),
    accessPoints: crud<AccessPoint>('/pppoe/access-points'),
  },
};
