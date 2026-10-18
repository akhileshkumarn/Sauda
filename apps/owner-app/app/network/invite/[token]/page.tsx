import { InviteLanding } from '@/components/network/InviteLanding';

// The backend's share links point here; same public landing page as /invite/[token].
export const metadata = { title: 'Invitation', robots: { index: false, follow: false } };
export default async function NetworkInviteTokenPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <InviteLanding token={decodeURIComponent(token)} />;
}
