/**
 * Platform Control API client.
 *
 * Talks to the same Django backend as the ISP console, but only ever calls
 * /platform/* endpoints — this app has no business reading a single ISP's data
 * directly. The one exception is impersonation, which is an explicit, audited,
 * time-boxed grant rather than a silent header flip.
 *
 * NO BROWSER STORAGE. Auth lives in server-set httpOnly cookies (see auth.ts).
 */

import { request } from './auth';

export { ApiError, login, logout } from './auth';

const get = <T,>(p: string) => request<T>(p);
const post = <T,>(p: string, body?: unknown) =>
  request<T>(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
const patch = <T,>(p: string, body: unknown) =>
  request<T>(p, { method: 'PATCH', body: JSON.stringify(body) });
const del = (p: string) => request<void>(p, { method: 'DELETE' });

// ---- types ------------------------------------------------------------------

type Money = string | number;

/** The platform (cross-tenant) AI key + platform-wide rate limit. */
export interface PlatformAISettings {
  provider: 'claude' | 'openai';
  has_key: boolean;
  key_preview: string;
  enabled: boolean;
  rate_limit_per_min: number;
  env_fallback_available: boolean;
}
export interface PlatformAISettingsInput {
  provider: 'claude' | 'openai';
  api_key: string;
  enabled: boolean;
  rate_limit_per_min: number;
}
/** The docs-gaps report — cross-tenant, anonymised assistant analytics. */
export interface DocsGaps {
  days: number;
  total_questions: number;
  grounded: number;
  unanswered: number;
  grounded_rate: number | null;
  top_topics: { topic: string; count: number; answered: number }[];
  gaps: { topic: string; count: number }[];
  thumbs_down: { topic: string; count: number }[];
  ai_cost_kes: string;
  pro_revenue_kes: string;
  ai_margin_kes: string;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
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

export interface MrrMonth {
  month: string; // "YYYY-MM"
  mrr: Money;
  new: Money;
  expansion: Money;
  contraction: Money;
  churned: Money;
  net: Money;
  new_tenants: number; // MRR-based: ISPs that started paying this month
  // Precise, status-based tenant counts — from real activation/suspension events, not the
  // MRR heuristic, so a billing-timing gap no longer masks as a lost ISP.
  active_tenants: number; // live at the start of the month (the churn denominator)
  activated_tenants: number;
  churned_tenants: number;
  tenant_churn_rate: number | null;
}
export interface MrrMover {
  operator: number;
  name: string;
  delta: Money;
  mrr: Money;
  bucket: 'new' | 'expansion' | 'contraction' | 'churned';
}
export interface MrrMovement {
  as_of: string;
  months: MrrMonth[];
  movers: MrrMover[];
}
export interface FunnelStage {
  key: string;
  label: string;
  count: number;
  pct: number | null; // of cohort
  drop_from_prev: number;
}
export interface OnboardingFunnel {
  as_of: string;
  window_days: number | null; // null = all-time
  cohort_size: number;
  stages: FunnelStage[];
  median_days_to_activate: number | null;
  median_days_to_first_payment: number | null;
  stuck: { pending_over_7d: number; activated_no_payment_over_14d: number };
}
export interface RetentionCell {
  offset: number; // months since signup
  retained: number;
  pct: number | null;
}
export interface RetentionCohort {
  cohort: string; // "YYYY-MM" signup month
  size: number;
  cells: RetentionCell[];
}
export interface CohortRetention {
  as_of: string;
  months: number;
  cohorts: RetentionCohort[];
}
export interface Broadcast {
  id: number;
  title: string;
  body: string;
  level: 'info' | 'warning' | 'critical';
  dismissable: boolean;
  is_active: boolean;
  starts_at: string;
  ends_at: string | null;
  created_at: string;
  is_live: boolean;
}
export type BroadcastDraft = {
  title: string;
  body: string;
  level: Broadcast['level'];
  dismissable: boolean;
  ends_at?: string | null;
};
export interface RiskFinding {
  operator: number;
  name: string;
  slug: string;
  signal:
    | 'collection_spike'
    | 'duplicate_identity'
    | 'reactivation_cycling'
    | 'large_payout'
    | 'offboarding_bad_debt';
  severity: 'high' | 'medium' | 'low';
  headline: string;
  detail: Record<string, unknown>;
}
export interface RiskSignals {
  as_of: string;
  counts: { high: number; medium: number; low: number };
  findings: RiskFinding[];
}

export interface UnmatchedSuggestion {
  client_id: number;
  account_number: string;
  full_name: string;
  operator: string;
  confidence: number;
  reason: string;
}

export interface UnmatchedPayment {
  id: number;
  trans_id: string;
  typed_account: string;
  amount: Money;
  paid_from: string;
  payer_name: string;
  received_at: string;
  suggestions: UnmatchedSuggestion[];
}

/** The one-time credentials returned when you provision a tenant by hand. */
export interface ProvisionResult {
  slug: string;
  name?: string;
  console_url: string;
  owner_phone: string;
  owner_name?: string;
  temp_password: string;
  status?: string;
  detail?: string;
}

export interface Tenant {
  id: number;
  name: string;
  slug: string;
  status: 'pending' | 'active' | 'suspended';
  is_active: boolean; // false = hard-killed (e.g. offboarding completed)
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
  offboarding: OffboardingInfo | null;
}

export interface OffboardingInfo {
  id: number;
  reason: string;
  grace_until: string;
  in_grace: boolean;
  snapshot_withdrawable: string; // + = we owe them
  snapshot_owed: string; // + = they owe us
  initiated_at: string;
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

export type HealthState = 'ok' | 'warn' | 'crit';

export interface HealthCheck {
  key: string;
  label: string;
  state: HealthState;
  value: number;
  detail: string;
}

export interface Health {
  status: HealthState;
  checked_at: string;
  checks: HealthCheck[];
  fleet: {
    total: number;
    online: number;
    offline: number;
    pending: number;
    unknown: number;
    needs_reonboarding: number;
    stale: number;
  };
  workers: { reachable: boolean; count: number; names: string[] };
  money: {
    stuck_payments: number;
    unmatched_payments: number;
    unmatched_value: Money;
    undelivered_service: number;
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
  /** Also the "am I signed in?" probe — only the server can answer that now. */
  me: () => get<Me>('/me/'),

  kpis: () => get<Kpis>('/platform/kpis/'),
  health: () => get<Health>('/platform/health/'),
  timeseries: (days: number) =>
    get<{ days: number; series: SeriesPoint[] }>(`/platform/timeseries/?days=${days}`),
  pnl: () => get<Pnl>('/platform/tenant-pnl/'),
  mrrMovement: (months: number) => get<MrrMovement>(`/platform/mrr-movement/?months=${months}`),
  onboardingFunnel: (days: number) =>
    get<OnboardingFunnel>(`/platform/onboarding-funnel/?days=${days}`),
  cohortRetention: (months: number) =>
    get<CohortRetention>(`/platform/cohort-retention/?months=${months}`),
  risk: () => get<RiskSignals>('/platform/risk/'),

  /** Broadcasts shown across every ISP console. Owner-only for writes. */
  broadcasts: {
    list: () => get<Page<Broadcast> | Broadcast[]>('/platform/broadcasts/'),
    create: (body: BroadcastDraft) => post<Broadcast>('/platform/broadcasts/', body),
    update: (id: number, body: Partial<Broadcast>) =>
      patch<Broadcast>(`/platform/broadcasts/${id}/`, body),
    remove: (id: number) => del(`/platform/broadcasts/${id}/`),
  },
  search: (q: string) => get<SearchResults>(`/platform/search/?q=${encodeURIComponent(q)}`),

  /** The unmatched-payments queue: money that landed on a mistyped account number. */
  unmatched: {
    list: () => get<{ count: number; results: UnmatchedPayment[] }>('/payments/platform/unmatched/'),
    resolve: (id: number, clientId: number) =>
      post<{ detail: string; status: string }>(`/payments/platform/unmatched/${id}/resolve/`, {
        client_id: clientId,
      }),
  },

  tenants: {
    list: (page = 1) => get<Page<Tenant>>(`/platform/tenants/?page=${page}`),
    /** Hand-onboard an ISP (skip the marketing signup wizard). Returns the owner's login,
     *  shown once so you can pass it on yourself. */
    provision: (body: { name: string; slug: string; owner_phone: string; owner_name: string }) =>
      post<ProvisionResult>('/platform/tenants/provision/', body),
    /** One click stands up (or refreshes) the read-only demo tenant. */
    createDemo: () => post<ProvisionResult>('/platform/tenants/create-demo/', {}),
    /** Credit (+) or debit (-) a tenant's wallet with an audited reason. Owner-only. */
    adjust: (id: number, amount: string, reason: string) =>
      post<{ detail: string; amount: string }>(`/platform/tenants/${id}/adjust/`, { amount, reason }),
    detail: (id: number) => get<TenantDetail>(`/platform/tenants/${id}/detail_stats/`),
    update: (id: number, body: Partial<Tenant>) => patch<Tenant>(`/platform/tenants/${id}/`, body),
    approve: (id: number) => post<unknown>(`/platform/tenants/${id}/approve/`),
    /** The last resort — a full lockout, always a person's decision. `reason` is recorded
     *  and shown to the ISP (so a non-payer is told to settle, not left guessing). */
    suspend: (id: number, reason: string) =>
      post<unknown>(`/platform/tenants/${id}/suspend/`, { reason }),
    restore: (id: number) => post<unknown>(`/platform/tenants/${id}/restore/`),
    chargeSetup: (id: number) =>
      post<{ charged: boolean; detail: string }>(`/platform/tenants/${id}/charge-setup/`),
    /** Begin offboarding: freeze the console + open a reversible grace window. Owner-only. */
    offboard: (id: number, reason: string) =>
      post<{ detail: string; grace_until: string; snapshot_withdrawable: string; snapshot_owed: string }>(
        `/platform/tenants/${id}/offboard/`, { reason }),
    /** Reinstate a tenant still in its grace window. */
    offboardAbort: (id: number) => post<{ detail: string }>(`/platform/tenants/${id}/offboard-abort/`),
    /** Terminal: tear every subscriber off the router + CANCELLED. `force` skips the grace.
     *  Returns the final settlement — fees recovered from held balance, net paid to the ISP,
     *  and any residual bad debt. */
    offboardComplete: (id: number, force: boolean) =>
      post<{
        detail: string;
        subscribers_torn_down: number;
        fees_recovered: string;
        net_settlement: string;
        residual_owed: string;
      }>(`/platform/tenants/${id}/offboard-complete/`, { force }),
    /** A portable JSON snapshot of the tenant's own data (owner-only; contains PII). */
    exportData: (id: number) => get<Record<string, unknown>>(`/platform/tenants/${id}/export/`),
    /** THE LOST PHONE. Clears an ISP owner's authenticator so they can enrol a new one.
     *  Owner-only, audited, emails them, and freezes their withdrawals for 24h — this
     *  is a human switching off somebody else's second factor, so it is never quiet. */
    resetMfa: (slug: string, reason: string) =>
      post<{ detail: string; freeze_hours: number }>('/platform/reset-mfa/', { slug, reason }),
  },

  audit: {
    list: (params: { tenant?: string; action?: string; page?: number } = {}) => {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
          .map(([k, v]) => [k, String(v)]) as [string, string][]
      ).toString();
      return get<Page<AuditRow>>(`/platform/audit/${qs ? `?${qs}` : ''}`);
    },
    actions: () => get<string[]>('/platform/audit/actions/'),
  },

  impersonation: {
    history: (live?: boolean, page = 1) => {
      const p = new URLSearchParams({ page: String(page) });
      if (live) p.set('live', 'true');
      return get<Page<Grant>>(`/platform/impersonation/?${p.toString()}`);
    },
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

  /** The cross-tenant AI key — the shared key every free/Pro tenant rides, rate-limited so a
   *  spike across ISPs can't run up the platform bill. Owner-only. */
  aiSettings: {
    get: () => get<PlatformAISettings>('/platform/ai-settings/'),
    update: (body: Partial<PlatformAISettingsInput>) =>
      patch<PlatformAISettings>('/platform/ai-settings/', body),
  },

  /** The docs-gaps report: what tenants ask and where the assistant had no grounded answer. */
  docsGaps: (days = 30) => get<DocsGaps>(`/platform/ai-docs-gaps/?days=${days}`),
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
