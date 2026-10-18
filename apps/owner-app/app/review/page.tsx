import { AuthGate } from '@/components/AuthGate';
import { ReviewQueue } from '@/components/network/Review';

export const metadata = { title: 'Review' };
export default function ReviewPage() {
  return <AuthGate><ReviewQueue /></AuthGate>;
}
