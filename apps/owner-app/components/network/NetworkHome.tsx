'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { categoryWord, counterpartyOf, listInvitations, listRelationships, myBusinesses, outstandingWord, pickBusiness, relWord, rememberBid, useReviewerMode } from '@/lib/network';
import { relTime } from '@/lib/format';
import { useAsync } from '@/lib/useAsync';
import type { TnBusinessMine, TnRelationship } from '@/lib/types';
import { ButtonLink, EmptyState, ErrorState, Icon, SectionHead, Skeleton, StatusPill } from '../ui';
import { SegmentedControl } from '../ui-client';
import { NIcon } from './shared';
import { IncomingRequests } from './IncomingRequests';
import { SampleBanner, SampleShopButton } from './SampleShop';

export function NetworkHome() {
  const mine = useAsync(() => myBusinesses(), []);
  const [bid, setBid] = useState<string | null>(null);
  useEffect(() => { if (mine.data) setBid(pickBusiness(mine.data)?.bid || null); }, [mine.data]);
  const biz = mine.data?.find((b) => b.bid === bid) || null;
  const rv = useReviewerMode();

  return (
    <div className="narrow">
      <div className="page-head">
        <h1>Network</h1>
        <p>Verify your business once, then invite the suppliers and buyers you already trade with.</p>
      </div>
      {mine.loading && !mine.data && <Skeleton lines={5} />}
      {mine.error && !mine.data ? <ErrorState error={mine.error} onRetry={mine.reload} title="Could not load your network" /> : null}
      {mine.data && mine.data.length === 0 && <StartCard />}
      {mine.data && mine.data.length > 1 && bid && (
        <div className="row sm wrap">
          <span className="small muted">Showing</span>
          <SegmentedControl label="Your businesses" value={bid} options={mine.data.map((b) => ({ value: b.bid, label: b.display_name.length > 22 ? b.display_name.slice(0, 20) + '…' : b.display_name }))}
            onChange={(v) => { setBid(v); rememberBid(v); }} />
        </div>
      )}
      {biz?.sandbox && <SampleBanner onChanged={mine.reload} />}
      {biz && <BusinessCard b={biz} />}
      {biz && <Relationships biz={biz} />}
      {(
        <section>
          <SectionHead title={rv.reviewer ? 'Reviewer' : 'Review'} />
          <Link href="/review" className="rowlink" style={{ borderTop: '1px solid var(--line)' }}>
            <div className="grow stack xs"><span className="strong">Review console</span><span className="small muted">{rv.reviewer ? 'Businesses waiting for a human check' : 'Review your ready shop and the showcase businesses. Real businesses are reviewed by the Sauda team.'}</span></div>
            <span className="chev-ico"><Icon name="chev" size={16} /></span>
          </Link>
        </section>
      )}
    </div>
  );
}

function StartCard() {
  return (
    <div className="stack">
      <EmptyState icon="shield" title="Set up your business on Sauda"
        action={<div className="stack sm" style={{ width: '100%', maxWidth: 340 }}>
          <ButtonLink href="/network/onboard/voice" icon="mic" block>Talk to set up my business</ButtonLink>
          <ButtonLink href="/network/onboard?role=buyer" variant="secondary" block>Fill in a form</ButtonLink>
          <SampleShopButton block variant="secondary" />
          <ButtonLink href="/network/discover" variant="ghost" block>Just browse suppliers</ButtonLink>
        </div>}>
        About five minutes by voice or form. Sauda checks what it can against official or authorised sources and tells you plainly what is still self-declared. We never ask for Aadhaar.
        Or explore a ready shop: Balaji Kirana & General Stores, set up and partially verified. Your copy is private to you.
      </EmptyState>
    </div>
  );
}

function BusinessCard({ b }: { b: TnBusinessMine }) {
  const s = b.summary;
  const w = categoryWord(s?.category, b.roles, b.sandbox);
  const outstanding = s?.outstanding?.length || 0;
  const next = b.sandbox ? (s?.next_step || '').replace(/\s*Upload a document that shows the correct name or number\.?/, '').trim() : s?.next_step;
  return (
    <section className="bizcard" aria-label="Your business">
      <div className="row between top wrap sm">
        <div className="stack xs grow">
          <h2>{b.display_name}</h2>
          <div className="facts">
            <span>{b.roles.map((r) => (r === 'buyer' ? 'Buyer' : 'Supplier')).join(' and ')}</span>
            {(b.address?.city || b.address?.state) && <span>{[b.address.city, b.address.state].filter(Boolean).join(', ')}</span>}
            {b.gstin && <span className="num">GSTIN {b.gstin}</span>}
          </div>
        </div>
      </div>
      {s ? <StatusPill tone={w.tone} size="lg">{w.label}</StatusPill> : <StatusPill tone="neutral">Not checked yet</StatusPill>}
      {s && w.tone !== 'ok' && <div className="stack xs"><p>Nothing is blocked. You can find suppliers, send requests and restock now.</p><p className="small muted">Credit and large orders wait for a reviewer.</p></div>}
      {s && s.outstanding && s.outstanding.length > 0 ? (
        <div className="stack xs" aria-labelledby={`todo-${b.bid}`}>
          <p className="strong small" id={`todo-${b.bid}`}>How to get fully verified</p>
          <ul className="plain-list">
            {s.outstanding.slice(0, 5).map((code) => {
              const o = outstandingWord(code);
              const act = o.action === 'upload' ? 'Upload' : o.action === 'location' ? 'Share location' : o.action === 'review' ? 'Ask a reviewer' : 'Open';
              return (
                <li key={code} className="row sm between wrap">
                  <span className="small">{o.label}</span>
                  <Link className="small" href={`/network/business/${encodeURIComponent(b.bid)}`}>{act}</Link>
                </li>
              );
            })}
          </ul>
        </div>
      ) : next && <p className="small muted">{next}</p>}
      <div className="row sm wrap">
        <ButtonLink href={`/network/business/${encodeURIComponent(b.bid)}`} size="sm">{outstanding ? `See verification · ${outstanding} to do` : 'See verification'}</ButtonLink>
        <ButtonLink href={`/network/business/${encodeURIComponent(b.bid)}/profile`} size="sm" variant="secondary">What others see</ButtonLink>
      </div>
    </section>
  );
}

const GROUPS: { key: string; title: string; states: string[] }[] = [
  { key: 'ok', title: 'Approved for trading', states: ['approved_for_trading'] },
  { key: 'prog', title: 'In progress', states: ['accepted', 'onboarding', 'under_review', 'paused'] },
  { key: 'inv', title: 'Invited', states: ['invited'] },
  { key: 'req', title: 'Requests sent', states: ['requested'] },
  { key: 'closed', title: 'Declined', states: ['declined'] },
];

function Relationships({ biz }: { biz: TnBusinessMine }) {
  const rels = useAsync(() => listRelationships(biz.bid), [biz.bid]);
  const invs = useAsync(() => listInvitations(biz.bid).catch(() => []), [biz.bid]);
  const isSeller = biz.roles.includes('seller');
  const isBuyer = biz.roles.includes('buyer') || !isSeller;
  const invites = (
    <div className="stack sm">
      {isBuyer && <Link href="/network/discover" className="rowlink" style={{ borderTop: '1px solid var(--line)' }}>
        <span className="none" style={{ color: 'var(--accent)' }}><Icon name="shield" size={18} /></span>
        <div className="grow stack xs"><span className="strong">Find verified suppliers</span><span className="small muted">Listed suppliers who deliver to your area</span></div>
        <span className="chev-ico"><Icon name="chev" size={16} /></span>
      </Link>}
      {isBuyer && <Link href={`/network/invite?role=seller&bid=${encodeURIComponent(biz.bid)}`} className="rowlink">
        <span className="none" style={{ color: 'var(--accent)' }}><Icon name="plus" size={18} /></span>
        <div className="grow stack xs"><span className="strong">Invite a supplier</span><span className="small muted">Distributors and wholesalers you already buy from</span></div>
        <span className="chev-ico"><Icon name="chev" size={16} /></span>
      </Link>}
      <Link href={`/network/invite?role=buyer&bid=${encodeURIComponent(biz.bid)}`} className="rowlink" style={isBuyer ? undefined : { borderTop: '1px solid var(--line)' }}>
        <span className="none" style={{ color: 'var(--accent)' }}><Icon name="plus" size={18} /></span>
        <div className="grow stack xs"><span className="strong">Invite a buyer</span><span className="small muted">Shops that buy from you</span></div>
        <span className="chev-ico"><Icon name="chev" size={16} /></span>
      </Link>
    </div>
  );
  if (rels.loading && !rels.data) return <Skeleton lines={4} />;
  if (rels.error && !rels.data) return <><ErrorState error={rels.error} onRetry={rels.reload} title="Could not load your trading relationships" />{invites}</>;
  const all = rels.data || [];
  const open = (invs.data || []).filter((i) => i.status === 'sent');
  return (
    <>
      {all.length === 0 && open.length === 0 && <EmptyState icon="link" title="No trading relationships yet">Invite the businesses you already trade with. They verify themselves; each of you decides whether to trade.</EmptyState>}
      <IncomingRequests rels={all} myBid={biz.bid} onChange={rels.reload} />
      {GROUPS.map((g) => {
        const rows = all.filter((r) => g.states.includes(r.state) && !(r.state === 'requested' && r.seller_bid === biz.bid));
        if (!rows.length) return null;
        return (
          <section key={g.key} aria-label={g.title}>
            <SectionHead title={`${g.title} · ${rows.length}`} />
            <div className="list">{rows.map((r) => <RelRow key={r.rid} r={r} myBid={biz.bid} />)}</div>
          </section>
        );
      })}
      {open.length > 0 && (
        <section aria-label="Invited">
          <SectionHead title={`Invited · ${open.length}`} href={`/network/invite?role=${open[0].role_invited}&bid=${encodeURIComponent(biz.bid)}`} linkText="Manage" />
          <div className="list">
            {open.map((i) => (
              <div key={i.iid} className="rowlink">
                <span className="avatar" aria-hidden><NIcon name={i.role_invited === 'seller' ? 'box' : 'cart'} size={14} /></span>
                <div className="grow stack xs">
                  <span className="strong break">{i.display_name_hint || i.display_name || i.contact_masked}</span>
                  <span className="small muted row sm wrap" style={{ rowGap: 0 }}><StatusPill tone="neutral">Invited, waiting for them</StatusPill><span>{i.role_invited === 'seller' ? 'Supplier' : 'Buyer'}</span>{i.categories?.length ? <span>{i.categories.join(', ')}</span> : null}{i.created_at && <span>{relTime(i.created_at)}</span>}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
      <section aria-label="Invite">
        <SectionHead title="Grow your network" />
        {invites}
      </section>
    </>
  );
}

function RelRow({ r, myBid }: { r: TnRelationship; myBid: string }) {
  const cp = counterpartyOf(r, myBid);
  const w = relWord(r.state);
  const last = r.history?.[r.history.length - 1]?.at || r.updated_at || r.created_at;
  return (
    <Link href={`/network/relationships/${encodeURIComponent(r.rid)}?bid=${encodeURIComponent(myBid)}`} className="rowlink">
      <span className="avatar" aria-hidden><NIcon name={cp.role === 'seller' ? 'box' : 'cart'} size={14} /></span>
      <div className="grow stack xs">
        <span className="strong break">{cp.name}</span>
        <span className="small muted row sm wrap" style={{ rowGap: 0 }}>
          <StatusPill tone={w.tone}>{w.label}</StatusPill>
          <span>{cp.role === 'seller' ? 'Supplier' : 'Buyer'}</span>
          {r.categories?.length ? <span className="break">{r.categories.join(', ')}</span> : null}
          {last && <span>{relTime(last)}</span>}
        </span>
      </div>
      <span className="chev-ico"><Icon name="chev" size={16} /></span>
    </Link>
  );
}
