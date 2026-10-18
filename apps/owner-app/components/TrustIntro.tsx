// Shared frame for the three Trust pages (Record, Security tests, Savings).
// Each page answers: what is this, why it matters, what am I looking at, how it was obtained, what can I do, what if I ignore it.
import Link from 'next/link';
import type { ReactNode } from 'react';
import { SHOP_ID } from '@/lib/api';
import { Icon, PageHead, type IconName } from './ui';

export interface Guide { looking: ReactNode; obtained: ReactNode; act: ReactNode; ignore: ReactNode }

export function TrustIntro({ title, lede, guide }: { eyebrow?: string; title: ReactNode; lede: ReactNode; guide: Guide }) {
  return (
    <div className="tz-intro">
      <PageHead title={title} description={lede} />
      <details className="tz-guide">
        <summary><Icon name="info" size={16} /><span className="grow">How to read this page</span><span className="chev" aria-hidden><Icon name="chev" size={14} /></span></summary>
        <dl>
          <div><dt>What you are looking at</dt><dd>{guide.looking}</dd></div>
          <div><dt>How it was obtained</dt><dd>{guide.obtained}</dd></div>
          <div><dt>What you can do</dt><dd>{guide.act}</dd></div>
          <div><dt>If you ignore it</dt><dd>{guide.ignore}</dd></div>
        </dl>
      </details>
    </div>
  );
}

type Area = 'record' | 'attack' | 'savings' | 'network';
const AREAS: { key: Area; href: (nid?: string) => string; icon: IconName; title: string; body: string }[] = [
  { key: 'record', href: (nid) => (nid ? `/trust/${encodeURIComponent(nid)}` : '/trust/latest'), icon: 'shield', title: 'Signed record', body: 'Every step of a restock, signed and checkable.' },
  { key: 'attack', href: () => '/attack', icon: 'flask', title: 'Security tests', body: 'Controlled tests of the tricks Sauda blocks.' },
  { key: 'savings', href: () => `/savings/${encodeURIComponent(SHOP_ID)}`, icon: 'chart', title: 'Savings', body: 'What you paid against the opening quotes.' },
  { key: 'network', href: () => '/network', icon: 'user', title: 'Network verification', body: 'Who your trading partners are, and how that was checked.' },
];

/** "Related" links that connect the Trust pages to each other and to Network. */
export function TrustLinks({ current, nid }: { current: Area; nid?: string }) {
  return (
    <nav className="tz-links" aria-label="Related trust pages">
      <h2 className="tz-links-h">Related</h2>
      <ul>
        {AREAS.filter((a) => a.key !== current).map((a) => (
          <li key={a.key}>
            <Link href={a.href(nid)}>
              <span className="tz-ico" aria-hidden><Icon name={a.icon} size={16} /></span>
              <span className="tz-lt"><b>{a.title}</b><span>{a.body}</span></span>
              <Icon name="chev" size={16} />
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
