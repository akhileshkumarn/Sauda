import { AuthGate } from '@/components/AuthGate';
import { VerifyContactReturn } from '@/components/network/VerifyContactReturn';

export const metadata = { title: 'Confirm business email' };
export default async function VerifyContactPage({ params }: { params: Promise<{ bid: string }> }) {
  const { bid } = await params;
  return <AuthGate><VerifyContactReturn bid={decodeURIComponent(bid)} /></AuthGate>;
}
