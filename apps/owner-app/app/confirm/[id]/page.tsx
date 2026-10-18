import { AuthGate } from '@/components/AuthGate';
import { ConfirmView } from '@/components/ConfirmView';
import { PageHead } from '@/components/ui';

export default async function ConfirmPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <div className="narrow">
      <PageHead eyebrow="Restock · step 3 of 4" title="Approve your cart">Nothing is ordered until you approve.</PageHead>
      <AuthGate><ConfirmView id={decodeURIComponent(id)} /></AuthGate>
    </div>
  );
}
