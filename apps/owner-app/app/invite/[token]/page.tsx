import { InviteLanding } from '@/components/network/InviteLanding';

// Public landing page: no AuthGate. Sign-in happens inside, only when accepting.
export const metadata = { title: 'Invitation', robots: { index: false, follow: false } };
export default async function InviteTokenPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <InviteLanding token={decodeURIComponent(token)} />;
}
