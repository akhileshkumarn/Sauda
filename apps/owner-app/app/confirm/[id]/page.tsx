import type { Metadata } from 'next';
import { AuthGate } from '@/components/AuthGate';
import { ConfirmView } from '@/components/ConfirmView';
import { PageHead, Steps } from '@/components/ui';
import { RESTOCK_STEPS } from '@/components/restock/steps';

export const metadata: Metadata = { title: 'Approve your cart' };

export default async function ConfirmPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <div className="narrow">
      <AuthGate>
        <PageHead crumbs={[{ href: '/restock', label: 'Restock' }, { label: 'Approve' }]} title="Approve your cart" description="Nothing is ordered until you approve." />
        <Steps steps={RESTOCK_STEPS} current={3} label="Restock progress" />
        <ConfirmView id={decodeURIComponent(id)} />
      </AuthGate>
    </div>
  );
}
