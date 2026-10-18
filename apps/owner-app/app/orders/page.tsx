import type { Metadata } from 'next';
import { AuthGate } from '@/components/AuthGate';
import { OrdersView } from '@/components/OrdersView';
import { PageHead } from '@/components/ui';

export const metadata: Metadata = { title: 'Orders' };

export default function OrdersPage() {
  return (
    <div className="wide">
      <AuthGate>
        <PageHead title="Orders" description="Each approved cart becomes one order per supplier. Pay from here and check how far each order has gone." />
        <OrdersView />
      </AuthGate>
    </div>
  );
}
