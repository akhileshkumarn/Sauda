'use client';
import Link from 'next/link';
import { getOverview } from '@/lib/api';
import { ist, paymentState, supplierName } from '@/lib/format';
import { useAsync } from '@/lib/useAsync';
import type { OverviewOrder } from '@/lib/types';
import { OrderPill, orderStatus, poAckStatus } from './status';
import { ButtonLink, EmptyState, ErrorState, Evidence, Icon, Money, Skeleton } from './ui';

// One status model for every restock, from first draft to delivery. Sauda tracks up to "payment reported";
// payment is the owner's claim (not bank-verified) and delivery is not tracked.
export const ORDER_STAGES: { key: string; label: string; body: string }[] = [
  { key: 'draft', label: 'Draft', body: 'You are writing the restock list. Nothing is sent to suppliers.' },
  { key: 'proposed', label: 'Proposed', body: 'Sauda negotiated and has a cart ready for your approval.' },
  { key: 'approved', label: 'Approved', body: 'You approved the cart. One order is made per supplier.' },
  { key: 'po', label: 'PO sent', body: 'The purchase order went to the supplier, who accepts or declines it.' },
  { key: 'link', label: 'Payment link', body: 'A UPI request for the supplier’s payout account on record is ready.' },
  { key: 'reported', label: 'Payment reported', body: 'You entered the UTR. This is your claim; Sauda has not checked it with the bank.' },
  { key: 'delivery', label: 'Delivery', body: 'Not tracked by Sauda. Check with the supplier.' },
];

/** Index into ORDER_STAGES for an order that exists (so at least "PO sent"). */
export function orderStage(o: OverviewOrder): number {
  const p = paymentState(o.payment_status || (o.status === 'settled' || o.status === 'payment_claimed' ? 'claimed' : null));
  if (p === 'claimed' || p === 'mismatch') return 5;
  if (p === 'issued') return 4;
  return 3;
}

function StageMeter({ o }: { o: OverviewOrder }) {
  const cancelled = String(o.status).toLowerCase() === 'cancelled';
  const i = orderStage(o);
  const label = cancelled ? 'Cancelled' : `Step ${i + 1} of ${ORDER_STAGES.length}: ${ORDER_STAGES[i].label}`;
  return (
    <span className="ord-prog">
      <span className={`ord-stage ${cancelled ? 'off' : ''}`} aria-hidden title={label}>
        {ORDER_STAGES.map((s, k) => <span key={s.key} className={k < i ? 'done' : k === i ? 'cur' : k === ORDER_STAGES.length - 1 ? 'na' : ''} />)}
      </span>
      <span className="ord-prog-t"><span className="sr-only">{label}</span><span aria-hidden>{cancelled ? 'Cancelled' : `${i + 1}/${ORDER_STAGES.length} · ${ORDER_STAGES[i].label}`}</span></span>
    </span>
  );
}

function nextAction(o: OverviewOrder): { label: string; primary: boolean } {
  const s = orderStatus(o).label;
  if (s === 'Waiting for your payment') return { label: 'Pay', primary: true };
  const ack = poAckStatus(o.po_ack);
  if (ack && /reject|declin/.test(ack)) return { label: 'Details', primary: false };
  return { label: 'View', primary: false };
}

export function OrdersEmpty() {
  return (
    <div className="empty-wrap">
      <EmptyState icon="box" title="No orders yet"
        action={<div className="empty-actions"><ButtonLink href="/restock">Start a restock</ButtonLink><Link className="textlink" href="/trust/latest">See a signed record</Link></div>}>
        Orders appear here after you approve a cart. Sauda never orders on its own.
      </EmptyState>
    </div>
  );
}

export function StageLegend() {
  return (
    <Evidence label="How an order moves: 7 stages">
      <ol className="ord-legend">
        {ORDER_STAGES.map((s, i) => <li key={s.key}><span className="n" aria-hidden>{i + 1}</span><span><b>{s.label}</b> <span className="muted">{s.body}</span></span></li>)}
      </ol>
    </Evidence>
  );
}

export function OrdersView() {
  const { data, error, loading, reload } = useAsync(() => getOverview(), []);
  if (loading && !data) return <div aria-busy="true" aria-label="Loading orders"><Skeleton lines={6} /></div>;
  if (error && !data) return <ErrorState error={error} onRetry={reload} title="Could not load your orders" />;
  const orders = data?.recent_orders || [];
  const pending = data?.pending_confirmation_id || null;
  const neg = data?.active_negotiation || null;
  const draft = neg && /^(created|drafted|draft)$/.test(String(neg.status));
  const banner = pending ? (
    <div className="ord-next">
      <span className="ord-next-tag">Proposed</span>
      <span className="grow"><b>A cart is waiting for your approval.</b> Nothing is ordered until you approve it.</span>
      <ButtonLink href={`/confirm/${encodeURIComponent(pending)}`} size="sm">Review cart</ButtonLink>
    </div>
  ) : draft ? (
    <div className="ord-next">
      <span className="ord-next-tag">Draft</span>
      <span className="grow"><b>You have a restock in draft.</b> Finish it to start negotiating.</span>
      <ButtonLink href="/restock" size="sm" variant="secondary">Continue</ButtonLink>
    </div>
  ) : null;
  if (!orders.length) return <div className="stack">{banner}<OrdersEmpty /><StageLegend /></div>;
  const toPay = orders.filter((o) => orderStatus(o).label === 'Waiting for your payment').length;
  return (
    <div className="stack">
      {banner}
      <p className="ord-sum" role="status">
        <span><b>{orders.length}</b> recent {orders.length === 1 ? 'order' : 'orders'}</span>
        {toPay > 0 && <span className="pill warn"><span className="dot" aria-hidden /><span><b>{toPay}</b> waiting for your payment</span></span>}
      </p>

      {/* desktop and tablet: table */}
      <div className="ord-table table-wrap">
        <table>
          <caption className="sr-only">Recent orders</caption>
          <thead><tr><th scope="col">Supplier</th><th scope="col">Status</th><th scope="col">Progress</th><th scope="col" className="right">Amount</th><th scope="col">Ordered</th><th scope="col"><span className="sr-only">Action</span></th></tr></thead>
          <tbody>
            {orders.map((o) => {
              const name = supplierName(o.supplier_id, o.supplier_name || undefined);
              const act = nextAction(o);
              return (
                <tr key={o.order_id}>
                  <td><span className="ord-name">{name}</span><span className="ord-id">{o.order_id}</span></td>
                  <td><OrderPill o={o} /></td>
                  <td><StageMeter o={o} /></td>
                  <td className="right"><Money paise={o.total_paise} /></td>
                  <td className="nowrap small muted">{ist(o.created_at)}</td>
                  <td className="right"><Link className={`btn sm ${act.primary ? '' : 'secondary'}`} href={`/pay/${encodeURIComponent(o.order_id)}`} aria-label={`${act.label}: ${name}, ${o.order_id}`}>{act.primary && <Icon name="upi" size={14} />}{act.label}</Link></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* phone: compact list */}
      <ul className="ord-list ord-mobile" aria-label="Recent orders">
        {orders.map((o) => {
          const name = supplierName(o.supplier_id, o.supplier_name || undefined);
          return (
            <li key={o.order_id}>
              <Link href={`/pay/${encodeURIComponent(o.order_id)}`} className="ord-row">
                <span className="ord-main">
                  <span className="ord-name">{name}</span>
                  <span className="ord-meta"><OrderPill o={o} /></span>
                  <span className="ord-meta"><StageMeter o={o} /><span>{ist(o.created_at)}</span></span>
                </span>
                <span className="ord-amt">
                  <Money paise={o.total_paise} />
                  {nextAction(o).primary && <span className="ord-pay">Pay</span>}
                </span>
                <span className="chev-ico"><Icon name="chev" size={16} /></span>
              </Link>
            </li>
          );
        })}
      </ul>
      <p className="ord-foot">Last {orders.length} {orders.length === 1 ? 'order' : 'orders'}. Payment status is what you reported, not bank-verified. Delivery is not tracked; check with the supplier.</p>
      <StageLegend />
    </div>
  );
}
