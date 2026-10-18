import type { Metadata } from 'next';
import { AuthGate } from '@/components/AuthGate';
import { SessionView } from '@/components/restock/SessionView';

export const metadata: Metadata = { title: 'Restock' };

export default async function RestockSessionPage({ params }: { params: Promise<{ sid: string }> }) {
  const { sid } = await params;
  return (
    <div className="narrow">
      <AuthGate><SessionView sid={decodeURIComponent(sid)} /></AuthGate>
    </div>
  );
}
