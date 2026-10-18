'use client';
import './network.css';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { ApiError } from '@/lib/api';
import { ist } from '@/lib/format';
import { TIER_WORD, counterpartyOf, decideRelationship, errorDetail, getRelationship, readinessList, relWord, requirementWord, type RelAction } from '@/lib/network';
import { useAsync } from '@/lib/useAsync';
import type { TnRelationship, TnRelState } from '@/lib/types';
import { Button, ButtonLink, Callout, ErrorState, Icon, SectionHead, Skeleton, StatusPill, Timeline, type Step } from '../ui';

const FLOW: TnRelState[] = ['invited', 'accepted', 'onboarding', 'under_review', 'approved_for_trading'];
const STATE_HELP: Record<string, string> = {
  invited: 'Invitation link created. Waiting for them to open it.',
  accepted: 'They accepted and linked a business.',
  onboarding: 'They are verifying their business.',
  under_review: 'Ready for your decision, or with a Sauda reviewer.',
  approved_for_trading: 'Approved for trading.',
  declined: 'Declined. No orders can be placed.',
  paused: 'Paused. No new orders until resumed.',
};

export function RelationshipView({ rid }: { rid: string }) {
  const sp = useSearchParams();
  const bid = sp.get('bid') || '';
  const q = useAsync(() => getRelationship(rid, bid), [rid, bid]);
  return (
    <div className="narrow">
      <Link href="/network" className="small muted row sm tn-back" style={{ minHeight: 32 }}><Icon name="chev" size={14} /><span>Network</span></Link>
      {q.loading && !q.data && <Skeleton lines={6} />}
      {q.error && !q.data ? <ErrorState error={q.error} onRetry={q.reload} title="Could not load this relationship" /> : null}
      {q.data && <Body r={q.data} myBid={bid} onChange={(r) => q.setData(r)} />}
    </div>
  );
}

function Body({ r, myBid, onChange }: { r: TnRelationship; myBid: string; onChange: (r: TnRelationship) => void }) {
  const cp = counterpartyOf(r, myBid);
  const w = relWord(r.state);
  const idx = FLOW.indexOf(r.state);
  const hist = new Map((r.history || []).map((h) => [h.state, h]));
  const steps: Step[] = FLOW.map((s, i) => ({
    key: s, title: relWord(s).label,
    state: r.state === 'declined' || r.state === 'paused' ? (hist.has(s) ? 'done' : 'na') : i < idx ? 'done' : i === idx ? (s === 'approved_for_trading' ? 'done' : 'current') : 'todo',
    meta: hist.get(s)?.at ? <span className="xs muted">{ist(hist.get(s)!.at)}</span> : undefined,
    body: i === idx ? STATE_HELP[s] : undefined,
  }));
  if (r.state === 'declined' || r.state === 'paused') {
    const h = hist.get(r.state);
    steps.push({ key: r.state, title: relWord(r.state).label, state: r.state === 'declined' ? 'bad' : 'warn', body: h?.reason ? `“${h.reason}”` : STATE_HELP[r.state], meta: h?.at ? <span className="xs muted">{ist(h.at)}</span> : undefined });
  }
  const canDecide = !!cp.bid && !['invited'].includes(r.state);

  return (
    <>
      <div className="tn-hero">
        <p className="small muted">{cp.role === 'seller' ? 'Supplier' : 'Buyer'}{r.categories?.length ? ` · ${r.categories.join(', ')}` : ''}</p>
        <h1>{cp.name}</h1>
        <div><StatusPill tone={w.tone} size="lg">{w.label}</StatusPill></div>
        <p className="muted small">{STATE_HELP[r.state]}</p>
      </div>
      {cp.bid && <div className="row sm wrap"><ButtonLink href={`/network/business/${encodeURIComponent(cp.bid)}/profile?as=${encodeURIComponent(myBid)}&back=${encodeURIComponent(`/network/relationships/${r.rid}?bid=${myBid}`)}`} variant="secondary" size="sm">Review their profile</ButtonLink></div>}
      {r.state === 'invited' && <Callout tone="neutral">Waiting for {cp.name} to open the link you shared{r.contact_masked ? ` with ${r.contact_masked}` : ''}. Sauda does not send it for you.</Callout>}

      <section>
        <SectionHead title="Progress" />
        <Timeline steps={steps} label="Relationship progress" />
      </section>

      {canDecide && <Decide r={r} name={cp.name} myBid={myBid} onChange={onChange} />}

      <p className="xs muted">Provenance: {r.provenance.replace(/_/g, ' ')}. {r.shared_fields?.length ? `They can see: ${r.shared_fields.map((f) => f.replace(/_/g, ' ')).join(', ')}.` : 'Only redacted summaries are shared between the two businesses.'}</p>
    </>
  );
}

const TIERS: { v: string; label: string }[] = [
  { v: 'prepaid_small', label: 'Small prepaid orders' },
  { v: 'prepaid_regular', label: 'Regular prepaid orders' },
  { v: 'credit', label: 'Credit (needs a Sauda reviewer)' },
  { v: 'large_order', label: 'Large orders (needs a Sauda reviewer)' },
];
const LABELS: Record<RelAction, string> = { accept_request: 'Accept request', approve_for_trading: 'Approve for trading', decline: 'Decline', pause: 'Pause', start_review: 'Start review', resume: 'Resume' };

function actionsFor(state: string, seller: boolean): RelAction[] {
  const out: RelAction[] = [];
  if (seller && state === 'requested') out.push('accept_request');
  if (seller && ['onboarding', 'under_review', 'paused', 'approved_for_trading'].includes(state)) out.push('approve_for_trading');
  if (state === 'onboarding') out.push('start_review');
  if (state === 'paused') out.push('resume');
  if (['accepted', 'onboarding', 'under_review', 'approved_for_trading'].includes(state)) out.push('pause');
  if (state !== 'declined') out.push('decline');
  return out;
}

function Decide({ r, name, myBid, onChange }: { r: TnRelationship; name: string; myBid: string; onChange: (r: TnRelationship) => void }) {
  const seller = r.seller_bid === myBid;
  const [action, setAction] = useState<RelAction | null>(null);
  const [tier, setTier] = useState('prepaid_small');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState<{ code: string; message: string; missing: string[] } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const acts = actionsFor(r.state, seller);
  const ready = readinessList(r.readiness);
  async function go() {
    if (!action || reason.trim().length < 3) return;
    setBusy(true); setErr(null); setBlocked(null);
    try { onChange(await decideRelationship(r.rid, action, reason.trim(), tier, r.version)); setAction(null); setReason(''); }
    catch (e) {
      const d = errorDetail(e);
      if (e instanceof ApiError && (e.status === 409 || e.status === 403) && d.code && ['human_review_required', 'requirements_not_met', 'not_approver'].includes(d.code)) setBlocked({ code: d.code, message: e.message, missing: d.missing || [] });
      else setErr(e);
    } finally { setBusy(false); }
  }
  return (
    <section className="stack" aria-labelledby="dec-h">
      <SectionHead title={<span id="dec-h">Your decision</span>} />
      {seller
        ? <p className="small muted">You decide whether to supply {name}. Approval means you will accept orders at the tier you choose. <b>It does not grant credit and does not approve large orders</b>; those always need a Sauda reviewer and your own judgement.</p>
        : <p className="small muted">Only the supplier approves trading with you. You can start a review, pause or decline at any time. Approval never grants credit or approves large orders.</p>}
      {seller && ready.length > 0 && (
        <ul className="req-list" aria-label="Readiness against your requirements">
          {ready.map((t) => (
            <li key={t.tier} style={{ flexWrap: 'wrap' }}>
              <span className={`dot ${t.ready ? 'ok' : 'warn'}`} aria-hidden />
              <span className="grow"><b>{TIER_WORD[t.tier] || t.tier.replace(/_/g, ' ')}</b>: {t.ready ? 'meets your requirements' : t.requires_human_review ? 'needs a Sauda reviewer' : `missing ${t.missing.map(requirementWord).join('; ')}`}</span>
            </li>
          ))}
        </ul>
      )}
      {acts.length === 0 && <p className="small muted">No decisions are possible in this state.</p>}
      <div className="chipset" role="radiogroup" aria-label="Decision">
        {acts.map((a) => (
          <button key={a} type="button" className="chip-btn" role="radio" aria-checked={action === a} aria-pressed={action === a} onClick={() => { setAction(a); setBlocked(null); }}>{a === 'approve_for_trading' && r.state === 'approved_for_trading' ? 'Approve another tier' : LABELS[a]}</button>
        ))}
      </div>
      {action && (
        <form className="stack sm" onSubmit={(e) => { e.preventDefault(); go(); }}>
          {action === 'approve_for_trading' && (
            <label className="field"><span>Approve for</span>
              <select className="input" value={tier} onChange={(e) => setTier(e.target.value)}>{TIERS.map((t) => <option key={t.v} value={t.v} disabled={r.approved_tiers?.includes(t.v)}>{t.label}{r.approved_tiers?.includes(t.v) ? ' (approved)' : ''}</option>)}</select>
            </label>
          )}
          <label className="field"><span>Reason <span className="hint">· required, saved on the record</span></span>
            <textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={action === 'approve_for_trading' ? 'e.g. Known buyer for 3 years; prepaid only for now' : 'e.g. Could not confirm the shop address'} />
          </label>
          <Button type="submit" variant={action === 'decline' ? 'danger' : 'primary'} busy={busy} busyLabel="Saving…" disabled={reason.trim().length < 3}>{LABELS[action]}</Button>
        </form>
      )}
      {blocked && (
        <div className="callout warn" role="alert">
          <Icon name="alert" size={16} />
          <div>
            <b>{blocked.code === 'not_approver' ? 'Only the supplier can approve.' : blocked.code === 'human_review_required' ? 'This needs a Sauda reviewer.' : `Not yet. ${name} does not meet your requirements.`}</b>
            <p className="small" style={{ marginTop: 4 }}>{blocked.code === 'human_review_required' ? 'Credit, payment and large-order terms are never approved automatically. A reviewer has to look at them first.' : blocked.code === 'not_approver' ? blocked.message : 'Approve once these are in place:'}</p>
            {blocked.missing.length > 0 && <ul className="req-list" style={{ marginTop: 6 }}>{blocked.missing.map((m) => <li key={m}><span className="dot warn" aria-hidden />{requirementWord(m)}</li>)}</ul>}
            <span className="small">Nothing was changed.</span>
          </div>
        </div>
      )}
      {!!err && <Callout tone="bad">{err instanceof ApiError && err.code === 'version_conflict' ? 'This relationship changed elsewhere. Reload the page and try again.' : err instanceof Error ? err.message : String(err)}</Callout>}
      {r.approved_tiers?.length ? <p className="xs muted">Approved tiers: {r.approved_tiers.map((t) => TIER_WORD[t] || t).join(', ')}.</p> : null}
    </section>
  );
}
