import { AuthGate } from '@/components/AuthGate';
import { PayView } from '@/components/PayView';
import { PageHead } from '@/components/ui';

export default async function PayPage({ params, searchParams }: { params: Promise<{ orderId: string }>; searchParams: Promise<{ more?: string }> }) {
  const { orderId } = await params;
  const { more } = await searchParams;
  return (
    <div className="narrow">
      <PageHead eyebrow="Restock · step 4 of 4" title="Pay" />
      <AuthGate><PayView orderId={decodeURIComponent(orderId)} more={more ? parseInt(more, 10) || 0 : 0} /></AuthGate>
    </div>
  );
}
