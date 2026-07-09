/** Adapters between API shapes and the UI's existing prop types, so the original
 * AI Studio components keep their exact design while reading real data. */

import { BandwidthProfile, Subscriber, OutboundCampaign } from '../types';
import { ApiCampaign, ApiPlan, ApiSubscriber } from './client';

// ---- plans ---------------------------------------------------------------

function kbpsToLabel(kbps: number): string {
  return kbps >= 1024 ? `${Math.round(kbps / 1024)} Mbps` : `${kbps} Kbps`;
}

function labelToKbps(label: string): number {
  const value = parseFloat(label) || 1;
  return /kbps/i.test(label) ? Math.round(value) : Math.round(value * 1024);
}

function secondsToValidityLabel(seconds: number): string {
  const days = seconds / 86400;
  if (days >= 28) return 'Monthly';
  if (days >= 7) return 'Weekly';
  if (days >= 1) return 'Daily';
  const hours = Math.round(seconds / 3600);
  return hours >= 1 ? `${hours} Hour${hours > 1 ? 's' : ''}` : `${Math.round(seconds / 60)} Min`;
}

/** DurationField accepts Django's "[DD ]HH:MM:SS" format. */
function secondsToDuration(totalSeconds: number): string {
  const days = Math.floor(totalSeconds / 86400);
  let rem = totalSeconds - days * 86400;
  const h = Math.floor(rem / 3600);
  rem -= h * 3600;
  const m = Math.floor(rem / 60);
  const s = Math.round(rem - m * 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  const hms = `${pad(h)}:${pad(m)}:${pad(s)}`;
  return days > 0 ? `${days} ${hms}` : hms;
}

export function planToProfile(plan: ApiPlan): BandwidthProfile {
  return {
    id: String(plan.id),
    name: plan.name,
    downloadSpeed: kbpsToLabel(plan.download_kbps),
    uploadSpeed: kbpsToLabel(plan.upload_kbps),
    price: Number(plan.price),
    validityDays: plan.duration_seconds / 86400,
    validityLabel: secondsToValidityLabel(plan.duration_seconds),
    sharedUsersLimit: plan.shared_users,
    description: plan.description || undefined,
    isActive: plan.is_active,
  };
}

export function profileToPlan(profile: Omit<BandwidthProfile, 'id'>): Partial<ApiPlan> {
  return {
    name: profile.name,
    price: String(profile.price),
    duration: secondsToDuration(Math.max(60, Math.round(profile.validityDays * 86400))),
    download_kbps: labelToKbps(profile.downloadSpeed),
    upload_kbps: labelToKbps(profile.uploadSpeed),
    shared_users: profile.sharedUsersLimit,
    description: profile.description ?? '',
    is_active: profile.isActive,
  };
}

// ---- campaigns -------------------------------------------------------------

const CHANNEL_UP = { sms: 'SMS', whatsapp: 'WhatsApp' } as const;
const AUDIENCE_UP = { all: 'All', active: 'Active', expired: 'Expired' } as const;

export function campaignToUi(c: ApiCampaign): OutboundCampaign {
  return {
    id: String(c.id),
    name: c.name,
    channel: CHANNEL_UP[c.channel],
    audience: AUDIENCE_UP[c.audience],
    body: c.body,
    recipients: c.total_recipients,
    sentAt: new Date(c.created_at).toLocaleString('en-KE', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }),
    status: c.status === 'done' ? 'Sent' : 'Queued',
  };
}

// ---- subscribers (minimal shape for MessagingView audience counts) ---------

export function subscriberToUi(s: ApiSubscriber): Subscriber {
  return {
    id: String(s.id),
    name: s.name || s.phone,
    phone: s.phone,
    email: s.email,
    ipAddress: '',
    planId: '',
    status: s.active_sessions > 0 ? 'Active' : 'Expired',
    billingType: 'Daily',
    nextBillingDate: s.last_session_expires?.slice(0, 10) ?? '',
    autoInvoice: false,
    balance: 0,
    createdAt: s.date_joined.slice(0, 10),
  };
}
