import { Suspense } from 'react';
import { AuthGate } from '@/components/AuthGate';
import { BusinessView } from '@/components/network/BusinessView';
import { Skeleton } from '@/components/ui';

export const metadata = { title: 'Business verification' };
export default async function BusinessPage({ params }: { params: Promise<{ bid: string }> }) {
  const { bid } = await params;
  return <AuthGate><Suspense fallback={<Skeleton lines={6} />}><BusinessView bid={decodeURIComponent(bid)} /></Suspense></AuthGate>;
}
