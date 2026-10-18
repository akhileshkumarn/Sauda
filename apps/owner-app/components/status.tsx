// Honest, plain-language statuses shared across screens.
import { paymentState } from '@/lib/format';
import { StatusPill, type Tone } from './ui';

export function poAckStatus(ack: unknown): string | null {
  if (!ack) return null;
  if (typeof ack === 'string') return ack.toLowerCase();
  const s = (ack as { status?: string }).status;
  return s ? String(s).toLowerCase() : 'received';
}

export function orderStatus(o: { status?: string | null; payment_status?: string | null; po_ack?: unknown }): { tone: Tone; label: string; icon?: string } {
  if (String(o.status).toLowerCase() === 'cancelled') return { tone: 'neutral', label: 'Cancelled', icon: 'x' };
  const p = paymentState(o.payment_status || (o.status === 'settled' || o.status === 'payment_claimed' ? 'claimed' : null));
  if (p === 'mismatch') return { tone: 'bad', label: 'Payment did not match' };
  if (p === 'claimed') return { tone: 'ok', label: 'Payment claimed (not bank-verified)', icon: 'check' };
  if (p === 'issued') return { tone: 'warn', label: 'Waiting for your payment', icon: 'upi' };
  const ack = poAckStatus(o.po_ack);
  if (ack && /accept|ok|ack|received|confirm/.test(ack)) return { tone: 'info', label: 'Supplier accepted' };
  if (ack && /reject|declin/.test(ack)) return { tone: 'bad', label: 'Supplier declined' };
  if (ack === 'partial') return { tone: 'warn', label: 'Supplier accepted part of the order' };
  return { tone: 'neutral', label: 'Order sent, awaiting supplier', icon: 'clock' };
}

export function OrderPill({ o }: { o: Parameters<typeof orderStatus>[0] }) {
  const s = orderStatus(o);
  return <StatusPill tone={s.tone} icon={s.icon}>{s.label}</StatusPill>;
}

export function negotiationLabel(status?: string | null, round?: number | null): { tone: Tone; label: string } {
  const s = String(status || '').toLowerCase();
  if (s === 'awaiting_confirmation') return { tone: 'warn', label: 'Needs your approval' };
  if (s === 'created' || s === 'drafted' || s === 'draft') return { tone: 'neutral', label: 'Draft, not signed yet' };
  if (s === 'mandate_signed' || s === 'signed') return { tone: 'info', label: 'Limits signed, ready to negotiate' };
  if (s === 'rfq_sent' || s === 'quoting' || s === 'negotiating') return { tone: 'info', label: `Negotiating${round ? `, round ${round} of 3` : ''}` };
  if (s === 'confirmed' || s === 'ordered') return { tone: 'ok', label: 'Ordered' };
  if (s === 'failed') return { tone: 'bad', label: 'Stopped: no supplier could be used' };
  if (s === 'cancelled' || s === 'declined') return { tone: 'neutral', label: 'Declined by you' };
  if (s === 'revoked') return { tone: 'bad', label: 'Stopped by kill switch' };
  return { tone: 'neutral', label: s ? s.replace(/_/g, ' ') : 'In progress' };
}

const SESSION_LABEL: Record<string, { tone: Tone; label: string; icon?: string }> = {
  draft: { tone: 'neutral', label: 'Draft', icon: 'pen' },
  awaiting_review: { tone: 'info', label: 'Ready to sign limits', icon: 'lock' },
  negotiating: { tone: 'info', label: 'Negotiating', icon: 'clock' },
  awaiting_approval: { tone: 'warn', label: 'Needs your approval' },
  ordered: { tone: 'ok', label: 'Ordered' },
  completed: { tone: 'ok', label: 'Completed' },
  cancelled: { tone: 'neutral', label: 'Cancelled', icon: 'x' },
  failed: { tone: 'bad', label: 'Stopped' },
};
export function sessionLabel(status?: string | null) {
  return SESSION_LABEL[String(status || '')] || { tone: 'neutral' as Tone, label: String(status || 'Unknown').replace(/_/g, ' ') };
}
export function SessionPill({ status }: { status?: string | null }) {
  const s = sessionLabel(status);
  return <StatusPill tone={s.tone} icon={s.icon}>{s.label}</StatusPill>;
}
export const EDITABLE_STATUSES = new Set(['draft', 'awaiting_review']);
