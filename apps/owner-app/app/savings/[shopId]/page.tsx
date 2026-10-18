import { MetricCards } from '@/components/MetricCards';

export default async function SavingsPage({ params }: { params: Promise<{ shopId: string }> }) {
  const { shopId } = await params;
  return (
    <div className="narrow">
      <MetricCards shopId={decodeURIComponent(shopId)} />
      <p className="attrib">Product data: Open Food Facts (ODbL) · Mandi prices: data.gov.in</p>
    </div>
  );
}
