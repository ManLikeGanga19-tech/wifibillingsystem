/**
 * Captive-portal looks — one flexible portal, many themes.
 *
 * Each template is a preset of design tokens. They deliberately vary the things that read
 * from across a room — the PAGE BACKDROP, the CARD treatment (glass / flat / floating /
 * bordered), the HEADER, and the ACCENT — while keeping the login card's SURFACE light
 * enough for dark text. That one rule (readable card) is what lets a "dark" template use a
 * dramatic backdrop without a single line of the portal's inner content needing to know
 * which theme is active: the card is always legible.
 *
 * The ISP's own accent colour flows through as `--pt-accent` unless a template overrides it
 * (neon, monochrome), so their identity survives the theme.
 *
 * This registry is the single source of truth for the portal render. The console keeps a
 * byte-identical copy to draw its previews; a test asserts the id set matches the backend's.
 */

export interface PortalTemplate {
  id: string;
  label: string;
  /** Page backdrop. May be a gradient, image, or solid — whatever CSS `background` takes. */
  bg: string;
  /** Header text colour — light on dark backdrops, dark on light ones. */
  headerFg: string;
  /** The login card. */
  cardBg: string;
  cardBorder: string;
  cardRadius: string;
  cardShadow: string;
  /** Glass blur behind the card, or 'none'. */
  cardBlur: string;
  /** 'brand' uses the ISP's accent colour; a hex pins it (neon, monochrome). */
  accent: 'brand' | string;
  /** True if a template supports a full-bleed brand background image behind the card. */
  supportsBackgroundImage?: boolean;
}

const INK = '#141414';
const CARD_WHITE = '#ffffff';
const FROST = 'rgba(255,255,255,0.72)';

export const PORTAL_TEMPLATES: PortalTemplate[] = [
  {
    id: 'aurora', label: 'Aurora',
    bg: 'linear-gradient(160deg,#3b2f6b 0%,#5b3f8f 40%,#c86fb0 100%)',
    headerFg: '#ffffff',
    cardBg: FROST, cardBorder: '1px solid rgba(255,255,255,0.6)', cardRadius: '20px',
    cardShadow: '0 20px 60px rgba(40,20,80,0.35)', cardBlur: 'blur(14px)', accent: 'brand',
    supportsBackgroundImage: true,
  },
  {
    id: 'badge', label: 'Badge',
    bg: '#e9eaf0', headerFg: INK,
    cardBg: CARD_WHITE, cardBorder: 'none', cardRadius: '14px',
    cardShadow: '0 2px 0 var(--pt-accent), 0 12px 30px rgba(20,20,30,0.12)', cardBlur: 'none',
    accent: 'brand',
  },
  {
    id: 'classic', label: 'Classic',
    bg: '#E4E3E0', headerFg: INK,
    cardBg: CARD_WHITE, cardBorder: `2px solid ${INK}`, cardRadius: '0px',
    cardShadow: `6px 6px 0 ${INK}`, cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'clay', label: 'Clay',
    bg: '#efe7de', headerFg: '#4a3f36',
    cardBg: '#fbf7f2', cardBorder: 'none', cardRadius: '26px',
    cardShadow: '10px 10px 24px rgba(180,160,140,0.5), -8px -8px 20px rgba(255,255,255,0.8)',
    cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'grid', label: 'Grid',
    bg: 'linear-gradient(#f3f4f6,#f3f4f6), repeating-linear-gradient(0deg,#e2e4e9 0 1px,transparent 1px 28px), repeating-linear-gradient(90deg,#e2e4e9 0 1px,transparent 1px 28px)',
    headerFg: INK,
    cardBg: CARD_WHITE, cardBorder: '1px solid #d5d8df', cardRadius: '10px',
    cardShadow: '0 10px 30px rgba(20,20,30,0.1)', cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'halo', label: 'Halo',
    bg: 'radial-gradient(circle at 50% 0%,#dff1ff 0%,#eef2f7 45%,#e7e9ef 100%)',
    headerFg: '#1f2937',
    cardBg: CARD_WHITE, cardBorder: '1px solid rgba(120,170,255,0.4)', cardRadius: '18px',
    cardShadow: '0 0 0 6px rgba(120,170,255,0.12), 0 18px 40px rgba(40,80,160,0.18)',
    cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'lagoon', label: 'Lagoon',
    bg: 'linear-gradient(160deg,#0f766e 0%,#15a394 55%,#5eead4 100%)',
    headerFg: '#ffffff',
    cardBg: FROST, cardBorder: '1px solid rgba(255,255,255,0.5)', cardRadius: '18px',
    cardShadow: '0 18px 50px rgba(6,60,55,0.35)', cardBlur: 'blur(12px)', accent: 'brand',
    supportsBackgroundImage: true,
  },
  {
    id: 'linen', label: 'Linen',
    bg: 'repeating-linear-gradient(45deg,#f4f1ea 0 2px,#efeae1 2px 4px)', headerFg: '#3f3a31',
    cardBg: '#fffdf8', cardBorder: '1px solid #e4ddcf', cardRadius: '8px',
    cardShadow: '0 8px 24px rgba(120,110,90,0.18)', cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'lumen', label: 'Lumen',
    bg: '#f2f3f5', headerFg: INK,
    cardBg: CARD_WHITE, cardBorder: '1px solid #e6e8ec', cardRadius: '16px',
    cardShadow: '0 12px 34px rgba(20,20,30,0.1)', cardBlur: 'none', accent: 'brand',
    supportsBackgroundImage: true,
  },
  {
    id: 'lumen-dark', label: 'Lumen Dark',
    bg: 'linear-gradient(180deg,#1b1f27 0%,#0f1218 100%)', headerFg: '#f5f6f8',
    cardBg: CARD_WHITE, cardBorder: 'none', cardRadius: '16px',
    cardShadow: '0 20px 50px rgba(0,0,0,0.5)', cardBlur: 'none', accent: 'brand',
    supportsBackgroundImage: true,
  },
  {
    id: 'marigold', label: 'Marigold',
    bg: 'linear-gradient(160deg,#f59e0b 0%,#fbbf24 55%,#fde68a 100%)', headerFg: '#4a2f05',
    cardBg: '#fffdf7', cardBorder: 'none', cardRadius: '18px',
    cardShadow: '0 16px 40px rgba(180,120,10,0.3)', cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'monochrome', label: 'Monochrome',
    bg: '#ffffff', headerFg: INK,
    cardBg: '#ffffff', cardBorder: `1.5px solid ${INK}`, cardRadius: '2px',
    cardShadow: 'none', cardBlur: 'none', accent: INK,
  },
  {
    id: 'neon', label: 'Neon',
    bg: 'radial-gradient(circle at 50% 20%,#131a2b 0%,#0a0e1a 70%)', headerFg: '#7cf6d6',
    cardBg: '#12172a', cardBorder: '1px solid rgba(88,247,214,0.5)', cardRadius: '14px',
    cardShadow: '0 0 24px rgba(88,247,214,0.35), 0 18px 40px rgba(0,0,0,0.5)',
    cardBlur: 'none', accent: '#22d3ee',
  },
  {
    id: 'nimbus', label: 'Nimbus',
    bg: 'linear-gradient(180deg,#eef2f8 0%,#dde6f2 100%)', headerFg: '#26334a',
    cardBg: CARD_WHITE, cardBorder: 'none', cardRadius: '22px',
    cardShadow: '0 24px 55px rgba(60,90,140,0.22)', cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'pebble', label: 'Pebble',
    bg: '#e8e8e6', headerFg: '#37373a',
    cardBg: '#fbfbfa', cardBorder: 'none', cardRadius: '28px',
    cardShadow: '0 10px 26px rgba(60,60,60,0.16)', cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'simple', label: 'Simple',
    bg: '#ffffff', headerFg: INK,
    cardBg: '#ffffff', cardBorder: '1px solid #e5e7eb', cardRadius: '10px',
    cardShadow: 'none', cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'slip', label: 'Slip',
    bg: '#f0eef7', headerFg: '#2c2542',
    cardBg: CARD_WHITE, cardBorder: '1px solid #e0dcec',
    cardRadius: '4px 18px 4px 18px', cardShadow: '0 12px 32px rgba(70,50,120,0.18)',
    cardBlur: 'none', accent: 'brand',
  },
  {
    id: 'sunrise', label: 'Sunrise',
    bg: 'linear-gradient(160deg,#fb7185 0%,#fb923c 55%,#fcd34d 100%)', headerFg: '#ffffff',
    cardBg: 'rgba(255,255,255,0.86)', cardBorder: '1px solid rgba(255,255,255,0.6)',
    cardRadius: '20px', cardShadow: '0 18px 46px rgba(200,80,60,0.3)', cardBlur: 'blur(6px)',
    accent: 'brand', supportsBackgroundImage: true,
  },
  {
    id: 'vault', label: 'Vault',
    bg: 'linear-gradient(180deg,#2b2f36 0%,#16181c 100%)', headerFg: '#d7dbe0',
    cardBg: '#f4f5f7', cardBorder: '1px solid #3a3f47', cardRadius: '6px',
    cardShadow: '0 20px 50px rgba(0,0,0,0.6)', cardBlur: 'none', accent: 'brand',
  },
];

export const DEFAULT_TEMPLATE = 'lumen';

export function resolveTemplate(id?: string | null): PortalTemplate {
  return (
    PORTAL_TEMPLATES.find((t) => t.id === id) ??
    PORTAL_TEMPLATES.find((t) => t.id === DEFAULT_TEMPLATE)!
  );
}

/** Readable text colour (black/white) for content sitting on top of `hex`. */
function contrastText(hex: string): string {
  const h = hex.replace('#', '');
  if (h.length !== 6) return '#ffffff';
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  // Perceived luminance — the usual 0.299/0.587/0.114 weighting.
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? '#141414' : '#ffffff';
}

export interface BrandLike {
  accent_color?: string;
  portal_template?: string;
  background_image?: string;
}

/** The CSS custom properties a template + brand resolve to. Both the portal and the
 *  console preview spread these onto the themed container. */
export function templateVars(
  tpl: PortalTemplate,
  brand?: BrandLike | null,
): Record<string, string> {
  const accent = tpl.accent === 'brand' ? brand?.accent_color || '#228B22' : tpl.accent;
  // A brand background image only shows on templates that opted in — over their backdrop,
  // so a template that never expects one is never disturbed.
  const image = tpl.supportsBackgroundImage && brand?.background_image;
  const bg = image
    ? `linear-gradient(rgba(10,10,20,0.35),rgba(10,10,20,0.35)), url("${brand!.background_image}") center/cover no-repeat, ${tpl.bg}`
    : tpl.bg;
  return {
    '--pt-bg': bg,
    '--pt-header-fg': image ? '#ffffff' : tpl.headerFg,
    '--pt-card-bg': tpl.cardBg,
    '--pt-card-border': tpl.cardBorder,
    '--pt-card-radius': tpl.cardRadius,
    '--pt-card-shadow': tpl.cardShadow,
    '--pt-card-blur': tpl.cardBlur,
    '--pt-accent': accent,
    '--pt-accent-fg': contrastText(accent),
  };
}
