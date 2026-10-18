'use client';
import './network.css';
import './discover.css';
import Link from 'next/link';
import { useState } from 'react';
import { relTime } from '@/lib/format';
import { decideRelationship, errorDetail } from '@/lib/network';
import type { TnRelationship } from '@/lib/types';
import { Button, Callout, Icon, SectionHead } from '../ui';
import { NIcon } from './shared';

/** Requests to connect that buyers sent from Find suppliers, for the seller to accept or decline with a reason. */
export function IncomingRequests({ rels, myBid, onChange }: { rels: TnRelationship[]; myBid: string; onChange: () => void }) {
  const rows = rels.filter((r) => r.state === 'requested' && r.seller_bid === myBid);
  if (!rows.length) return null;
  return (
    <section aria-label="Incoming requests">
      <SectionHead title={`Incoming requests · ${rows.length}`} />
      <div className="list">{rows.map((r) => <RequestRow key={r.rid} r={r} myBid={myBid} onChange={onChange} />)}</div>
    </section>
  );
}

function RequestRow({ r, myBid, onChange }: { r: TnRelationship; myBid: string; onChange: () => void }) {
  const [mode, setMode] = useState<'accept' | 'decline' | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const name = r.buyer_display_name || r.buyer_name || 'A buyer';
  const req = r.request;
  const at = req?.at || r.created_at;
  async function decide() {
    if (!mode) return;
    setBusy(true); setErr(null);
    try {
      await decideRelationship(r.rid, mode === 'accept' ? 'accept_request' : 'decline', reason.trim(), 'prepaid_small', r.version);
      setDone(mode === 'accept' ? 'Accepted. Review their profile next.' : 'Declined.');
      setTimeout(onChange, 900);
    } catch (e) {
      const d = errorDetail(e);
      setErr(d.code === 'version_conflict' ? 'This request changed elsewhere. Reload to see it.' : e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }
  return (
    <div className="req-card">
      <div className="row sm top">
        <span className="avatar" aria-hidden><NIcon name="cart" size={14} /></span>
        <div className="grow stack xs" style={{ minWidth: 0 }}>
          <Link href={`/network/relationships/${encodeURIComponent(r.rid)}?bid=${encodeURIComponent(myBid)}`} className="strong break">{name}</Link>
          <span className="small muted row sm wrap" style={{ rowGap: 0 }}>
            <span>Buyer · found you in Find suppliers</span>
            {r.categories?.length ? <span className="break">{r.categories.join(', ')}</span> : null}
            {at && <span>{relTime(at)}</span>}
          </span>
        </div>
      </div>
      {req?.message && <div className="req-msg"><span className="k">Their message (unverified)</span>{req.message}</div>}
      {req?.message_blocked && <p className="xs muted">Their message was held back by the safety check.</p>}
      {done ? <Callout tone="ok">{done}</Callout> : mode ? (
        <div className="stack sm">
          <label className="field">
            <span>{mode === 'accept' ? 'Why are you accepting?' : 'Why are you declining?'}</span>
            <input className="input" value={reason} autoFocus onChange={(e) => setReason(e.target.value)}
              placeholder={mode === 'accept' ? 'For example: we deliver to their area' : 'For example: we do not deliver there'} />
            <span className="hint">The buyer sees your decision. Accepting starts onboarding; trading is approved separately after you review their profile.</span>
          </label>
          {err && <Callout tone="bad">{err}</Callout>}
          <div className="row sm wrap">
            <Button size="sm" variant={mode === 'decline' ? 'danger' : 'primary'} busy={busy} busyLabel="Saving…" disabled={reason.trim().length < 3} onClick={decide}>
              {mode === 'accept' ? 'Accept request' : 'Decline request'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setMode(null); setReason(''); setErr(null); }}>Cancel</Button>
          </div>
        </div>
      ) : (
        <div className="row sm wrap">
          <Button size="sm" onClick={() => setMode('accept')}><Icon name="check" size={14} />Accept</Button>
          <Button size="sm" variant="secondary" onClick={() => setMode('decline')}>Decline</Button>
        </div>
      )}
    </div>
  );
}
