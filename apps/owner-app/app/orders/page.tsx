import { AuthGate } from '@/components/AuthGate';
import { OrdersView } from '@/components/OrdersView';
import { PageHead } from '@/components/ui';

export default function OrdersPage() {
  return (
    <div className="narrow">
      <PageHead eyebrow="Orders" title="Orders" />
      <AuthGate><OrdersView /></AuthGate>
    </div>
  );
}
