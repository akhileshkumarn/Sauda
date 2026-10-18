'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { categoryWord, counterpartyOf, listInvitations, listRelationships, myBusinesses, pickBusiness, relWord, rememberBid, useIsReviewer } from '@/lib/network';
import { relTime } from '@/lib/format';
import { useAsync } from '@/lib/useAsync';
import type { TnBusinessMine, TnRelationship } from '@/lib/types';
import { ButtonLink, EmptyState, ErrorState, Icon, SectionHead, Skeleton, StatusPill } from '../ui';
import { SegmentedControl } from '../ui-client';
import { NIcon, SimulatedNote, hasSimulated } from './shared';

export function NetworkHome() {
  const mine = useAsync(() => myBusinesses(), []);
  const [bid, setBid] = useState<string | null>(null);
  useEffect(() => { if (mine.data) setBid(pickBusiness(mine.data)?.bid || null); }, [mine.data]);
  const biz = mine.data?.find((b) => b.bid === bid) || null;
  const reviewer = useIsReviewer();

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
      {biz && <BusinessCard b={biz} />}
      {biz && <Relationships biz={biz} />}
      {reviewer && (
        <section>
          <SectionHead title="Reviewer" />
          <Link href="/review" className="rowlink" style={{ borderTop: '1px solid var(--line)' }}>
            <div className="grow stack xs"><span className="strong">Review console</span><span className="small muted">Businesses waiting for a human check</span></div>
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
      <EmptyState icon="shield" title="Verify your business"
        action={<div className="stack sm" style={{ width: '100%', maxWidth: 320 }}>
          <ButtonLink href="/network/onboard?role=buyer" block>Verify my business</ButtonLink>
          <ButtonLink href="/network/onboard?role=seller" variant="secondary" block>Verify my supplier business</ButtonLink>
        </div>}>
        About five minutes. Sauda checks what it can against official or authorised sources and tells you plainly what is still self-declared. We never ask for Aadhaar.
      </EmptyState>
    </div>
  );
}

function BusinessCard({ b }: { b: TnBusinessMine }) {
  const s = b.summary;
  const w = categoryWord(s?.category, b.roles);
  const outstanding = s?.outstanding?.length || 0;
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
      {s?.next_step && <p className="small muted">{s.next_step}</p>}
      {(b.is_fixture || hasSimulated(s?.dimensions)) && <SimulatedNote>This sample business uses demo records, not live government lookups.</SimulatedNote>}
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
  { key: 'closed', title: 'Declined', states: ['declined'] },
];

function Relationships({ biz }: { biz: TnBusinessMine }) {
  const rels = useAsync(() => listRelationships(biz.bid), [biz.bid]);
  const invs = useAsync(() => listInvitations(biz.bid).catch(() => []), [biz.bid]);
  const isSeller = biz.roles.includes('seller');
  const isBuyer = biz.roles.includes('buyer') || !isSeller;
  const invites = (
    <div className="stack sm">
      {isBuyer && <Link href={`/network/invite?role=seller&bid=${encodeURIComponent(biz.bid)}`} className="rowlink" style={{ borderTop: '1px solid var(--line)' }}>
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
      {GROUPS.map((g) => {
        const rows = all.filter((r) => g.states.includes(r.state));
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
