import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { AuthGate } from '@/components/AuthGate';
import { HomeView } from '@/components/HomeView';

export const metadata: Metadata = { title: 'Dashboard' };

export default async function Dashboard({ searchParams }: { searchParams: Promise<{ run?: string }> }) {
  const { run } = await searchParams;
  if (run) redirect(`/restock?run=${encodeURIComponent(run)}`); // old links
  return <AuthGate><HomeView /></AuthGate>;
}
