const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });

export function rupees(paise: number | null | undefined, whole = false): string {
  if (paise === null || paise === undefined || Number.isNaN(paise)) return '—';
  return (whole ? inr0 : inr).format(paise / 100);
}

export function paiseToRupeeString(paise: number): string {
  return (paise / 100).toFixed(2);
}

export function ist(ts?: string | null): string {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) + ' IST';
}

export function istDate(ts?: string | null): string {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', year: 'numeric' });
}

export function shortHash(h?: string | null, n = 10): string {
  if (!h) return '—';
  return h.length > n * 2 ? `${h.slice(0, n)}…${h.slice(-6)}` : h;
}

/** Registered payout shown masked: "79••••57@ybl". The full VPA stays in the UPI link only. */
/** Payee UPI IDs are never printed in full: "79••••357@ybl" (first 2 + last 3 of the local part).
 *  Prefer the backend's payout_vpa_masked when present. The raw VPA lives only in the upi:// link / QR. */
export function maskVpa(vpa?: string | null, masked?: string | null): string {
  if (masked) return masked;
  if (!vpa) return '—';
  const i = vpa.lastIndexOf('@');
  const user = i >= 0 ? vpa.slice(0, i) : vpa;
  const host = i >= 0 ? vpa.slice(i) : '';
  if (user.includes('•')) return vpa; // already masked
  const u = user.length <= 5 ? `${user.slice(0, 1)}••••` : `${user.slice(0, 2)}••••${user.slice(-3)}`;
  return `${u}${host}`;
}

const VPA_RE = /[A-Za-z0-9._-]{2,}@[A-Za-z][A-Za-z0-9.-]{1,}/g;
/** Mask every UPI-ID-looking token inside free text (evidence lines, transcripts, JSON). */
export function maskVpasIn(text: string): string {
  return String(text).replace(VPA_RE, (m) => (m.includes('•') ? m : maskVpa(m)));
}
/** Map masked -> raw for every VPA in `raw`, so an edited masked text can be restored before parsing. */
export function unmaskWith(text: string, raw: string): string {
  let out = text;
  for (const m of new Set(raw.match(VPA_RE) || [])) out = out.split(maskVpa(m)).join(m);
  return out;
}

/** Contract 5: legacy "settled" is read as "claimed" (owner-reported, not bank-verified). */
export function paymentState(s?: string | null): 'issued' | 'claimed' | 'mismatch' | 'cancelled' | 'none' {
  const v = String(s || '').toLowerCase();
  if (v === 'settled' || v === 'claimed' || v === 'payment_claimed') return 'claimed';
  if (v === 'mismatch') return 'mismatch';
  if (v === 'cancelled') return 'cancelled';
  if (v === 'issued') return 'issued';
  return 'none';
}

export function plusDaysIso(d: number): string {
  // date in IST
  const t = new Date(Date.now() + 5.5 * 3600_000 + d * 86400_000);
  return t.toISOString().slice(0, 10);
}

export function relTime(ts?: string | null): string {
  if (!ts) return '';
  const d = new Date(ts).getTime();
  if (Number.isNaN(d)) return '';
  const s = Math.round((Date.now() - d) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return istDate(ts);
}

export function plural(n: number, one: string, many = one + 's'): string {
  return `${n.toLocaleString('en-IN')} ${n === 1 ? one : many}`;
}

/** Plain-language reason for a gate/guard code. Context fills in the numbers when we have them. */
export function reasonText(code: string, ctx: { supplier?: string; advance?: number | null; maxAdvance?: number | null } = {}): string {
  const who = ctx.supplier || 'The supplier';
  switch (String(code).toUpperCase()) {
    case 'ADVANCE_TOO_HIGH':
      return ctx.advance != null && ctx.maxAdvance != null
        ? `${who} asked for ${ctx.advance}% advance; your limit is ${ctx.maxAdvance}%`
        : `${who} asked for more advance payment than your limit`;
    case 'GUARD_BLOCKED': return 'Message contained instructions to the agent (blocked by Model Armor)';
    case 'GUARD_TIMEOUT': return 'Safety screening timed out, so the message was treated as unsafe';
    case 'PAYEE_MISMATCH': return 'Payout account changed to one not on record';
    case 'OVER_CEILING': return 'A unit price was above your ceiling';
    case 'OVER_BUDGET': return 'The total would go over your budget';
    case 'SUPPLIER_UNKNOWN': return `${who} is not a registered supplier, or its identity did not match the registry`;
    case 'SUPPLIER_QUARANTINED': return `${who} is quarantined after repeated unsafe messages`;
    case 'MANDATE_INVALID': return 'Your signed limits are missing, invalid or expired';
    case 'MANDATE_EXPIRED': return 'Your signed limits have expired';
    case 'LATE_DELIVERY': return 'Delivery would arrive after your deliver-by date';
    case 'ANOMALY': return 'Unusual quantity or price; Sauda wants you to look';
    case 'OWNER_APPROVAL': return 'Placing the order needs your approval';
    case 'DUPLICATE': return 'This exact order was already placed once';
    case 'REVOKED': return 'You switched off this mandate (kill switch)';
    case 'GATE_ERROR': return 'A safety check could not run, so the action was blocked';
    case 'NONCE_NOT_ECHOED': return `${who}'s reply could not be matched to our request (possible spoof)`;
    case 'CHAIN_BROKEN': return 'The audit record was altered, so verification fails';
    case 'INVALID_AMOUNT': return 'A price or quantity was zero or negative';
    case 'CART_CHANGED': return 'The offer changed after you saw it; review it again';
    case 'PO_NOT_ACCEPTED': return 'The supplier has not accepted the order, so no payment is requested';
    case 'NOT_THIS_SESSION': return 'This belongs to a different owner session';
    case 'AMOUNT_MISMATCH': return 'The amount you entered does not match the payment request';
    case 'PAYEE_MISMATCH_PROOF': return 'The payee does not match the account on record';
    case 'UTR_REUSED': return 'This UTR was already used for another payment';
    case 'UTR_FORMAT': return 'A UTR is exactly 12 digits';
    case 'ORDER_CANCELLED': return 'This order was cancelled';
    case 'PREVIOUS_MISMATCH': return 'An earlier report for this order did not match; this order needs a call to the supplier'; 
    default: return String(code).replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase());
  }
}

export const SUPPLIER_NAMES: Record<string, string> = {
  metro: 'Metro Distributors',
  sharma: 'Sharma Traders',
  quickstock: 'QuickStock',
};
export function supplierName(id: string, name?: string): string {
  return name || SUPPLIER_NAMES[id] || id;
}

export const CEILING_SOURCE_LABEL: Record<string, string> = {
  'last_paid_x1.10': 'Last paid × 1.10',
  mrp: 'MRP (pack label)',
  'mandi_modal_x1.10': 'Mandi modal × 1.10 (data.gov.in)',
  doca_retail: 'DoCA retail average',
};
export function ceilingSource(s: string): string {
  return CEILING_SOURCE_LABEL[s] || s.replace(/_/g, ' ');
}

/** Display-only: "sugar" -> "Sugar". The data is never changed. */
export function cap1(s?: string | null): string { return s ? s[0].toUpperCase() + s.slice(1) : ''; }
