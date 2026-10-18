'use client';
import Link from 'next/link';
import { categoryWord, myBusinesses, pickBusiness } from '@/lib/network';
import { useAsync } from '@/lib/useAsync';
import { Icon, SectionHead, StatusPill } from '../ui';

/** Home entry card: "Verify my business", or the business's status once it exists. Hidden on error. */
export function VerifyEntry() {
  const q = useAsync(() => myBusinesses(), []);
  if (!q.data) return null;
  const b = pickBusiness(q.data);
  const w = b ? categoryWord(b.summary?.category, b.roles) : null;
  return (
    <section>
      <SectionHead title="Network" href="/network" linkText="Open" />
      <Link href={b ? `/network/business/${encodeURIComponent(b.bid)}` : '/network/onboard?role=buyer'} className="rowlink" style={{ borderTop: '1px solid var(--line)' }}>
        <span className="none" style={{ color: 'var(--accent)' }}><Icon name="shield" size={18} /></span>
        <div className="grow stack xs">
          <span className="strong break">{b ? b.display_name : 'Verify my business'}</span>
          {b && w ? <span className="small muted row sm wrap" style={{ rowGap: 0 }}><StatusPill tone={w.tone}>{w.label}</StatusPill></span>
            : <span className="small muted">So suppliers can check who you are before they trade with you. About five minutes; no Aadhaar.</span>}
        </div>
        <span className="chev-ico"><Icon name="chev" size={16} /></span>
      </Link>
    </section>
  );
}
