import { AuthGate } from '@/components/AuthGate';
import { ReviewTaskView } from '@/components/network/Review';

export const metadata = { title: 'Review task' };
export default async function ReviewTaskPage({ params }: { params: Promise<{ tid: string }> }) {
  const { tid } = await params;
  return <AuthGate><ReviewTaskView tid={decodeURIComponent(tid)} /></AuthGate>;
}
