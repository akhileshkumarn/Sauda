'use client';
import Link from 'next/link';
import { getOverview } from '@/lib/api';
import { ist, supplierName } from '@/lib/format';
import { useAsync } from '@/lib/useAsync';
import { OrderPill } from './status';
import { ButtonLink, Callout, EmptyState, ErrorState, Icon, Money, Skeleton } from './ui';

export function OrdersView() {
  const { data, error, loading, reload } = useAsync(() => getOverview(), []);
  if (loading && !data) return <Skeleton lines={6} />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} title="Could not load your orders" />;
  const orders = data?.recent_orders || [];
  if (!orders.length) {
    return <EmptyState icon="box" title="No orders yet" action={<ButtonLink href="/restock">New restock</ButtonLink>}>Orders appear here after you approve a cart. Sauda never orders on its own.</EmptyState>;
  }
  return (
    <div className="stack">
      <ul className="list" style={{ listStyle: 'none', padding: 0, margin: 0 }} aria-label="Recent orders">
        {orders.map((o) => (
          <li key={o.order_id} style={{ listStyle: 'none' }}>
            <Link href={`/pay/${encodeURIComponent(o.order_id)}`} className="rowlink" aria-label={`Order from ${supplierName(o.supplier_id, o.supplier_name || undefined)}`}>
              <div className="grow stack xs">
                <span className="strong break">{supplierName(o.supplier_id, o.supplier_name || undefined)}</span>
                <span className="small muted row sm wrap" style={{ rowGap: 0 }}><OrderPill o={o} /><span>{ist(o.created_at)}</span></span>
              </div>
              <Money paise={o.total_paise} className="strong none" />
              <span className="chev-ico"><Icon name="chev" size={16} /></span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="xs muted">Last {orders.length} orders. Delivery is not tracked; check with the supplier.</p>
    </div>
  );
}
