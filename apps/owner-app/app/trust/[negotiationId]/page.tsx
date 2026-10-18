import { TrustConsole } from '@/components/TrustConsole';
import { Evidence, PLAN_B, SUPPLIER_DISCLOSURE } from '@/components/ui';

export default async function TrustPage({ params }: { params: Promise<{ negotiationId: string }> }) {
  const { negotiationId } = await params;
  return (
    <div className="narrow">
      <TrustConsole negotiationId={decodeURIComponent(negotiationId)} />
      <Evidence label="About this data">
          <span>Every step is written to a tamper-evident record signed with Cloud KMS. Anyone can check it; no sign-in needed.</span>
          <span>{PLAN_B}</span>
          <span>{SUPPLIER_DISCLOSURE}</span>
          <span>Product data: Open Food Facts (ODbL) · Mandi prices: data.gov.in</span>
      </Evidence>
    </div>
  );
}
