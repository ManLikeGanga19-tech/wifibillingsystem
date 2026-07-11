/**
 * Platform Control API client.
 *
 * Talks to the same Django backend as the ISP console, but only ever calls
 * /platform/* endpoints — this app has no business reading a single ISP's data
 * directly. The one exception is impersonation, which is an explicit, audited,
 * time-boxed grant (see startImpersonation) rather than a silent header flip.
 */

const BASE = (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE_URL ?? '';
const TOKEN_KEY = 'wifios_platform_jwt';

interface TokenPair {
  access: string;
  refresh: string;
}

function getTokens(): TokenPair | null {
  const raw = localStorage.getItem(TOKEN_KEY);
  return raw ? (JSON.parse(raw) as TokenPair) : null;
}
function setTokens(t: TokenPair | null) {
  if (t) localStorage.setItem(TOKEN_KEY, JSON.stringify(t));
  else localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getTokens() !== null;
}
export function logout() {
  setTokens(null);
}

export async function login(phone: string, password: string): Promise<void> {
  const resp = await fetch(`${BASE}/api/v1/auth/token/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, password }),
  });
  if (!resp.ok) {
    throw new Error(
      resp.status === 401 ? 'Wrong phone number or password.' : `Login failed (HTTP ${resp.status})`
    );
  }
  setTokens((await resp.json()) as TokenPair);
}

async function tryRefresh(): Promise<boolean> {
  const tokens = getTokens();
  if (!tokens) return false;
  const resp = await fetch(`${BASE}/api/v1/auth/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: tokens.refresh }),
  });
  if (!resp.ok) {
    setTokens(null);
    return false;
  }
  const data = (await resp.json()) as { access: string };
  setTokens({ ...tokens, access: data.access });
  return true;
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

async function request<T>(path: string, init?: RequestInit, retried = false): Promise<T> {
  const tokens = getTokens();
  const resp = await fetch(`${BASE}/api/v1${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(tokens ? { Authorization: `Bearer ${tokens.access}` } : {}),
      ...init?.headers,
    },
  });
  if (resp.status === 401 && !retried && (await tryRefresh())) {
    return request<T>(path, init, true);
  }
  if (resp.status === 401) {
    setTokens(null);
    window.location.reload();
  }
  if (!resp.ok) throw new ApiError(resp.status, await resp.json().catch(() => null));
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

const get = <T,>(p: string) => request<T>(p);
const post = <T,>(p: string, body?: unknown) =>
  request<T>(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
const patch = <T,>(p: string, body: unknown) =>
  request<T>(p, { method: 'PATCH', body: JSON.stringify(body) });

// ---- types ------------------------------------------------------------------

type Money = string | number;

export interface Page<T> {
  count: number;
  results: T[];
}

export interface Me {
  id: number;
  name: string;
  phone: string;
  role: string;
  is_platform_staff: boolean;
  is_read_only: boolean;
  operator: { slug: string; name: string } | null;
}

export interface Kpis {
  scope: 'all_isps';
  mrr: Money;
  arr: Money;
  earnings_month: Money;
  revenue_by_stream: Record<string, Money>;
  transaction_costs_month: Money;
  net_margin_month: Money;
  margin_pct: number;
  gross_volume_month: Money;
  float_held: Money;
  tenants_active: number;
  tenants_total: number;
  new_tenants_30d: number;
  routers_online: number;
  routers_total: number;
  active_sessions: number;
  alerts: {
    pending_approvals: number;
    trials_expiring_7d: number;
    payouts_pending: number;
    payouts_stale_2d: number;
    unmatched_payments: number;
    routers_offline: number;
  };
}

export interface SeriesPoint {
  date: string;
  gross_volume: Money;
  earnings: Money;
  transaction_costs: Money;
  net_margin: Money;
  new_tenants: number;
}

export interface PnlRow {
  id: number;
  slug: string;
  name: string;
  status: string;
  is_platform_owned: boolean;
  in_trial: boolean;
  gross_collected: Money;
  revenue: Money;
  transaction_costs: Money;
  net_margin: Money;
  margin_pct: number;
  wallet_balance: Money;
  pppoe_users: number;
}

export interface Pnl {
  totals: { revenue: Money; transaction_costs: Money; net_margin: Money };
  tenants: PnlRow[];
}

export interface Tenant {
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

export interface TenantDetail {
  tenant: Tenant;
  in_trial: boolean;
  finance: {
    gross_collected: Money;
    platform_revenue: Money;
    wallet_balance: Money;
    payouts_paid: Money;
    payouts_pending: Money;
  };
  usage: {
    pppoe_billable: number;
    pppoe_total: number;
    routers_total: number;
    routers_online: number;
    transactions: number;
    staff: number;
  };
  recent_activity: AuditRow[];
}

export interface AuditRow {
  id: number;
  action: string;
  actor_name: string;
  actor_phone: string;
  operator_slug: string;
  operator_name: string;
  target_type: string;
  target_id: string;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

export interface Grant {
  id: number;
  actor_name: string;
  operator_slug: string;
  operator_name: string;
  reason: string;
  started_at: string;
  expires_at: string;
  ended_at: string | null;
  ip_address: string | null;
  is_live: boolean;
}

export interface SearchResults {
  q: string;
  total: number;
  results: {
    tenants?: { id: number; slug: string; name: string; status: string }[];
    transactions?: {
      id: number;
      tenant: string;
      phone: string;
      amount: Money;
      status: string;
      mpesa_receipt: string;
      created_at: string;
    }[];
    c2b_payments?: {
      id: number;
      tenant: string;
      trans_id: string;
      bill_ref: string;
      msisdn: string;
      amount: Money;
      status: string;
      received_at: string;
    }[];
    pppoe_clients?: {
      id: number;
      tenant: string;
      account_number: string;
      full_name: string;
      phone: string;
      status: string;
      plan: string;
    }[];
    subscribers?: { id: number; tenant: string; phone: string; name: string }[];
    routers?: { id: number; tenant: string; name: string; host: string; status: string }[];
  };
}

export interface Payout {
  id: number;
  operator_name: string;
  amount: Money;
  method: string;
  destination: string;
  status: string;
  mpesa_reference: string;
  created_at: string;
}

// ---- endpoints ---------------------------------------------------------------

export const api = {
  me: () => get<Me>('/auth/me/'),

  kpis: () => get<Kpis>('/platform/kpis/'),
  timeseries: (days: number) =>
    get<{ days: number; series: SeriesPoint[] }>(`/platform/timeseries/?days=${days}`),
  pnl: () => get<Pnl>('/platform/tenant-pnl/'),
  search: (q: string) => get<SearchResults>(`/platform/search/?q=${encodeURIComponent(q)}`),

  tenants: {
    list: () => get<Page<Tenant>>('/platform/tenants/'),
    detail: (id: number) => get<TenantDetail>(`/platform/tenants/${id}/detail_stats/`),
    update: (id: number, body: Partial<Tenant>) => patch<Tenant>(`/platform/tenants/${id}/`, body),
    approve: (id: number) => post<unknown>(`/platform/tenants/${id}/approve/`),
    suspend: (id: number) => post<unknown>(`/platform/tenants/${id}/suspend/`),
    chargeSetup: (id: number) =>
      post<{ charged: boolean; detail: string }>(`/platform/tenants/${id}/charge-setup/`),
  },

  audit: {
    list: (params: { tenant?: string; action?: string } = {}) => {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v) as [string, string][]
      ).toString();
      return get<Page<AuditRow>>(`/platform/audit/${qs ? `?${qs}` : ''}`);
    },
    actions: () => get<string[]>('/platform/audit/actions/'),
  },

  impersonation: {
    history: (live?: boolean) =>
      get<Page<Grant>>(`/platform/impersonation/${live ? '?live=true' : ''}`),
    /** Opens an AUDITED, time-boxed door into one ISP's console. Reason required. */
    start: (tenant: string, reason: string, minutes = 60) =>
      post<Grant>('/platform/impersonation/start/', { tenant, reason, minutes }),
    end: (tenant?: string) => post<{ ended: number }>('/platform/impersonation/end/', { tenant }),
  },

  payouts: {
    list: (status = '') =>
      get<Page<Payout>>(`/billing/platform/payouts/${status ? `?status=${status}` : ''}`),
    /** We pay the ISP manually (M-Pesa / bank), then record the reference here. */
    markPaid: (id: number, mpesa_reference: string) =>
      post<Payout>(`/billing/platform/payouts/${id}/mark_paid/`, { mpesa_reference }),
    /** Rejecting returns the held funds to the ISP's wallet. */
    reject: (id: number, note: string) =>
      post<Payout>(`/billing/platform/payouts/${id}/reject/`, { note }),
  },
};

// ---- formatting --------------------------------------------------------------

export const ksh = (v: Money | undefined | null, compact = false): string => {
  const n = Number(v ?? 0);
  if (compact && Math.abs(n) >= 1000) {
    return `KSh ${new Intl.NumberFormat('en-KE', {
      notation: 'compact',
      maximumFractionDigits: 1,
    }).format(n)}`;
  }
  return `KSh ${new Intl.NumberFormat('en-KE', { maximumFractionDigits: 0 }).format(n)}`;
};

export const num = (v: number | undefined | null): string =>
  new Intl.NumberFormat('en-KE').format(Number(v ?? 0));

export const dt = (iso: string | null): string =>
  iso ? new Date(iso).toLocaleString('en-KE', { dateStyle: 'medium', timeStyle: 'short' }) : '—';

export const day = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-KE', { month: 'short', day: 'numeric' });
