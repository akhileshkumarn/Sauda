'use client';
import Link from 'next/link';
import { getOverview } from '@/lib/api';
import { ist, supplierName } from '@/lib/format';
import { useAsync } from '@/lib/useAsync';
import { OrderPill, orderStatus } from './status';
import { ButtonLink, EmptyState, ErrorState, Icon, Money, Skeleton } from './ui';

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

export function OrdersView() {
  const { data, error, loading, reload } = useAsync(() => getOverview(), []);
  if (loading && !data) return <Skeleton lines={6} />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} title="Could not load your orders" />;
  const orders = data?.recent_orders || [];
  if (!orders.length) return <OrdersEmpty />;
  const toPay = orders.filter((o) => orderStatus(o).label === 'Waiting for your payment').length;
  return (
    <div className="stack">
      <p className="ord-sum">
        <span><b>{orders.length}</b> recent {orders.length === 1 ? 'order' : 'orders'}</span>
        {toPay > 0 && <span className="pill warn"><span className="dot" aria-hidden /><span><b>{toPay}</b> waiting for your payment</span></span>}
      </p>
      <ul className="ord-list" aria-label="Recent orders">
        {orders.map((o) => {
          const name = supplierName(o.supplier_id, o.supplier_name || undefined);
          return (
            <li key={o.order_id}>
              <Link href={`/pay/${encodeURIComponent(o.order_id)}`} className="ord-row">
                <span className="ord-main">
                  <span className="ord-name">{name}</span>
                  <span className="ord-meta"><OrderPill o={o} /><span>{ist(o.created_at)}</span></span>
                </span>
                <span className="ord-amt">
                  <Money paise={o.total_paise} />
                  <span className="ord-id">{o.order_id}</span>
                </span>
                <span className="chev-ico"><Icon name="chev" size={16} /></span>
              </Link>
            </li>
          );
        })}
      </ul>
      <p className="ord-foot">Last {orders.length} {orders.length === 1 ? 'order' : 'orders'}. Payment status is what you reported, not bank-verified. Delivery is not tracked; check with the supplier.</p>
    </div>
  );
}
