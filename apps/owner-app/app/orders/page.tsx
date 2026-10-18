import type { Metadata } from 'next';
import { AuthGate } from '@/components/AuthGate';
import { OrdersView } from '@/components/OrdersView';
import { PageHead } from '@/components/ui';

export const metadata: Metadata = { title: 'Orders' };

export default function OrdersPage() {
  return (
    <div className="narrow">
      <AuthGate>
        <PageHead eyebrow="Orders" title="Orders">Each approved cart becomes one order per supplier. Open one to pay or check its progress.</PageHead>
        <OrdersView />
      </AuthGate>
    </div>
  );
}
