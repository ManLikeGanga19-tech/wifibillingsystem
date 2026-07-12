/**
 * The signup API client.
 *
 * NO BROWSER STORAGE — the hard rule of this system, and here it does real work. The
 * draft lives on the SERVER, keyed by an httpOnly cookie the wizard cannot read. So
 * "which step am I on?" is a question only the server can answer, and we ask it
 * (GET /state/) instead of trusting anything in the page.
 *
 * That is why a refresh mid-signup resumes exactly where they were, why a half-filled
 * form cannot be resurrected on a shared laptop by hitting Back, and why nothing here
 * goes stale after a deploy.
 *
 * Same-origin via the dev/edge proxy, so the cookie rides along with credentials:
 * 'include' and no CORS preflight on every keystroke of the slug checker.
 */

export const STEPS = {
  IDENTITY: 1,
  VERIFY_EMAIL: 2,
  COMPANY: 3,
  DETAILS: 4,
  SECURE: 5,
  DONE: 6,
} as const;

export type Step = (typeof STEPS)[keyof typeof STEPS];

export interface SignupState {
  step: Step;
  known: {
    full_name?: string;
    email?: string;
    email_verified?: boolean;
    company_name?: string;
    slug?: string;
    county?: string;
    phone?: string;
    referral_source?: string;
  };
  counties: string[];
  referral_sources: string[];
  tos_version: string;
  resend_available_in?: number;
  complete?: boolean;
  console_url?: string | null;
}

export interface Availability {
  slug: string;
  suggestion: string | null;
  name_available?: boolean;
  slug_available?: boolean;
  domain?: string;
}

export interface CompleteResult {
  detail: string;
  slug: string;
  console_url: string;
  next: string;
}

export class SignupError extends Error {
  constructor(
    message: string,
    /** Field-level errors, so the wizard can point at the offending input. */
    public fields: Record<string, string> = {},
    public status = 400
  ) {
    super(message);
  }
}

const BASE = '/api/v1/signup';

/** DRF hands back either {detail} or {field: [msg]}. Flatten it into something the
 *  form can actually render, without ever showing a bare "[object Object]". */
function toError(status: number, body: unknown): SignupError {
  if (!body || typeof body !== 'object') {
    return new SignupError(`Something went wrong (HTTP ${status}).`, {}, status);
  }
  const record = body as Record<string, unknown>;
  if (typeof record.detail === 'string') {
    return new SignupError(record.detail, {}, status);
  }
  const fields: Record<string, string> = {};
  for (const [key, value] of Object.entries(record)) {
    fields[key] = Array.isArray(value) ? String(value[0]) : String(value);
  }
  const first = Object.values(fields)[0] ?? 'Please check the form.';
  return new SignupError(first, fields, status);
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const body = resp.status === 204 ? null : await resp.json().catch(() => null);
  if (!resp.ok) throw toError(resp.status, body);
  return body as T;
}

const post = <T>(path: string, payload: unknown) =>
  call<T>(path, { method: 'POST', body: JSON.stringify(payload) });

export const signup = {
  /** The only source of truth for where the applicant is. */
  state: () => call<SignupState>('/state/'),

  /** Step 1. Deliberately says the same thing whether or not the email is taken —
   *  confirming "that address has an account" is an enumeration oracle. */
  start: (full_name: string, email: string) =>
    post<{ detail: string; step: Step; email: string }>('/start/', { full_name, email }),

  verify: (code: string) => post<{ detail: string; step: Step }>('/verify/', { code }),
  resend: () => post<{ detail: string }>('/resend/', {}),

  /** Advisory only — the database's unique constraint is what actually decides, at
   *  the moment the ISP is created. */
  availability: (params: { name?: string; slug?: string }) => {
    const q = new URLSearchParams();
    if (params.name) q.set('name', params.name);
    if (params.slug) q.set('slug', params.slug);
    return call<Availability>(`/availability/?${q}`);
  },

  company: (company_name: string, slug: string) =>
    post<{ detail: string; step: Step }>('/company/', { company_name, slug }),

  details: (payload: { county: string; phone: string; referral_source?: string }) =>
    post<{ detail: string; step: Step }>('/details/', payload),

  complete: (password: string, confirm_password: string, accept_tos: boolean) =>
    post<CompleteResult>('/complete/', { password, confirm_password, accept_tos }),
};
