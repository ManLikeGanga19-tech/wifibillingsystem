/**
 * Admin API client: JWT auth (access + refresh with silent renewal) and typed
 * endpoints for the wired screens. All calls go through the Vite dev proxy
 * (/api -> Django) in dev; VITE_API_BASE_URL overrides in production builds.
 */

const BASE = (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE_URL ?? '';
const TOKEN_KEY = 'wifios_admin_jwt';

// ---- auth -------------------------------------------------------------

interface TokenPair {
  access: string;
  refresh: string;
}

function getTokens(): TokenPair | null {
  const raw = localStorage.getItem(TOKEN_KEY);
  return raw ? (JSON.parse(raw) as TokenPair) : null;
}

function setTokens(tokens: TokenPair | null) {
  if (tokens) localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
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
    throw new Error(resp.status === 401 ? 'Wrong phone number or password.' : `Login failed (HTTP ${resp.status})`);
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
    window.location.reload(); // back to the login gate
  }
  const body = resp.status === 204 ? null : await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, body);
  return body as T;
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
}

export interface ApiCampaign {
  id: number;
  name: string;
  channel: 'sms' | 'whatsapp';
  audience: 'all' | 'active' | 'expired';
  body: string;
  status: 'queued' | 'sending' | 'done';
  total_recipients: number;
  sent_count: number;
  failed_count: number;
  created_at: string;
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
    active_sessions: number;
    sessions_expiring_1h: number;
    total_subscribers: number;
    new_subscribers_7d: number;
    arpu_month: number | null;
    unused_vouchers: number;
    vouchers_redeemed_7d: number;
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

interface Paginated<T> {
  count: number;
  results: T[];
}

// ---- endpoints ----------------------------------------------------------

export const api = {
  stats: () => request<DashboardStats>('/stats/'),

  plans: {
    list: () => request<Paginated<ApiPlan>>('/plans/'),
    create: (data: Partial<ApiPlan>) =>
      request<ApiPlan>('/plans/', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<ApiPlan>) =>
      request<ApiPlan>(`/plans/${id}/`, { method: 'PATCH', body: JSON.stringify(data) }),
    remove: (id: number) => request<null>(`/plans/${id}/`, { method: 'DELETE' }),
  },

  transactions: {
    list: (status?: string) =>
      request<Paginated<ApiTransaction>>(`/payments/transactions/${status ? `?status=${status}` : ''}`),
  },

  campaigns: {
    list: () => request<Paginated<ApiCampaign>>('/notifications/campaigns/'),
    create: (data: { name: string; channel: string; audience: string; body: string }) =>
      request<ApiCampaign>('/notifications/campaigns/', { method: 'POST', body: JSON.stringify(data) }),
  },

  subscribers: {
    list: () => request<Paginated<ApiSubscriber>>('/subscribers/'),
  },
};
