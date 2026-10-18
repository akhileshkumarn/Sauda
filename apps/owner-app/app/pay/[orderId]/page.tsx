import type { Metadata } from 'next';
import { AuthGate } from '@/components/AuthGate';
import { PayView } from '@/components/PayView';
import { PageHead } from '@/components/ui';

export const metadata: Metadata = { title: 'Pay' };

export default async function PayPage({ params, searchParams }: { params: Promise<{ orderId: string }>; searchParams: Promise<{ more?: string }> }) {
  const { orderId } = await params;
  const { more } = await searchParams;
  return (
    <div className="narrow">
      <AuthGate>
        <PageHead crumbs={[{ href: '/orders', label: 'Orders' }, { label: decodeURIComponent(orderId) }]} title="Pay this order" />
        <PayView orderId={decodeURIComponent(orderId)} more={more ? parseInt(more, 10) || 0 : 0} />
      </AuthGate>
    </div>
  );
}
