'use client';
import './network.css';
import type { ReactNode } from 'react';
import { ist, relTime } from '@/lib/format';
import { categoryWord, dimWord, sourceWord, statusWord } from '@/lib/network';
import type { TnCheck, TnDimensionSummary, TnFieldCompare, TnRole, TnSourceKind, TnSummary } from '@/lib/types';
import { Disclosure, Icon, StatusPill } from '../ui';

const EXTRA: Record<string, ReactNode> = {
  pin: <><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0113 0c0 5.4-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.3" /></>,
  upload: <><path d="M12 15V4M7.5 8.5L12 4l4.5 4.5" /><path d="M4.5 15v4.5h15V15" /></>,
  doc: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>,
  people: <><circle cx="9" cy="8.5" r="3" /><path d="M3.5 19c.8-3 3-4.5 5.5-4.5s4.7 1.5 5.5 4.5" /><circle cx="16.5" cy="9.5" r="2.4" /><path d="M15.5 14.6c2.3 0 4.2 1.3 5 4.4" /></>,
  copy: <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V5.5A1.5 1.5 0 0014.5 4h-9A1.5 1.5 0 004 5.5v9A1.5 1.5 0 005.5 16H8" /></>,
  ext: <><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" /></>,
};
/** Icons used only by the network screens; falls back to the shared set. */
export function NIcon({ name, size = 16 }: { name: string; size?: number }) {
  if (!EXTRA[name]) return <Icon name={name} size={size} />;
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">{EXTRA[name]}</svg>;
}

const SRC_CLASS: Partial<Record<TnSourceKind, string>> = { simulated_fixture: 'sim', preliminary_validation: 'pre', official_registry: 'off', human_review: 'hum' };
const SRC_ICON: Partial<Record<TnSourceKind, string>> = {
  simulated_fixture: 'flask', official_registry: 'shield', authorised_provider: 'shield', uploaded_evidence: 'doc', human_review: 'user', self_declared: 'pen', device_signal: 'pin', preliminary_validation: 'check',
};
export function SourceBadge({ kind, name }: { kind?: TnSourceKind | string | null; name?: string | null }) {
  if (!kind) return null;
  const k = kind as TnSourceKind;
  const label = sourceWord(k);
  const title = k === 'simulated_fixture' ? 'Demo data made up for this prototype. Not from a government or provider record.' : name || label;
  return (
    <span className={`src ${SRC_CLASS[k] || ''}`} title={title}>
      <NIcon name={SRC_ICON[k] || 'info'} size={12} />
      <span>{label}</span>
    </span>
  );
}

export function CheckStatus({ status }: { status: string }) {
  const w = statusWord(status);
  return <StatusPill tone={w.tone}>{w.label}</StatusPill>;
}

export function SimulatedNote({ show = true, children }: { show?: boolean; children?: ReactNode }) {
  if (!show) return null;
  return (
    <div className="sim-note" role="note">
      <NIcon name="flask" />
      <div><b>Simulated (demo data).</b> {children || 'Some results here come from demo fixtures, not live government or provider records. They show how verification works; they prove nothing about a real business.'}</div>
    </div>
  );
}

export function hasSimulated(xs: { source_kind?: string | null }[] | undefined | null) {
  return !!xs?.some((x) => x.source_kind === 'simulated_fixture');
}

export function MatchMark({ match }: { match: boolean | null | undefined }) {
  if (match === true) return <span className="match y"><Icon name="check" size={12} />Match</span>;
  if (match === false) return <span className="match n"><Icon name="x" size={12} />Mismatch</span>;
  return <span className="match u">Not compared</span>;
}

export function FieldCompare({ fields }: { fields: TnFieldCompare[] }) {
  if (!fields.length) return <p className="small muted">No field-by-field comparison for this check.</p>;
  return (
    <div className="cmp" role="table" aria-label="Declared versus observed">
      {fields.map((f, i) => (
        <div key={`${f.field}-${i}`} className={`cmp-row ${f.match === false ? 'mis' : ''}`} role="row">
          <div className="cmp-f" role="rowheader"><span className="break">{f.field}</span><MatchMark match={f.match} /></div>
          <div className="cmp-vals">
            <div role="cell"><span className="k">You declared</span><span className="v">{f.declared ?? '—'}</span></div>
            <div role="cell"><span className="k">Source shows</span><span className="v">{f.observed ?? '—'}</span></div>
          </div>
        </div>
      ))}
    </div>
  );
}

type DimRowData = { dim: string; status: string; source_kind?: string | null; source_name?: string; summary: string; checked_at?: string | null; fields?: TnFieldCompare[]; source_url?: string | null; reviewer?: TnCheck['reviewer']; expires_at?: string | null };

/** One row per dimension. Detailed checks (with fields) win over the summary line when both are present. */
export function DimensionList({ dims, checks, compare = true }: { dims?: TnDimensionSummary[]; checks?: TnCheck[]; compare?: boolean }) {
  const byDim = new Map<string, TnCheck[]>();
  for (const c of checks || []) byDim.set(c.dim, [...(byDim.get(c.dim) || []), c]);
  const rows: DimRowData[] = [];
  const seen = new Set<string>();
  for (const d of dims || []) {
    seen.add(d.dim);
    const cs = byDim.get(d.dim) || [];
    const main = cs.find((c) => c.source_kind === d.source_kind) || cs[cs.length - 1];
    rows.push({ ...d, source_name: main?.source_name, fields: cs.flatMap((c) => c.fields || []), source_url: main?.source_url, reviewer: main?.reviewer, expires_at: main?.expires_at });
  }
  for (const [dim, cs] of byDim) {
    if (seen.has(dim)) continue;
    const main = cs[cs.length - 1];
    rows.push({ ...main, fields: cs.flatMap((c) => c.fields || []) });
  }
  if (!rows.length) return <p className="muted small">No checks have run yet.</p>;
  return (
    <ul className="dims" aria-label="Verification by dimension">
      {rows.map((r) => {
        const w = dimWord(r.dim);
        return (
          <li key={r.dim} className={`dim ${r.status === 'not_applicable' ? 'na' : ''}`}>
            <div className="dim-top">
              <span className="dim-name">{w.label}</span>
              <CheckStatus status={r.status} />
              <p className="dim-sum">{r.summary}</p>
              <div className="dim-meta">
                {r.status !== 'not_applicable' && <SourceBadge kind={r.source_kind} name={r.source_name} />}
                {r.status !== 'not_applicable' && r.source_name && r.source_name !== '—' && <span className="break">{r.source_name}</span>}
                {r.checked_at && <span title={ist(r.checked_at)}>Checked {relTime(r.checked_at)}</span>}
                {r.expires_at && <span>Valid until {ist(r.expires_at)}</span>}
              </div>
            </div>
            {compare && r.status !== 'not_applicable' && ((r.fields && r.fields.length) || r.reviewer || r.source_url) ? (
              <Disclosure label="Field by field">
                {r.fields && r.fields.length > 0 && <FieldCompare fields={r.fields} />}
                {r.reviewer && <p className="small">Reviewer decision: <b>{r.reviewer.decision.replace(/_/g, ' ')}</b>. “{r.reviewer.reason}” · {ist(r.reviewer.at)}</p>}
                {r.source_url && <a className="linkbtn row sm" href={r.source_url} target="_blank" rel="noopener noreferrer">Open source <NIcon name="ext" size={12} /></a>}
              </Disclosure>
            ) : <div style={{ height: 8 }} />}
          </li>
        );
      })}
    </ul>
  );
}

export function CategoryHero({ summary, roles, title, children, sample }: { summary: TnSummary; roles?: TnRole[]; title?: ReactNode; children?: ReactNode; sample?: boolean }) {
  const w = categoryWord(summary.category, roles, sample);
  return (
    <div className="tn-hero">
      {title && <p className="small muted break">{title}</p>}
      <h1>{w.label}</h1>
      <div><StatusPill tone={w.tone}>{w.tone === 'ok' ? 'On track' : w.tone === 'bad' ? 'Not verified' : 'Needs attention'}</StatusPill></div>
      {summary.next_step && <div className="tn-next"><Icon name="arrow" size={16} /><div><b>Next: </b>{summary.next_step}</div></div>}
      {children}
    </div>
  );
}

export function Limitations({ items, title = 'What this does not tell you' }: { items: string[]; title?: string }) {
  const all = [...items];
  if (!all.some((x) => /credit/i.test(x))) all.push('Verification does not approve credit, payment terms or large orders. Those stay your decision.');
  return (
    <section aria-labelledby="lim-h" className="stack sm">
      <h2 id="lim-h" className="small muted" style={{ fontWeight: 500 }}>{title}</h2>
      <ul className="plain-list">{all.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </section>
  );
}

export function Field({ label, hint, children, msg, why }: { label: ReactNode; hint?: ReactNode; children: ReactNode; msg?: { ok: boolean; message: string } | null; why?: ReactNode }) {
  return (
    <label className="field">
      <span>{label}{hint && <span className="hint"> · {hint}</span>}</span>
      {children}
      {why && <span className="why"><NIcon name="lock" size={12} /><span><span className="why-k">Why we ask:</span> {why}</span></span>}
      {msg && msg.message && (
        <span className={`fieldmsg ${msg.ok ? 'ok' : 'bad'}`} aria-live="polite">
          <span>{msg.ok ? '✓' : '!'} {msg.message}</span><span className="fmt">Format check only</span>
        </span>
      )}
    </label>
  );
}
