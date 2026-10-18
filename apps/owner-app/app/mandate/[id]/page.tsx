import { AuthGate } from '@/components/AuthGate';
import { MandateCard } from '@/components/MandateCard';
import { PageHead } from '@/components/ui';

export default async function MandatePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ new?: string; sid?: string }> }) {
  const { id } = await params;
  const { new: isNew, sid } = await searchParams;
  return (
    <div className="narrow">
      <PageHead eyebrow="Restock · step 2 of 4" title="Your limits" />
      <AuthGate><MandateCard id={decodeURIComponent(id)} justSigned={isNew === '1'} sid={sid} /></AuthGate>
    </div>
  );
}
