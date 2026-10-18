import type { Metadata } from 'next';
import { AuthGate } from '@/components/AuthGate';
import { MandateCard } from '@/components/MandateCard';
import { PageHead, Steps } from '@/components/ui';
import { RESTOCK_STEPS } from '@/components/restock/steps';

export const metadata: Metadata = { title: 'Your limits' };

export default async function MandatePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ new?: string; sid?: string }> }) {
  const { id } = await params;
  const { new: isNew, sid } = await searchParams;
  return (
    <div className="narrow">
      <AuthGate>
        <PageHead crumbs={[{ href: '/restock', label: 'Restock' }, ...(sid ? [{ href: `/restock/${encodeURIComponent(sid)}`, label: 'This restock' }] : []), { label: 'Your limits' }]}
          title="Your limits" description="Sauda can only act inside these. Switch them off at any time." />
        <Steps steps={RESTOCK_STEPS} current={2} label="Restock progress" />
        <MandateCard id={decodeURIComponent(id)} justSigned={isNew === '1'} sid={sid} />
      </AuthGate>
    </div>
  );
}
