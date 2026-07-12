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
      resp.status === 401 ? 'Wrong phone number or password.' : `Login failed (HTTP ${resp.status})`
    );
  }
  // Nothing to store — the cookies are already set.
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/api/v1/auth/logout/`, { ...withCookies, method: 'POST' }).catch(() => {});
}

async function tryRefresh(): Promise<boolean> {
  const resp = await fetch(`${BASE}/api/v1/auth/refresh/`, { ...withCookies, method: 'POST' });
  return resp.ok;
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

export type Role =
  | 'platform_owner'
  | 'platform_support'
  | 'tenant_owner'
  | 'tenant_manager'
  | 'tenant_support';

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
  method: 'paybill' | 'bank' | null;
  destination: string | null;
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

export interface MeOperator {
  id: number;
  name: string;
  slug: string;
  status: 'pending' | 'active' | 'suspended';
  is_platform_owned: boolean;
  /** THE MONEY GATE. False => this ISP cannot collect, provision or withdraw. */
  can_transact: boolean;
  /** Why not, and what to do about it. Empty when they're live. */
  go_live_blockers: GoLiveBlocker[];
}

export interface Me {
  phone: string;
  name: string;
  is_staff: boolean;
  role: Role;
  is_platform_staff: boolean;
  is_read_only: boolean;
  can_manage_money: boolean;
  /** The user's home ISP (null for platform-only staff). */
  operator: MeOperator | null;
  /** The ISP this session is currently acting for (platform staff can switch). */
  acting_operator: MeOperator | null;
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

export interface WithdrawPayload {
  amount: string;
  method: 'mpesa' | 'bank';
  phone?: string;
  bank_name?: string;
  bank_account_number?: string;
  bank_account_name?: string;
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

export interface OperatorSettings {
  name: string;
  slug: string;
  status: string;
  owner_name: string;
  contact_phone: string;
  contact_email: string;
  commission_rate: string;
}

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

export interface PppoeClient {
  id: number;
  account_number: string;
  full_name: string;
  phone: string;
  email: string;
  physical_address: string;
  plan: number;
  plan_name: string;
  router: number;
  pppoe_username: string;
  pppoe_password: string;
  static_ip: string | null;
  delivery_method: 'fibre' | 'ethernet' | 'wireless_ptp' | 'wireless_ptmp';
  access_point: number | null;
  cpe_equipment: number | null;
  status: 'pending_install' | 'active' | 'suspended' | 'disabled';
  billing_day: number;
  balance: string;
  next_due_date: string | null;
  installed_at: string | null;
  notes: string;
  created_at: string;
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
  /** Also the "am I signed in / which ISP am I in?" probe — only the server knows. */
  me: () => request<Me>('/me/'),

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

  billing: {
    wallet: () => request<WalletSummary>('/billing/wallet/'),
    ledger: () => request<Paginated<ApiLedgerEntry>>('/billing/ledger/'),
    payouts: {
      list: () => request<Paginated<ApiPayout>>('/billing/payouts/'),
      withdraw: (data: WithdrawPayload) =>
        request<ApiPayout>('/billing/payouts/withdraw/', { method: 'POST', body: JSON.stringify(data) }),
    },
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
    setupScript: (id: number) =>
      request<{ script: string; enrolled: boolean; status: string }>(`/routers/${id}/setup_script/`),
    resync: (id: number) =>
      request<{ detail: string }>(`/routers/${id}/resync/`, { method: 'POST' }),
    deviceInfo: (id: number) => request<DeviceInfo>(`/routers/${id}/device_info/`),
  },

  tickets: crud<ApiTicket>('/ops/tickets'),
  leads: crud<ApiLead>('/ops/leads'),
  expenses: crud<ApiExpense>('/ops/expenses'),
  equipment: crud<ApiEquipment>('/ops/equipment'),

  pppoe: {
    plans: crud<PppoePlan>('/pppoe/plans'),
    clients: {
      ...crud<PppoeClient>('/pppoe/clients'),
      provision: (id: number) =>
        request<PppoeClient>(`/pppoe/clients/${id}/provision/`, { method: 'POST' }),
      suspend: (id: number) =>
        request<{ detail: string }>(`/pppoe/clients/${id}/suspend/`, { method: 'POST' }),
      restore: (id: number) =>
        request<{ detail: string }>(`/pppoe/clients/${id}/restore/`, { method: 'POST' }),
      liveStatus: (id: number) =>
        request<{ online: boolean }>(`/pppoe/clients/${id}/live_status/`),
    },
    invoices: {
      list: (query = '') => request<Paginated<PppoeInvoice>>(`/pppoe/invoices/${query}`),
    },
    towers: crud<Tower>('/pppoe/towers'),
    accessPoints: crud<AccessPoint>('/pppoe/access-points'),
  },
};
