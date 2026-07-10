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
  management_host: string;
  api_port: number;
  username: string;
  use_tls: boolean;
  verify_tls: boolean;
  provisioning_backend: 'mikrotik_rest' | 'dummy';
  status: 'online' | 'offline' | 'unknown';
  last_seen_at: string | null;
  is_active: boolean;
}

export interface ApiTicket {
  id: number;
  subject: string;
  description: string;
  subscriber: number | null;
  subscriber_phone: string;
  status: 'open' | 'in_progress' | 'resolved' | 'closed';
  priority: 'low' | 'normal' | 'high' | 'urgent';
  assigned_to: number | null;
  created_at: string;
  resolved_at: string | null;
}

export interface ApiLead {
  id: number;
  name: string;
  phone: string;
  location: string;
  source: string;
  status: 'new' | 'contacted' | 'converted' | 'lost';
  notes: string;
  created_at: string;
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

export interface Me {
  phone: string;
  name: string;
  is_staff: boolean;
  is_platform_admin: boolean;
  operator: {
    id: number;
    name: string;
    slug: string;
    status: 'pending' | 'active' | 'suspended';
  } | null;
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

export interface ApiLedgerEntry {
  id: number;
  entry_type: 'sale' | 'commission' | 'base_fee' | 'pppoe_fee' | 'payout' | 'adjustment';
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
  phone: string;
  status: 'requested' | 'paid' | 'rejected';
  mpesa_reference: string;
  note: string;
  created_at: string;
  processed_at: string | null;
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
  approved_at: string | null;
  created_at: string;
  router_count: number;
  staff_count: number;
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

export const api = {
  stats: () => request<DashboardStats>('/stats/'),
  navCounts: () => request<NavCounts>('/nav/'),
  me: () => request<Me>('/me/'),

  operatorSettings: {
    get: () => request<OperatorSettings>('/operator/settings/'),
    update: (data: Record<string, string>) =>
      request<OperatorSettings>('/operator/settings/', { method: 'PATCH', body: JSON.stringify(data) }),
  },

  billing: {
    wallet: () => request<WalletSummary>('/billing/wallet/'),
    ledger: () => request<Paginated<ApiLedgerEntry>>('/billing/ledger/'),
    payouts: {
      list: () => request<Paginated<ApiPayout>>('/billing/payouts/'),
      withdraw: (data: { amount: string; phone: string }) =>
        request<ApiPayout>('/billing/payouts/withdraw/', { method: 'POST', body: JSON.stringify(data) }),
    },
  },

  platform: {
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
    list: (status?: string) =>
      request<Paginated<ApiTransaction>>(`/payments/transactions/${status ? `?status=${status}` : ''}`),
  },

  campaigns: {
    list: () => request<Paginated<ApiCampaign>>('/notifications/campaigns/'),
    create: (data: { name: string; channel: string; audience: string; body: string; subject?: string }) =>
      request<ApiCampaign>('/notifications/campaigns/', { method: 'POST', body: JSON.stringify(data) }),
  },

  messages: {
    list: (query = '') => request<Paginated<ApiMessage>>(`/notifications/messages/${query}`),
  },

  subscribers: {
    list: () => request<Paginated<ApiSubscriber>>('/subscribers/'),
  },

  sessions: {
    list: (query = '') => request<Paginated<ApiSession>>(`/sessions/${query}`),
    suspend: (id: number) => request<{ detail: string }>(`/sessions/${id}/suspend/`, { method: 'POST' }),
  },

  vouchers: {
    list: (query = '') => request<Paginated<ApiVoucher>>(`/vouchers/${query}`),
    generate: (data: { plan_id: number; count: number; prefix?: string }) =>
      request<ApiVoucher[]>('/vouchers/generate/', { method: 'POST', body: JSON.stringify(data) }),
  },

  routers: {
    ...crud<ApiRouter>('/routers'),
    testConnection: (id: number) =>
      request<{ ok: boolean; detail?: string }>(`/routers/${id}/test_connection/`, { method: 'POST' }),
  },

  tickets: crud<ApiTicket>('/ops/tickets'),
  leads: crud<ApiLead>('/ops/leads'),
  expenses: crud<ApiExpense>('/ops/expenses'),
  equipment: crud<ApiEquipment>('/ops/equipment'),
};
