import { BandwidthProfile, Subscriber, HotspotVoucher, Invoice, RouterConfig, SystemLog } from '../types';

// Default / initial templates for speed limits and packages
export const DEFAULT_PROFILES: BandwidthProfile[] = [
  {
    id: 'prof-1',
    name: '1 Hour Hotspot Premium',
    downloadSpeed: '5 Mbps',
    uploadSpeed: '2 Mbps',
    price: 30,
    validityDays: 0.04, // 1 hour
    validityLabel: '1 Hour',
    sharedUsersLimit: 1,
    description: 'High speed short duration access, ideal for quick browse.',
    isActive: true
  },
  {
    id: 'prof-2',
    name: 'Daily Standard Wifi',
    downloadSpeed: '3 Mbps',
    uploadSpeed: '1 Mbps',
    price: 50,
    validityDays: 1,
    validityLabel: 'Daily',
    sharedUsersLimit: 1,
    description: 'Standard speed package, unlimited data for 24 hours.',
    isActive: true
  },
  {
    id: 'prof-3',
    name: 'Weekly Premium Wifi',
    downloadSpeed: '6 Mbps',
    uploadSpeed: '3 Mbps',
    price: 350,
    validityDays: 7,
    validityLabel: 'Weekly',
    sharedUsersLimit: 2,
    description: 'Premium speed, multi-device access for 7 days.',
    isActive: true
  },
  {
    id: 'prof-4',
    name: 'Monthly Basic Fiber',
    downloadSpeed: '10 Mbps',
    uploadSpeed: '5 Mbps',
    price: 2000,
    validityDays: 30,
    validityLabel: 'Monthly',
    sharedUsersLimit: 3,
    description: 'Home or business fiber-like speed, unlimited for 30 days.',
    isActive: true
  },
  {
    id: 'prof-5',
    name: 'Monthly SME Unlimited',
    downloadSpeed: '20 Mbps',
    uploadSpeed: '10 Mbps',
    price: 4500,
    validityDays: 30,
    validityLabel: 'Monthly',
    sharedUsersLimit: 5,
    description: 'Dedicated speed for offices, mini-cafes, and shops.',
    isActive: true
  }
];

export const DEFAULT_SUBSCRIBERS: Subscriber[] = [
  {
    id: 'sub-1',
    name: 'Harun Mwangi',
    phone: '+254 712 345 678',
    email: 'harun.mwangi@gmail.com',
    address: 'Block A, Apartment 12',
    ipAddress: '192.168.88.50',
    macAddress: 'C8:D7:19:AA:BB:CC',
    planId: 'prof-4', // Monthly Basic Fiber (Ksh 2,000)
    status: 'Active',
    billingType: 'Monthly',
    nextBillingDate: '2026-06-14', // Due today! Useful for automated trigger simulation
    autoInvoice: true,
    balance: 0,
    createdAt: '2026-05-14'
  },
  {
    id: 'sub-2',
    name: 'Amina Omondi',
    phone: '+254 722 987 654',
    email: 'amina.omondi@yahoo.com',
    address: 'Plot 4, Ground Floor Shop',
    ipAddress: '192.168.88.51',
    macAddress: '40:B0:34:CC:DD:EE',
    planId: 'prof-5', // Monthly SME Unlimited (Ksh 4,500)
    status: 'Active',
    billingType: 'Monthly',
    nextBillingDate: '2026-06-28', // Due later
    autoInvoice: true,
    balance: 0,
    createdAt: '2026-05-28'
  },
  {
    id: 'sub-3',
    name: 'John Doe',
    phone: '+1 415 555 2673',
    email: 'jdoe@fastwifi.net',
    address: 'Room 5B, Student Compound',
    ipAddress: '192.168.88.102',
    macAddress: '90:32:00:1F:11:22',
    planId: 'prof-2', // Daily Standard Wifi (Ksh 50)
    status: 'Active',
    billingType: 'Daily',
    nextBillingDate: '2026-06-14', // Due today! Daily subscriber automated invoice demonstration
    autoInvoice: true,
    balance: 50, // Outstanding balance
    createdAt: '2026-06-13'
  },
  {
    id: 'sub-4',
    name: 'Priscilla Wanjiku',
    phone: '+254 733 444 555',
    email: 'cilly_wanjiku@outlook.com',
    address: 'Main Highway Cyber Cafe',
    ipAddress: '192.168.88.80',
    macAddress: '54:B8:0A:11:22:33',
    planId: 'prof-5', // Monthly SME Unlimited (Ksh 4,500)
    status: 'Expired',
    billingType: 'Monthly',
    nextBillingDate: '2026-06-10', // Overdue and Expired! Needs billing/payment re-triggering
    autoInvoice: true,
    balance: 4500,
    createdAt: '2026-04-10'
  },
  {
    id: 'sub-5',
    name: 'David Cheruiyot',
    phone: '+254 701 112 233',
    email: 'david.cheru@cybernet.co.ke',
    address: 'Apartment D4, Upper Ground',
    ipAddress: '192.168.88.92',
    macAddress: 'AA:BB:CC:DD:EE:FF',
    planId: 'prof-3', // Weekly Premium Wifi (Ksh 350)
    status: 'Active',
    billingType: 'Daily', // Billed every validity cycle
    nextBillingDate: '2026-06-17',
    autoInvoice: false, // Manual invoicing flag configuration test
    balance: 0,
    createdAt: '2026-06-10'
  }
];

export const DEFAULT_VOUCHERS: HotspotVoucher[] = [
  {
    id: 'vouch-1',
    code: 'WF-8241A',
    profileId: 'prof-1',
    price: 30,
    status: 'Unused',
    createdAt: '2026-06-13T10:15:00Z'
  },
  {
    id: 'vouch-2',
    code: 'WF-9182C',
    profileId: 'prof-1',
    price: 30,
    status: 'Active',
    usedByMac: 'D4:12:43:B5:E8:90',
    usedAt: '2026-06-13T23:45:00Z',
    expiresBy: '2026-06-14T00:45:00Z',
    createdAt: '2026-06-13T11:00:00Z'
  },
  {
    id: 'vouch-3',
    code: 'WF-FAST4',
    profileId: 'prof-2',
    price: 50,
    status: 'Unused',
    createdAt: '2026-06-14T01:30:00Z'
  },
  {
    id: 'vouch-4',
    code: 'WF-K927S',
    profileId: 'prof-3',
    price: 350,
    status: 'Expired',
    usedByMac: '90:32:00:15:EF:4A',
    usedAt: '2026-06-05T09:00:00Z',
    expiresBy: '2026-06-12T09:00:00Z',
    createdAt: '2026-06-05T08:30:00Z'
  }
];

export const DEFAULT_INVOICES: Invoice[] = [
  {
    id: 'inv-1',
    invoiceNumber: 'INV-2026-0001',
    subscriberId: 'sub-4',
    subscriberName: 'Priscilla Wanjiku',
    planName: 'Monthly SME Unlimited',
    amount: 4500,
    status: 'Unpaid',
    dateCreated: '2026-06-10',
    dateDue: '2026-06-15',
    periodStart: '2026-06-10',
    periodEnd: '2026-07-10'
  },
  {
    id: 'inv-2',
    invoiceNumber: 'INV-2026-0002',
    subscriberId: 'sub-2',
    subscriberName: 'Amina Omondi',
    planName: 'Monthly SME Unlimited',
    amount: 4500,
    status: 'Paid',
    dateCreated: '2026-05-28',
    datePaid: '2026-05-28',
    dateDue: '2026-06-02',
    periodStart: '2026-05-28',
    periodEnd: '2026-06-28'
  },
  {
    id: 'inv-3',
    invoiceNumber: 'INV-2026-0003',
    subscriberId: 'sub-1', // Harun Mwangi
    subscriberName: 'Harun Mwangi',
    planName: 'Monthly Basic Fiber',
    amount: 2000,
    status: 'Paid',
    dateCreated: '2026-05-14',
    datePaid: '2026-05-14',
    dateDue: '2026-05-19',
    periodStart: '2026-05-14',
    periodEnd: '2026-06-14'
  }
];

export const DEFAULT_ROUTER: RouterConfig = {
  id: 'router-main',
  name: 'Core_RouterBOARD_951G',
  ipAddress: '192.168.88.1',
  port: 8728, // RouterOS API Port
  username: 'admin',
  isConnected: true,
  dnsServer: '8.8.8.8, 1.1.1.1',
  hotspotInterface: 'ether3-hotspot-lan'
};

export const DEFAULT_LOGS: SystemLog[] = [
  {
    id: 'log-1',
    timestamp: '2026-06-13 18:24:10',
    category: 'Router',
    type: 'success',
    message: 'Successfully established API socket handshake with MikroTik RouterBOARD Core_RouterBOARD_951G.'
  },
  {
    id: 'log-2',
    timestamp: '2026-06-13 19:00:00',
    category: 'Billing',
    type: 'info',
    message: 'System cron: executing automated daily validation script for expiration schedules.'
  },
  {
    id: 'log-3',
    timestamp: '2026-06-13 23:45:00',
    category: 'Hotspot',
    type: 'info',
    message: 'Hotspot login triggered: User with MAC D4:12:43:B5:E8:90 entered voucher WF-9182C.'
  },
  {
    id: 'log-4',
    timestamp: '2026-06-14 00:10:05',
    category: 'Router',
    type: 'warning',
    message: 'MikroTik alert: CPU utilization spiked to 88% momentarily during route convergence.'
  }
];

// Helper to generate a unique voucher code
export function generateVoucherCode(length: number = 6, prefix: string = 'WF-'): string {
  const chars = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'; // Exclude ambiguous characters like 0, O, 1, I
  let result = '';
  for (let i = 0; i < length; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return prefix + result;
}

// Calculate next billing date adding days/months
export function calculateNextDate(currentDateStr: string, interval: 'Daily' | 'Monthly', daysCount: number = 1): string {
  const current = new Date(currentDateStr);
  if (isNaN(current.getTime())) {
    return new Date().toISOString().substring(0, 10);
  }
  
  if (interval === 'Daily') {
    current.setDate(current.getDate() + daysCount);
  } else {
    current.setMonth(current.getMonth() + 1);
  }
  
  return current.toISOString().substring(0, 10);
}

// Check subscribers and execute automated billing invoicing
// Returns the newly generated invoices, the updated subscribers list, and new logs
export function runAutomatedBillingJob(
  subscribers: Subscriber[],
  profiles: BandwidthProfile[],
  currentDateStr: string,
  invoiceCounter: number = 4
): {
  newInvoices: Invoice[];
  updatedSubscribers: Subscriber[];
  newLogs: SystemLog[];
} {
  const newInvoices: Invoice[] = [];
  const updatedSubscribers = [...subscribers];
  const newLogs: SystemLog[] = [];
  
  const currentSimulatedTime = new Date(currentDateStr);
  let counter = invoiceCounter;

  updatedSubscribers.forEach((sub, index) => {
    // If the subscriber is due for billing (nextBillingDate <= currentDateStr) 
    // and autoInvoice is active
    const nextBillDate = new Date(sub.nextBillingDate);
    const subPlan = profiles.find(p => p.id === sub.planId);
    
    if (nextBillDate <= currentSimulatedTime && sub.autoInvoice && subPlan) {
      const invNum = `INV-2026-${String(counter).padStart(4, '0')}`;
      counter++;

      const validityDays = subPlan.validityDays;
      const periodStart = sub.nextBillingDate;
      const periodEnd = calculateNextDate(periodStart, sub.billingType, Math.max(1, Math.round(validityDays)));

      // Generate Invoice
      const newInv: Invoice = {
        id: `inv-sim-${index}-${Date.now()}`,
        invoiceNumber: invNum,
        subscriberId: sub.id,
        subscriberName: sub.name,
        planName: subPlan.name,
        amount: subPlan.price,
        status: 'Unpaid',
        dateCreated: currentDateStr,
        dateDue: calculateNextDate(currentDateStr, 'Daily', 5), // 5 days grace period
        periodStart,
        periodEnd
      };

      newInvoices.push(newInv);

      // Log the event
      newLogs.push({
        id: `log-billing-${sub.id}-${Date.now()}`,
        timestamp: `${currentDateStr} 07:00:00`,
        category: 'Billing',
        type: 'success',
        message: `Automated Invoicing: Generated ${invNum} of Ksh ${subPlan.price.toFixed(2)} for ${sub.name} (Plan: ${subPlan.name}).`
      });

      // Update Subscriber stats:
      // Update their outstanding balance and increment their billing date
      const oldNextDate = sub.nextBillingDate;
      const computedNextDate = calculateNextDate(oldNextDate, sub.billingType, Math.max(1, Math.round(validityDays)));
      
      updatedSubscribers[index] = {
        ...sub,
        balance: Number((sub.balance + subPlan.price).toFixed(2)),
        nextBillingDate: computedNextDate,
        // Since subscription renewed billing, they stay Active or transition depending on payment
        // Usually, in standard systems, and auto-invoice is issued, they remain Active for grace period.
        status: sub.status === 'Expired' ? 'Active' : sub.status
      };
      
      newLogs.push({
        id: `log-sub-${sub.id}-${Date.now()}`,
        timestamp: `${currentDateStr} 07:01:12`,
        category: 'Subscriber',
        type: 'info',
        message: `Subscriber ${sub.name} cycle advanced. Next billing set to ${computedNextDate} (previously ${oldNextDate}).`
      });
    }
  });

  return {
    newInvoices,
    updatedSubscribers,
    newLogs
  };
}
