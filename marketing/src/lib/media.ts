/**
 * THE MEDIA MANIFEST — the single source of truth for every screenshot and screen
 * recording on the marketing site.
 *
 * The problem this solves: a marketing site whose proof is "some screenshots someone
 * took once" rots. Nobody remembers which shots exist, what size they were, or which
 * page breaks if one is replaced. So the slots are DECLARED here — filename, shape,
 * and what the shot must actually show — and the page renders against the declaration.
 *
 * Drop a file into `public/media/` with the exact `file` name below and it appears.
 * Leave it out and the slot renders a labelled placeholder with the capture spec
 * instead of a broken image. The site is therefore never in a broken state, and the
 * to-do list for the person holding the camera IS the code.
 *
 * See docs/MARKETING_MEDIA.md for how to capture these (and how to do it without
 * publishing a real ISP's customer data).
 */

export type MediaKind = 'shot' | 'clip';

export interface MediaSlot {
  /** Stable id — used in the DOM and in the capture guide. */
  id: string;
  kind: MediaKind;
  /** Exact filename to drop into public/media/. */
  file: string;
  /** Poster frame for a clip: shown before it plays, and on slow connections. */
  poster?: string;
  /** Intrinsic aspect ratio. Reserving it stops the page jumping when media loads. */
  aspect: '16/9' | '16/10' | '4/3' | '9/16';
  /** Shown under the media, and read by screen readers as the alt text. */
  caption: string;
  /** What this shot has to prove. This is the brief, not a description. */
  brief: string;
}

/** Recommended capture width. Retina on a 1440-wide layout, without shipping 4K. */
export const CAPTURE_WIDTH = 2560;

export const MEDIA: Record<string, MediaSlot> = {
  hero: {
    id: 'hero',
    kind: 'shot',
    file: 'console-dashboard.png',
    aspect: '16/10',
    caption: 'The ISP console — revenue, clients and live sessions at a glance.',
    brief:
      'The ISP dashboard on seeded demo data, with the eye toggle OPEN so the money ' +
      'is visible. Full browser window, no bookmarks bar, no personal tabs.',
  },
  payments: {
    id: 'payments',
    kind: 'clip',
    file: 'stk-push.mp4',
    poster: 'stk-push.png',
    aspect: '16/9',
    caption: 'A customer buys a bundle. M-Pesa prompt, connected, counted.',
    brief:
      'Screen recording (15–25s, no audio): captive portal → pick a plan → enter ' +
      'phone → STK prompt → connected. This is the whole product in one loop.',
  },
  wallet: {
    id: 'wallet',
    kind: 'shot',
    file: 'wallet-ledger.png',
    aspect: '16/10',
    caption: 'Every shilling attributed. Commission shown, never guessed.',
    brief:
      'The Wallet page: balance, sales this month, commission line, and the ledger ' +
      'below it. This is the answer to "where is my money?" — it must be legible.',
  },
  pppoe: {
    id: 'pppoe',
    kind: 'shot',
    file: 'pppoe-clients.png',
    aspect: '16/10',
    caption: 'PPPoE clients, invoices and suspensions — on autopilot.',
    brief:
      'The PPPoE client list showing a mix of active/suspended and their account ' +
      'numbers. Proves this is not a hotspot-only toy.',
  },
  routers: {
    id: 'routers',
    kind: 'shot',
    file: 'router-health.png',
    aspect: '16/10',
    caption: 'Your MikroTiks, live — enrolled in one paste.',
    brief:
      'The Routers page with at least one router ONLINE and its RouterOS version and ' +
      'board name populated. A real device beats any diagram.',
  },
  onboarding: {
    id: 'onboarding',
    kind: 'clip',
    file: 'go-live.mp4',
    poster: 'go-live.png',
    aspect: '16/9',
    caption: 'Sign up, add your paybill, take money. No sales call.',
    brief:
      'Screen recording (20–30s, no audio): the go-live checklist → add settlement ' +
      'account → "payments are ON". Sells the thing competitors make you phone them for.',
  },
};

/** Every clip on the site, for the capture guide and the checklist. */
export const ALL_SLOTS: MediaSlot[] = Object.values(MEDIA);
