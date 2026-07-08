export interface BandwidthProfile {
  id: string;
  name: string;
  downloadSpeed: string; // e.g. "5 Mbps" or "10 Mbps"
  uploadSpeed: string; // e.g. "2 Mbps" or "5 Mbps"
  price: number; // in KSh
  validityDays: number; // e.g. 1 for Daily, 30 for Monthly, 0.04 for 1 hour
  validityLabel: string; // e.g. "1 Hour", "Daily", "Weekly", "Monthly"
  sharedUsersLimit: number; // e.g. 1 for single device
  description?: string;
  isActive: boolean;
}

export interface Subscriber {
  id: string;
  name: string;
  phone: string;
  email: string;
  address?: string;
  ipAddress: string;  // e.g. "192.168.88.25"
  macAddress?: string; // e.g. "50:E5:49:A3:BC:12"
  planId: string; // refers to BandwidthProfile.id
  status: 'Active' | 'Expired' | 'Suspended';
  billingType: 'Daily' | 'Monthly';
  nextBillingDate: string; // YYYY-MM-DD
  autoInvoice: boolean;
  balance: number; // pre-paid or postpaid outstanding balance
  createdAt: string;
}

export interface HotspotVoucher {
  id: string;
  code: string; // the coupon/login code
  profileId: string; // BandwidthProfile.id
  price: number;
  status: 'Unused' | 'Active' | 'Expired';
  usedByMac?: string;
  usedAt?: string;
  expiresBy?: string;
  createdAt: string;
}

export interface Invoice {
  id: string;
  invoiceNumber: string; // e.g. "INV-2026-0001"
  subscriberId: string; // Subscriber.id
  subscriberName: string;
  planName: string;
  amount: number;
  status: 'Paid' | 'Unpaid' | 'Overdue';
  dateCreated: string; // YYYY-MM-DD
  dateDue: string; // YYYY-MM-DD
  datePaid?: string; // YYYY-MM-DD
  periodStart: string;
  periodEnd: string;
}

export interface RouterConfig {
  id: string;
  name: string;
  ipAddress: string;
  port: number;
  username: string;
  password?: string;
  isConnected: boolean;
  dnsServer: string;
  hotspotInterface: string;
}

export interface OutboundCampaign {
  id: string;
  name: string;
  channel: 'SMS' | 'WhatsApp';
  audience: 'All' | 'Active' | 'Expired';
  body: string;
  recipients: number;
  sentAt: string; // YYYY-MM-DD HH:mm
  status: 'Sent' | 'Queued';
}

export interface SystemLog {
  id: string;
  timestamp: string;
  category: 'Router' | 'Billing' | 'Subscriber' | 'Hotspot';
  type: 'info' | 'success' | 'warning' | 'error';
  message: string;
}
