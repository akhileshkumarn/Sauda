'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { MOCK } from '@/lib/api';
import { AUTH_MODE, onUser, signInWithGoogle } from '@/lib/auth';
import { acceptInvitation, getInvitation, myBusinesses, rememberBid } from '@/lib/network';
import { useAsync } from '@/lib/useAsync';
import type { TnInvitationPublic, TnRelationship } from '@/lib/types';
import { Button, ButtonLink, Callout, EmptyState, ErrorState, Icon, Skeleton } from '../ui';
import { BrandMark } from '../BrandMark';
import './network.css';

export function InviteLanding({ token }: { token: string }) {
  const inv = useAsync(() => getInvitation(token), [token]);
  return (
    <div className="narrow">
      {inv.loading && !inv.data && <Skeleton lines={5} />}
      {inv.error && !inv.data ? (
        (inv.error as { status?: number }).status === 404 || (inv.error as { status?: number }).status === 410
          ? <EmptyState icon="link" title="This invitation is no longer valid">It may have expired or been withdrawn. Ask the business that invited you to send a new link.</EmptyState>
          : <ErrorState error={inv.error} onRetry={inv.reload} title="Could not open this invitation" />
      ) : null}
      {inv.data && <Body inv={inv.data} token={token} />}
    </div>
  );
}

function Body({ inv, token }: { inv: TnInvitationPublic; token: string }) {
  const as = inv.role_invited === 'seller' ? 'supplier' : 'buyer';
  const [user, setUser] = useState<{ name: string } | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (MOCK || AUTH_MODE === 'demo') { setUser({ name: 'Owner' }); return; }
    let off = () => {};
    onUser((u) => setUser(u)).then((f) => { off = f; }).catch(() => setUser(null));
    return () => off();
  }, []);
  const done = inv.status === 'accepted';
  return (
    <>
      <div className="tn-hero" style={{ paddingTop: 8 }}>
        <BrandMark size={40} />
        <h1>{inv.from_display_name} invited you to trade on Sauda</h1>
        <p className="muted">They would like to add you as a {as}. Verify your business once; both of you then decide whether to trade. Nothing is ordered or paid through this link.</p>
      </div>
      <ol className="plain-list" style={{ color: 'var(--ink)' }}>
        <li>Sign in with Google.</li>
        <li>Link a business you already have on Sauda, or verify a new one (about five minutes; no Aadhaar).</li>
        <li>{inv.from_display_name} reviews a summary of your verification. You see a summary of theirs.</li>
      </ol>
      {done && <Callout tone="neutral">This invitation has already been accepted.</Callout>}
      {user === undefined && <Skeleton lines={2} />}
      {user === null && (
        <div className="stack sm">
          <Button block busy={busy} busyLabel="Opening Google…" onClick={() => { setBusy(true); setErr(null); signInWithGoogle().catch((e) => setErr(String(e?.message || e))).finally(() => setBusy(false)); }}>Sign in with Google to continue</Button>
          {err && <Callout tone="bad" title="Sign-in did not finish.">{err}</Callout>}
        </div>
      )}
      {user && !done && <Accept token={token} as={inv.role_invited} from={inv.from_display_name} />}
      <p className="xs muted">Sauda shares only redacted verification summaries between businesses. Your documents and contacts stay private.</p>
    </>
  );
}

function Accept({ token, as, from }: { token: string; as: 'buyer' | 'seller'; from: string }) {
  const mine = useAsync(() => myBusinesses(), []);
  const [bid, setBid] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [rel, setRel] = useState<TnRelationship | null>(null);
  useEffect(() => { if (mine.data?.[0] && !bid) setBid(mine.data[0].bid); }, [mine.data, bid]);
  const onboard = `/network/onboard?role=${as}&return=${encodeURIComponent(`/invite/${token}`)}`;

  if (rel) {
    return (
      <div className="stack">
        <Callout tone="ok" title="Accepted.">You are connected with {from}. Finish any outstanding checks so they can approve trading.</Callout>
        <ButtonLink href={`/network/relationships/${encodeURIComponent(rel.rid)}?bid=${encodeURIComponent(bid)}`} block>See the relationship</ButtonLink>
      </div>
    );
  }
  if (mine.loading && !mine.data) return <Skeleton lines={3} />;
  if (mine.error && !mine.data) return <ErrorState error={mine.error} onRetry={mine.reload} title="Could not load your businesses" />;
  const list = mine.data || [];
  async function go() {
    if (!bid) return;
    setBusy(true); setErr(null);
    try { rememberBid(bid); setRel(await acceptInvitation(token, bid)); } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  return (
    <div className="stack">
      {list.length > 0 && (
        <fieldset className="tn-group">
          <legend>Accept as</legend>
          <div className="radio-cards">
            {list.map((b) => (
              <label key={b.bid} className="radio-card"><input type="radio" name="bid" checked={bid === b.bid} onChange={() => setBid(b.bid)} />
                <span><b>{b.display_name}</b><span className="d">{[b.address?.city, b.address?.state].filter(Boolean).join(', ')}</span></span></label>
            ))}
          </div>
          <Button block busy={busy} busyLabel="Accepting…" disabled={!bid} onClick={go}>Accept invitation</Button>
        </fieldset>
      )}
      {!!err && <Callout tone="bad">{err instanceof Error ? err.message : String(err)}</Callout>}
      <Link href={onboard} className="rowlink" style={{ borderTop: '1px solid var(--line)' }}>
        <span className="none" style={{ color: 'var(--accent)' }}><Icon name="plus" size={18} /></span>
        <div className="grow stack xs"><span className="strong">{list.length ? 'Verify a different business' : `Verify my ${as === 'seller' ? 'supplier ' : ''}business`}</span><span className="small muted">Then come back here to accept</span></div>
        <span className="chev-ico"><Icon name="chev" size={16} /></span>
      </Link>
    </div>
  );
}
