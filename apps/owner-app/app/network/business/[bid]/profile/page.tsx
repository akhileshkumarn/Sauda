import { Suspense } from 'react';
import { AuthGate } from '@/components/AuthGate';
import { ProfileView } from '@/components/network/ProfileView';
import { Skeleton } from '@/components/ui';

export const metadata = { title: 'Business profile' };
export default async function ProfilePage({ params }: { params: Promise<{ bid: string }> }) {
  const { bid } = await params;
  return <AuthGate><Suspense fallback={<Skeleton lines={6} />}><ProfileView bid={decodeURIComponent(bid)} /></Suspense></AuthGate>;
}
