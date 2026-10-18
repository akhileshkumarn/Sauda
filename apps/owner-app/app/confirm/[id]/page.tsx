import type { Metadata } from 'next';
import { AuthGate } from '@/components/AuthGate';
import { ConfirmView } from '@/components/ConfirmView';
import { PageHead } from '@/components/ui';

export const metadata: Metadata = { title: 'Approve your cart' };

export default async function ConfirmPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <div className="narrow">
      <AuthGate>
        <PageHead eyebrow="Restock · step 3 of 4" title="Approve your cart">Nothing is ordered until you approve.</PageHead>
        <ConfirmView id={decodeURIComponent(id)} />
      </AuthGate>
    </div>
  );
}
