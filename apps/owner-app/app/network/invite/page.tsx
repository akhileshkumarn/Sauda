import { Suspense } from 'react';
import { AuthGate } from '@/components/AuthGate';
import { InviteView } from '@/components/network/InviteView';
import { Skeleton } from '@/components/ui';

export const metadata = { title: 'Invite' };
export default function InvitePage() {
  return <AuthGate><Suspense fallback={<Skeleton lines={6} />}><InviteView /></Suspense></AuthGate>;
}
