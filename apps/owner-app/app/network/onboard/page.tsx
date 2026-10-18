import { Suspense } from 'react';
import { AuthGate } from '@/components/AuthGate';
import { Onboard } from '@/components/network/Onboard';
import { Skeleton } from '@/components/ui';

export const metadata = { title: 'Verify your business' };
export default function OnboardPage() {
  return <AuthGate><Suspense fallback={<Skeleton lines={6} />}><Onboard /></Suspense></AuthGate>;
}
