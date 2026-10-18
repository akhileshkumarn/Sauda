import { Suspense } from 'react';
import { AuthGate } from '@/components/AuthGate';
import { VoiceOnboard } from '@/components/network/VoiceOnboard';
import { Skeleton } from '@/components/ui';

export const metadata = { title: 'Set up by voice' };
export default function VoiceOnboardPage() {
  return <AuthGate><Suspense fallback={<Skeleton lines={6} />}><VoiceOnboard /></Suspense></AuthGate>;
}
