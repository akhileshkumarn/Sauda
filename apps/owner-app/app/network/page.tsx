import { AuthGate } from '@/components/AuthGate';
import { NetworkHome } from '@/components/network/NetworkHome';

export const metadata = { title: 'Network' };
export default function NetworkPage() {
  return <AuthGate><NetworkHome /></AuthGate>;
}
