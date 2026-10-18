'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { DEFAULT_NEGOTIATION_ID, MOCK, SHOP_ID } from '@/lib/api';
import { lastNegotiationId } from '@/lib/session';
import { Icon } from './ui';
import { ProfileMenu } from './ProfileMenu';
import { BrandMark } from './BrandMark';

type Tab = { href: string; label: string; icon: string; match: (p: string) => boolean };

const inTrust = (p: string) => p.startsWith('/trust') || p.startsWith('/attack') || p.startsWith('/savings');

export function Nav() {
  const path = usePathname() || '/';
  const [nid, setNid] = useState(DEFAULT_NEGOTIATION_ID);
  useEffect(() => { setNid(lastNegotiationId() || DEFAULT_NEGOTIATION_ID); }, [path]);
  const trustHref = nid ? `/trust/${encodeURIComponent(nid)}` : '/trust/latest';
  const tabs: Tab[] = [
    { href: '/', label: 'Home', icon: 'home', match: (p) => p === '/' },
    { href: '/restock', label: 'Restock', icon: 'cart', match: (p) => p.startsWith('/restock') || p.startsWith('/mandate') || p.startsWith('/confirm') },
    { href: '/orders', label: 'Orders', icon: 'box', match: (p) => p.startsWith('/orders') || p.startsWith('/pay') },
    { href: trustHref, label: 'Trust', icon: 'shield', match: inTrust },
  ];
  const sub = [
    { href: trustHref, label: 'Record', match: (p: string) => p.startsWith('/trust') },
    { href: '/attack', label: 'Security tests', match: (p: string) => p.startsWith('/attack') },
    { href: `/savings/${SHOP_ID}`, label: 'Savings', match: (p: string) => p.startsWith('/savings') },
  ];
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="topbar-in">
          <Link href="/" className="brand" aria-label="Sauda home">
            <BrandMark size={28} />
            <span>Sauda</span>
          </Link>
          <nav className="topnav" aria-label="Main">
            {tabs.map((t) => (
              <Link key={t.label} href={t.href} aria-current={t.match(path) ? 'page' : undefined}>
                <Icon name={t.icon} size={16} />{t.label}
              </Link>
            ))}
          </nav>
          <span className="spacer" />
          {MOCK && <span className="mock-tag" title="NEXT_PUBLIC_MOCK=1: sample data, no backend"><span className="dot warn" aria-hidden />Sample data</span>}
          <ProfileMenu />
        </div>
      </header>
      {inTrust(path) && (
        <div className="subtabs-wrap">
          <nav className="subtabs" aria-label="Trust">
            {sub.map((t) => <Link key={t.label} href={t.href} aria-current={t.match(path) ? 'page' : undefined}>{t.label}</Link>)}
          </nav>
        </div>
      )}
      <nav className="tabbar" aria-label="Main">
        {tabs.map((t) => (
          <Link key={t.label} href={t.href} aria-current={t.match(path) ? 'page' : undefined}>
            <span className="tab-ico"><Icon name={t.icon} size={22} stroke={1.5} /></span>
            <span>{t.label}</span>
          </Link>
        ))}
      </nav>
    </>
  );
}
