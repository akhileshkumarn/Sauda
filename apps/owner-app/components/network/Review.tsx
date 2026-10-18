'use client';
import Link from 'next/link';
import { useState } from 'react';
import { ApiError } from '@/lib/api';
import { ist } from '@/lib/format';
import { ageText, dimWord, outstandingWord, reviewDecision, reviewQueue, reviewTask } from '@/lib/network';
import { useAsync } from '@/lib/useAsync';
import type { TnCheck, TnReviewAction, TnReviewTaskDetail } from '@/lib/types';
import { Button, Callout, EmptyState, ErrorState, Icon, SectionHead, Skeleton, StatusPill, type Tone } from '../ui';
import { CategoryHero, DimensionList, NIcon, SimulatedNote, SourceBadge, hasSimulated } from './shared';

const TASK_TONE: Record<string, { label: string; tone: Tone }> = {
  open: { label: 'Open', tone: 'warn' }, in_review: { label: 'In review', tone: 'info' }, needs_evidence: { label: 'Waiting for evidence', tone: 'info' }, approved: { label: 'Approved', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'bad' }, escalated: { label: 'Escalated', tone: 'quar' },
};
const taskWord = (s: string) => TASK_TONE[s] || { label: s, tone: 'neutral' as Tone };

export function ReviewQueue() {
  const q = useAsync(() => reviewQueue(), []);
  const forbidden = q.error instanceof ApiError && (q.error.status === 401 || q.error.status === 403);
  const rows = q.data || [];
  const open = rows.filter((t) => ['open', 'escalated', 'needs_evidence', 'in_review'].includes(t.status));
  const done = rows.filter((t) => !open.includes(t));
  return (
    <div className="narrow">
      <div className="page-head"><h1>Review</h1><p>Businesses the checks could not settle on their own. Every decision needs a reason and is written to the signed record.</p></div>
      {q.loading && !q.data && <Skeleton lines={6} />}
      {forbidden && <EmptyState icon="lock" title="Reviewers only">This console is for Sauda reviewers. Your account is not on the reviewer list.</EmptyState>}
      {q.error && !q.data && !forbidden ? <ErrorState error={q.error} onRetry={q.reload} title="Could not load the review queue" /> : null}
      {q.data && rows.length === 0 && <EmptyState icon="check" title="Nothing to review">New tasks appear when a check conflicts, a document needs reading, or an owner asks for a manual review.</EmptyState>}
      {[{ t: `Waiting · ${open.length}`, r: open }, { t: `Decided · ${done.length}`, r: done }].map((g) => g.r.length > 0 && (
        <section key={g.t}>
          <SectionHead title={g.t} />
          <div style={{ borderTop: '1px solid var(--line)' }}>
            {g.r.map((t) => {
              const w = taskWord(t.status);
              return (
                <Link key={t.tid} href={`/review/${encodeURIComponent(t.tid)}`} className="q-row">
                  <div className="stack xs" style={{ minWidth: 0 }}>
                    <span className="strong break">{t.display_name || t.bid}</span>
                    <span className="small muted row sm wrap" style={{ rowGap: 0 }}>
                      <StatusPill tone={w.tone}>{w.label}</StatusPill>
                      {t.roles?.length ? <span>{t.roles.map((r) => (r === 'buyer' ? 'Buyer' : 'Supplier')).join(', ')}</span> : null}
                      {t.is_fixture && <SourceBadge kind="simulated_fixture" />}
                    </span>
                  </div>
                  <span className="small muted num" title={ist(t.created_at)}>{ageText(t.created_at)}</span>
                  <span className="q-reason">{t.reasons.join(' · ')}</span>
                </Link>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

const ACTIONS: { a: TnReviewAction; label: string; variant: 'primary' | 'secondary' | 'danger' }[] = [
  { a: 'approve_identity', label: 'Approve identity', variant: 'primary' },
  { a: 'approve_claim', label: 'Approve a claim', variant: 'secondary' },
  { a: 'reject_claim', label: 'Reject a claim', variant: 'danger' },
  { a: 'request_evidence', label: 'Request evidence', variant: 'secondary' },
  { a: 'escalate', label: 'Escalate', variant: 'secondary' },
];

export function ReviewTaskView({ tid }: { tid: string }) {
  const q = useAsync(() => reviewTask(tid), [tid]);
  return (
    <div className="narrow">
      <Link href="/review" className="small muted row sm tn-back" style={{ minHeight: 32 }}><Icon name="chev" size={14} /><span>Review queue</span></Link>
      {q.loading && !q.data && <Skeleton lines={8} />}
      {q.error && !q.data ? <ErrorState error={q.error} onRetry={q.reload} title="Could not load this task" /> : null}
      {q.data && <TaskBody d={q.data} reload={q.reload} />}
    </div>
  );
}

function TaskBody({ d, reload }: { d: TnReviewTaskDetail; reload: () => void }) {
  const t = d.task;
  const b = d.business;
  const w = taskWord(t.status);
  const conflicts = d.checks.filter((c) => c.fields?.some((f) => f.match === false) || c.status === 'conflict' || c.status === 'failed');
  const doneChecks = d.checks.filter((c) => !['pending', 'inconclusive'].includes(c.status) && c.status !== 'not_applicable');
  const outstanding = d.summary?.outstanding || [];
  const audit = d.audit && d.audit.length ? d.audit : t.decisions.map((x) => ({ action: x.action, reason: x.reason, actor: x.reviewer_hash, at: x.at }));
  return (
    <>
      <div className="tn-hero">
        <p className="small muted">Review task · opened {ist(t.created_at)} · {ageText(t.created_at)} ago</p>
        <h1>{b?.display_name || t.display_name || t.bid}</h1>
        <div className="row sm wrap"><StatusPill tone={w.tone} size="lg">{w.label}</StatusPill>{(b?.roles || t.roles || []).map((r) => <span key={r} className="tag">{r === 'buyer' ? 'Buyer' : 'Supplier'}</span>)}</div>
      </div>
      <SimulatedNote show={!!(b?.is_fixture || t.is_fixture || hasSimulated(d.checks))}>Registry-like results for this business are demo fixtures. Use the official portal link below for any real check.</SimulatedNote>

      <section className="stack sm">
        <SectionHead title="Why it is here" />
        <ul className="req-list">{t.reasons.map((r, i) => <li key={i}><span className="dot warn" aria-hidden />{r}</li>)}</ul>
      </section>

      {(d.recommended_action || d.summary?.next_step) && <div className="tn-next"><Icon name="arrow" size={16} /><div><b>Recommended next action: </b>{d.recommended_action || d.summary?.next_step}</div></div>}

      {conflicts.length > 0 && (
        <section className="stack sm" aria-labelledby="conf-h">
          <SectionHead title={<span id="conf-h">Conflicting fields</span>} />
          {conflicts.map((c) => <Conflict key={c.check_id} c={c} />)}
        </section>
      )}

      {(d.manual_checks?.length ? d.manual_checks : manualFor(b)).map((m, i) => <ManualCheck key={i} m={m} />)}

      <section>
        <SectionHead title={`Checks done · ${doneChecks.length}`} />
        <DimensionList checks={d.checks} dims={d.summary?.dimensions} />
      </section>

      {outstanding.length > 0 && (
        <section className="stack sm">
          <SectionHead title="Still outstanding" />
          <ul className="req-list">{outstanding.map((o) => <li key={o}><span className="dot info" aria-hidden />{outstandingWord(o).label}</li>)}</ul>
        </section>
      )}

      {b && (
        <section className="stack sm">
          <SectionHead title="Declared by the business" />
          <dl className="kv">
            {b.legal_name && <><dt>Legal name</dt><dd>{b.legal_name}</dd></>}
            {b.gstin && <><dt>GSTIN</dt><dd className="num">{b.gstin}</dd></>}
            {b.cin_llpin && <><dt>CIN / LLPIN</dt><dd className="num">{b.cin_llpin}</dd></>}
            {b.fssai && <><dt>FSSAI</dt><dd className="num">{b.fssai}</dd></>}
            <dt>Address</dt><dd>{[b.address?.line, b.address?.city, b.address?.state, b.address?.pin].filter(Boolean).join(', ')}</dd>
            <dt>Representative</dt><dd>{[b.representative?.name, b.representative?.role].filter(Boolean).join(', ')} ({(b.representative?.authority_status || 'unknown').replace(/_/g, ' ')})</dd>
            {b.brand_claims?.length ? <><dt>Brand claims</dt><dd>{b.brand_claims.join(', ')}</dd></> : null}
          </dl>
        </section>
      )}

      <Decide d={d} onDone={reload} />

      <section>
        <SectionHead title="Audit history" />
        {audit.length === 0 ? <p className="small muted">No decisions yet.</p> : (
          <ol className="tl">{audit.map((a, i) => (
            <li key={i} className="tl-row done">
              <span className="tl-dot"><Icon name="check" size={14} /></span>
              <div className="tl-body">
                <div className="row between wrap sm"><span className="tl-title">{a.action.replace(/_/g, ' ')}</span><span className="xs muted">{ist(a.at)}</span></div>
                {a.reason && <div>“{a.reason}”</div>}
                {a.actor && <div className="xs muted mono">{a.actor}</div>}
              </div>
            </li>
          ))}</ol>
        )}
      </section>
    </>
  );
}

function Conflict({ c }: { c: TnCheck }) {
  const mis = c.fields.filter((f) => f.match === false);
  return (
    <div className="stack sm">
      <div className="row sm wrap"><span className="strong">{dimWord(c.dim).label}</span><SourceBadge kind={c.source_kind} name={c.source_name} /><span className="xs muted">{c.source_name}</span></div>
      {(mis.length ? mis : c.fields).map((f, i) => (
        <div key={i} className="side" role="group" aria-label={f.field}>
          <div><span className="k">{f.field} · declared by business</span>{f.declared ?? '—'}</div>
          <div className="bad"><span className="k">{f.field} · {c.source_kind === 'simulated_fixture' ? 'demo record shows' : 'source shows'}</span>{f.observed ?? '—'}</div>
        </div>
      ))}
    </div>
  );
}

function ManualCheck({ m }: { m: NonNullable<TnReviewTaskDetail['manual_checks']>[number] }) {
  const [vals, setVals] = useState<Record<string, string>>({});
  return (
    <section className="manual" aria-label={m.title}>
      <div className="stack xs"><span className="strong">Manual check: {m.title}</span><span className="small muted">Open the official portal yourself, look the business up, and type what it shows. Sauda does not scrape or automate the portal.</span></div>
      <a className="btn secondary sm" href={m.source_url} target="_blank" rel="noopener noreferrer" style={{ alignSelf: 'flex-start' }}>Open official portal <NIcon name="ext" size={14} /></a>
      {m.fields.map((f) => (
        <label key={f} className="field"><span>{f}</span><input className="input" value={vals[f] || ''} onChange={(e) => setVals((v) => ({ ...v, [f]: e.target.value }))} /></label>
      ))}
      <p className="xs muted">Include what you saw in the reason of your decision below; it is saved with a timestamp on the audit trail.</p>
    </section>
  );
}

function Decide({ d, onDone }: { d: TnReviewTaskDetail; onDone: () => void }) {
  const [action, setAction] = useState<TnReviewAction | null>(null);
  const [scope, setScope] = useState<string>('identity');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [ok, setOk] = useState<string | null>(null);
  const claimScoped = action === 'approve_claim' || action === 'reject_claim';
  async function go() {
    if (!action || reason.trim().length < 5) return;
    setBusy(true); setErr(null); setOk(null);
    const sc = action === 'approve_identity' ? 'identity' : claimScoped ? scope : scope.startsWith('claim:') ? scope : 'identity';
    try { await reviewDecision(d.task.tid, { action, scope: sc, reason: reason.trim() }); setOk(`${ACTIONS.find((x) => x.a === action)?.label} recorded.`); setAction(null); setReason(''); onDone(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  }
  return (
    <section className="stack" aria-labelledby="rdec-h">
      <SectionHead title={<span id="rdec-h">Decision</span>} />
      <div className="chipset" role="radiogroup" aria-label="Action">
        {ACTIONS.map((x) => <button key={x.a} type="button" className="chip-btn" role="radio" aria-checked={action === x.a} aria-pressed={action === x.a} onClick={() => { setAction(x.a); if (x.a === 'approve_claim' || x.a === 'reject_claim') setScope(d.checks[0] ? `claim:${d.checks[0].check_id}` : 'identity'); }}>{x.label}</button>)}
      </div>
      {action && (
        <form className="stack sm" onSubmit={(e) => { e.preventDefault(); go(); }}>
          {claimScoped && (
            <label className="field"><span>Which claim</span>
              <select className="input" value={scope} onChange={(e) => setScope(e.target.value)}>
                {d.checks.filter((c) => c.status !== 'not_applicable').map((c) => <option key={c.check_id} value={`claim:${c.check_id}`}>{dimWord(c.dim).label}: {c.summary.slice(0, 60)}</option>)}
              </select>
            </label>
          )}
          <label className="field"><span>Reason <span className="hint">· required; what you checked and what you saw</span></span>
            <textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. GST portal shows trade name 'Sri Laxmi General Store'; same legal name and address; spelling variant only." />
          </label>
          <Button type="submit" variant={action === 'reject_claim' ? 'danger' : 'primary'} busy={busy} busyLabel="Recording…" disabled={reason.trim().length < 5}>{ACTIONS.find((x) => x.a === action)?.label}</Button>
          <p className="xs muted">A decision changes the business’s verification record, not credit or order limits.</p>
        </form>
      )}
      {ok && <Callout tone="ok">{ok}</Callout>}
      {!!err && <Callout tone="bad">{err instanceof Error ? err.message : String(err)}</Callout>}
      {d.summary && <details className="evidence"><summary><span className="chev"><Icon name="chev" size={14} /></span>What the owner sees now</summary><div className="ev-body"><CategoryHero summary={d.summary} roles={d.business?.roles} /></div></details>}
    </section>
  );
}

/** Official public portals for a hand check when the backend does not suggest one. Links only; never automated. */
function manualFor(b: TnReviewTaskDetail['business']): NonNullable<TnReviewTaskDetail['manual_checks']> {
  if (!b) return [];
  const out: NonNullable<TnReviewTaskDetail['manual_checks']> = [];
  if (b.gstin) out.push({ title: `Search GSTIN ${b.gstin} on the GST portal`, source_url: 'https://services.gst.gov.in/services/searchtp', fields: ['Legal name on portal', 'Trade name on portal', 'Status'] });
  if (b.cin_llpin) out.push({ title: `Look up ${b.cin_llpin} on the MCA portal`, source_url: 'https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html', fields: ['Company or LLP name', 'Status'] });
  if (b.fssai) out.push({ title: `Check FSSAI ${b.fssai} on FoSCoS`, source_url: 'https://foscos.fssai.gov.in/', fields: ['Name on licence', 'Valid until'] });
  if (b.udyam) out.push({ title: `Verify Udyam ${b.udyam}`, source_url: 'https://udyamregistration.gov.in/Udyam_Verify.aspx', fields: ['Enterprise name', 'Type'] });
  return out.slice(0, 2);
}
