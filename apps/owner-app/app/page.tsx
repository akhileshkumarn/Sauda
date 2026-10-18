import { redirect } from 'next/navigation';
import { AuthGate } from '@/components/AuthGate';
import { HomeView } from '@/components/HomeView';

export default async function Home({ searchParams }: { searchParams: Promise<{ run?: string }> }) {
  const { run } = await searchParams;
  if (run) redirect(`/restock?run=${encodeURIComponent(run)}`); // old links
  return <AuthGate><HomeView /></AuthGate>;
}
