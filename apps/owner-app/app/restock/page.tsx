import type { Metadata } from 'next';
import Link from 'next/link';
import { AuthGate } from '@/components/AuthGate';
import { ChatStream } from '@/components/ChatStream';
import { SessionList } from '@/components/restock/SessionList';

export const metadata: Metadata = { title: 'Restocks' };

/** /restock = history + New restock. /restock?run=<mandate> = the live negotiation view (unchanged). */
export default async function RestockPage({ searchParams }: { searchParams: Promise<{ run?: string; sid?: string }> }) {
  const { run, sid } = await searchParams;
  return (
    <div className="narrow">
      <AuthGate>
        {run ? (
          <>
            {sid && <Link href={`/restock/${encodeURIComponent(sid)}`} className="rf-back" style={{ alignSelf: 'flex-start' }}>Back to this restock</Link>}
            <ChatStream runMandateId={run} />
          </>
        ) : <SessionList />}
      </AuthGate>
    </div>
  );
}
