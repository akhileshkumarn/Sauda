'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { DEFAULT_NEGOTIATION_ID, MOCK, SHOP_ID } from '@/lib/api';
import { lastNegotiationId } from '@/lib/session';
import { Icon } from './ui';
import { ProfileMenu } from './ProfileMenu';
import { Wordmark } from './BrandMark';
import { useReviewerMode } from '@/lib/network';

type Item = { href: string; label: string; match: (p: string) => boolean };
type Tab = Item & { icon: string; sub?: Item[] };

const inNetwork = (p: string) => p.startsWith('/network') || p.startsWith('/review') || p.startsWith('/invite');
const inTrust = (p: string) => p.startsWith('/trust') || p.startsWith('/attack') || p.startsWith('/savings');

/**
 * App shell navigation.
 * Desktop (>= 900px): a left sidebar with the five task areas, their sub-areas nested
 * underneath, and the shop, theme and profile controls at the foot.
 * Mobile: a slim top bar (mark, sample-data tag, profile), sub-area tabs for Trust and
 * Network, and a bottom tab bar.
 */
export function Nav() {
  const path = usePathname() || '/';
  const [nid, setNid] = useState(DEFAULT_NEGOTIATION_ID);
  useEffect(() => { setNid(lastNegotiationId() || DEFAULT_NEGOTIATION_ID); }, [path]);
  const rv = useReviewerMode();
  const trustHref = nid ? `/trust/${encodeURIComponent(nid)}` : '/trust/latest';

  const trustSub: Item[] = [
    { href: trustHref, label: 'Record', match: (p) => p.startsWith('/trust') },
    { href: '/attack', label: 'Security tests', match: (p) => p.startsWith('/attack') },
    { href: `/savings/${SHOP_ID}`, label: 'Savings', match: (p) => p.startsWith('/savings') },
  ];
  const networkSub: Item[] | undefined = [
    { href: '/network', label: 'My network', match: (p) => p.startsWith('/network') || p.startsWith('/invite') },
    { href: '/review', label: rv.reviewer ? 'Review' : 'Review', match: (p) => p.startsWith('/review') },
  ];
  const tabs: Tab[] = [
    { href: '/dashboard', label: 'Home', icon: 'home', match: (p) => p === '/dashboard' },
    { href: '/restock', label: 'Restock', icon: 'cart', match: (p) => p.startsWith('/restock') || p.startsWith('/mandate') || p.startsWith('/confirm') },
    { href: '/orders', label: 'Orders', icon: 'box', match: (p) => p.startsWith('/orders') || p.startsWith('/pay') },
    { href: '/network', label: 'Network', icon: 'link', match: inNetwork, sub: networkSub },
    { href: trustHref, label: 'Trust', icon: 'shield', match: inTrust, sub: trustSub },
  ];
  const cur = (m: boolean) => (m ? 'page' as const : undefined);
  const mobileSub = inTrust(path) ? { label: 'Trust', items: trustSub } : networkSub && inNetwork(path) ? { label: 'Network', items: networkSub } : null;

  if (path === '/') return null; // the public landing page has its own header

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>

      {/* desktop sidebar */}
      <aside className="sidebar" aria-label="Sauda">
        <Link href="/dashboard" className="brand sb-brand" aria-label="Sauda home">
          <Wordmark height={22} />
        </Link>
        <Link href="/network" className="sb-shop" title="Business profile and verification">
          <span className="sb-shop-k">Shop</span>
          <span className="sb-shop-v">{MOCK ? 'Your shop' : 'Your shop'}</span>
          <span className="sb-shop-go" aria-hidden><Icon name="chev" size={14} /></span>
        </Link>
        <nav className="sb-nav" aria-label="Main">
          <ul>
            {tabs.map((t) => {
              const on = t.match(path);
              return (
                <li key={t.label}>
                  <Link href={t.href} className="sb-item" aria-current={on ? (t.sub ? 'true' : 'page') : undefined}>
                    <Icon name={t.icon} size={18} stroke={1.6} />
                    <span>{t.label}</span>
                  </Link>
                  {t.sub && (on || t.label === 'Trust') && (
                    <ul className="sb-sub" aria-label={`${t.label} sections`}>
                      {t.sub.map((s) => (
                        <li key={s.label}><Link href={s.href} className="sb-subitem" aria-current={cur(s.match(path))}>{s.label}</Link></li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="sb-foot">
          {MOCK && <span className="mock-tag" title="NEXT_PUBLIC_MOCK=1: sample data, no backend"><span className="dot warn" aria-hidden />Sample data</span>}
          <ProfileMenu placement="up" />
        </div>
      </aside>

      {/* mobile top bar */}
      <header className="topbar">
        <div className="topbar-in">
          <Link href="/dashboard" className="brand" aria-label="Sauda home">
            <Wordmark height={20} />
          </Link>
          <span className="spacer" />
          {MOCK && <span className="mock-tag" title="NEXT_PUBLIC_MOCK=1: sample data, no backend"><span className="dot warn" aria-hidden />Sample data</span>}
          <ProfileMenu />
        </div>
      </header>
      {mobileSub && (
        <div className="subtabs-wrap">
          <nav className="subtabs" aria-label={mobileSub.label}>
            {mobileSub.items.map((t) => <Link key={t.label} href={t.href} aria-current={cur(t.match(path))}>{t.label}</Link>)}
          </nav>
        </div>
      )}

      {/* mobile bottom tab bar */}
      <nav className="tabbar" aria-label="Main" style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}>
        {tabs.map((t) => (
          <Link key={t.label} href={t.href} aria-current={cur(t.match(path))}>
            <span className="tab-ico"><Icon name={t.icon} size={22} stroke={1.5} /></span>
            <span>{t.label}</span>
          </Link>
        ))}
      </nav>
    </>
  );
}
