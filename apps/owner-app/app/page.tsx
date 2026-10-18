import { redirect } from 'next/navigation';
import { Landing } from '@/components/landing/Landing';

/** Public product page. Signed-in visitors see it too, with an "Open your dashboard" button. */
export default async function Home({ searchParams }: { searchParams: Promise<{ run?: string }> }) {
  const { run } = await searchParams;
  if (run) redirect(`/restock?run=${encodeURIComponent(run)}`); // old links
  return <Landing />;
}
