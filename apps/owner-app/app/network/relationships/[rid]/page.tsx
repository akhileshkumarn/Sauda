import { Suspense } from 'react';
import { AuthGate } from '@/components/AuthGate';
import { RelationshipView } from '@/components/network/RelationshipView';
import { Skeleton } from '@/components/ui';

export const metadata = { title: 'Trading relationship' };
export default async function RelationshipPage({ params }: { params: Promise<{ rid: string }> }) {
  const { rid } = await params;
  return <AuthGate><Suspense fallback={<Skeleton lines={6} />}><RelationshipView rid={decodeURIComponent(rid)} /></Suspense></AuthGate>;
}
