import { AuthGate } from '@/components/AuthGate';
import { Discover } from '@/components/network/Discover';

export const metadata = { title: 'Find suppliers' };
export default function DiscoverPage() {
  return <AuthGate><Discover /></AuthGate>;
}
