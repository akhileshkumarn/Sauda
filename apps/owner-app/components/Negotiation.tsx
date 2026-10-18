'use client';
// Live negotiation view, built only from SSE events (offer, guard.verdict, gate.report, agent.tool).
import { maskVpasIn, reasonText, rupees, supplierName } from '@/lib/format';
import type { GateReport, OfferEvent } from '@/lib/types';
import { Evidence, Money, StatusPill, type Tone } from './ui';

export const MAX_ROUNDS = 3;

export interface RoundQuote {
  round: number;
  total: number | null;
  lines: number;
  advance?: number | null;
  delivery?: number | null;
  guardBlocked: boolean;
  gate?: string;
  reasons: string[];
}
export interface SupplierState {
  id: string;
  name: string;
  quotes: RoundQuote[];
  guardBlocks: number;
  verified: boolean | null;
  down: string | null;
  gates: (GateReport & { round?: number })[];
  categories: string[];
}
export interface NegState {
  suppliers: Record<string, SupplierState>;
  order: string[];
  round: number;
  done: boolean;
  maxAdvance: number | null;
}

export const emptyNeg = (ids: string[] = [], maxAdvance: number | null = null): NegState => {
  const s: NegState = { suppliers: {}, order: [], round: 0, done: false, maxAdvance };
  for (const id of ids) ensure(s, id);
  return s;
};

function ensure(s: NegState, id: string, name?: string): SupplierState {
  if (!s.suppliers[id]) {
    s.suppliers[id] = { id, name: supplierName(id, name), quotes: [], guardBlocks: 0, verified: null, down: null, gates: [], categories: [] };
    s.order.push(id);
  } else if (name) s.suppliers[id].name = name;
  return s.suppliers[id];
}

const clone = (s: NegState): NegState => ({ ...s, order: [...s.order], suppliers: Object.fromEntries(Object.entries(s.suppliers).map(([k, v]) => [k, { ...v, quotes: [...v.quotes], gates: [...v.gates], categories: [...v.categories] }])) });

export function negOffer(prev: NegState, o: OfferEvent): NegState {
  const s = clone(prev);
  const sup = ensure(s, o.supplier_id, o.supplier_name);
  const lines = o.lines || [];
  const total = lines.length && lines.every((l) => l.qty && l.unit_price_paise != null) ? lines.reduce((a, l) => a + (l.qty || 0) * (l.unit_price_paise || 0), 0) : null;
  const q: RoundQuote = { round: o.round, total, lines: lines.length, advance: o.advance_pct, delivery: o.delivery_days, guardBlocked: !!o.guard_blocked, gate: o.gate_verdict ? String(o.gate_verdict).toUpperCase() : undefined, reasons: o.reasons || [] };
  sup.quotes = [...sup.quotes.filter((x) => x.round !== o.round), q].sort((a, b) => a.round - b.round);
  if (q.gate !== 'DENY' || !q.reasons.includes('SUPPLIER_UNKNOWN')) sup.verified = sup.verified ?? true;
  sup.down = null;
  s.round = Math.max(s.round, o.round || 0);
  return s;
}

export function negGuard(prev: NegState, d: { supplier_id: string; round?: number; blocked: boolean; categories?: string[] }): NegState {
  const s = clone(prev);
  const sup = ensure(s, d.supplier_id);
  if (d.blocked) { sup.guardBlocks += 1; sup.categories = Array.from(new Set([...sup.categories, ...(d.categories || [])])); }
  if (d.round) s.round = Math.max(s.round, d.round);
  return s;
}

export function negGate(prev: NegState, g: GateReport & { supplier_id?: string; round?: number; reasons?: string[] }): NegState {
  if (!g.supplier_id) return prev;
  const s = clone(prev);
  const sup = ensure(s, g.supplier_id);
  sup.gates = [...sup.gates, g];
  const r2 = g.results.find((r) => r.rule === 'R2');
  if (r2) sup.verified = r2.verdict === 'PASS' || r2.verdict === 'ALLOW';
  if ((g.round ?? 1) === 0 && String(g.verdict).toUpperCase() === 'DENY') sup.down = 'not_verified';
  return s;
}

export function negDown(prev: NegState, sid: string, why: string): NegState {
  const s = clone(prev);
  const sup = ensure(s, sid);
  sup.down = why;
  return s;
}

type Kind = 'allowed' | 'blocked' | 'quarantined' | 'approval' | 'waiting' | 'down' | 'unverified';
function kindOf(sup: SupplierState): Kind {
  if (sup.down === 'not_verified' || sup.verified === false) return 'unverified';
  if (sup.down) return 'down';
  if (sup.guardBlocks >= 2) return 'quarantined';
  const last = sup.quotes[sup.quotes.length - 1];
  if (!last) return 'waiting';
  if (last.guardBlocked || last.gate === 'DENY') return 'blocked';
  if (last.gate === 'CONFIRM') return 'approval';
  return 'allowed';
}
const KIND: Record<Kind, { tone: Tone; label: string; cls: string; icon: string }> = {
  allowed: { tone: 'ok', label: 'Offer allowed', cls: 'ok', icon: 'check' },
  blocked: { tone: 'bad', label: 'Offer blocked', cls: 'bad', icon: 'shieldx' },
  quarantined: { tone: 'quar', label: 'Quarantined', cls: 'quar', icon: 'lock' },
  approval: { tone: 'warn', label: 'Needs your approval', cls: 'warn', icon: 'alert' },
  waiting: { tone: 'neutral', label: 'Waiting for quote', cls: 'wait', icon: 'clock' },
  down: { tone: 'neutral', label: 'Not responding', cls: 'down', icon: 'wifi' },
  unverified: { tone: 'bad', label: 'Not verified', cls: 'bad', icon: 'shieldx' },
};

export function NegotiationPanel({ s }: { s: NegState }) {
  const cur = s.done ? MAX_ROUNDS + 1 : Math.max(1, s.round);
  const ids = s.order;
  return (
    <section className="stack" style={{ alignSelf: 'stretch' }} aria-labelledby="neg-h" aria-live="polite">
      <div className="row between wrap">
        <div className="stack xs">
          <h2 id="neg-h">Comparing and negotiating</h2>
          <span className="small muted">{s.done ? `Finished after ${s.round} ${s.round === 1 ? 'round' : 'rounds'}` : `Round ${Math.max(1, s.round)} of ${MAX_ROUNDS}`} · {ids.length} {ids.length === 1 ? 'supplier' : 'suppliers'}</span>
        </div>
        {s.done ? <StatusPill tone="ok">Done</StatusPill> : <StatusPill tone="accent">Live</StatusPill>}
      </div>
      <ol className="rounds" aria-label="Rounds">
        {Array.from({ length: MAX_ROUNDS }).map((_, i) => {
          const r = i + 1;
          const skipped = s.done && r > s.round;
          const st = skipped ? '' : r < cur ? 'done' : r === cur ? 'current' : '';
          return (
            <li key={r} className={`round ${st}`} style={{ listStyle: 'none' }} aria-current={st === 'current' ? 'step' : undefined}>
              <b>Round {r}</b>{skipped ? 'not needed' : st === 'done' ? 'done' : st === 'current' ? 'now' : r === 1 ? 'quotes' : 'counter'}
            </li>
          );
        })}
      </ol>
      <div className="suppliers">
        {ids.map((id) => <SupplierCard key={id} sup={s.suppliers[id]} maxAdvance={s.maxAdvance} />)}
      </div>
      <p className="xs faint">Simulated suppliers. Their messages are read as data, never as instructions.</p>
    </section>
  );
}

function SupplierCard({ sup, maxAdvance }: { sup: SupplierState; maxAdvance: number | null }) {
  const k = kindOf(sup);
  const meta = KIND[k];
  const first = sup.quotes[0];
  const last = sup.quotes[sup.quotes.length - 1];
  const gateCodes = sup.gates.flatMap((g) => [...((g as { reasons?: string[] }).reasons || []), ...g.results.filter((r) => r.verdict === 'DENY').map((r) => r.reason_code || '')]).filter(Boolean) as string[];
  const reasons = Array.from(new Set(sup.quotes.flatMap((q) => q.reasons).concat(sup.guardBlocks ? ['GUARD_BLOCKED'] : []).concat(gateCodes)));
  const why = reasons.map((c) => reasonText(c, { supplier: sup.name, advance: last?.advance, maxAdvance }));
  const dropped = first && last && first.total && last.total && last.total < first.total ? first.total - last.total : 0;
  const blockedish = k === 'blocked' || k === 'quarantined' || k === 'unverified';
  return (
    <article className="sup" aria-label={`${sup.name}: ${meta.label}`}>
      <div className="row between top">
        <div className="stack xs grow">
          <span className="row sm"><span className="strong break">{sup.name}</span><span className="tag">Simulated</span></span>
          <StatusPill tone={meta.tone}>{meta.label}{sup.verified === true && !blockedish ? ' · registered' : ''}</StatusPill>
        </div>
        {first && first.total != null && (
          <div className="right none stack xs">
            {sup.quotes.length > 1 && last.total != null ? (
              <>
                <span className="small strike num"><Money paise={first.total} whole /></span>
                <Money paise={last.total} whole className="strong" />
              </>
            ) : <Money paise={first.total} whole className={blockedish ? 'strike' : 'strong'} />}
          </div>
        )}
      </div>
      {first && (last.advance != null || last.delivery != null) && (
        <span className="small muted">
          {[last.advance != null ? `${last.advance}% advance` : null, last.delivery != null ? `${last.delivery} ${last.delivery === 1 ? 'day' : 'days'} delivery` : null, sup.quotes.length > 1 ? `round ${last.round}` : null].filter(Boolean).join(' · ')}
          {dropped > 0 && k === 'allowed' ? ` · down ${rupees(dropped)}` : ''}
        </span>
      )}
      {blockedish && why.length > 0 && <span className="small" style={{ color: 'var(--ink)' }}>{why[0]}.</span>}
      {k === 'quarantined' && <span className="small muted">Sauda stopped talking to {sup.name} for this restock.</span>}
      {k === 'unverified' && <span className="small muted">Not in the registry, so Sauda did not contact it.</span>}
      {k === 'down' && <span className="small muted">Did not respond in time. Sauda carried on with the others.</span>}
      {k === 'approval' && <span className="small muted">Allowed, but check the cart before approving.</span>}
      {(sup.gates.length > 0 || reasons.length > 0) && (
        <Evidence>
          {why.length > 1 && <ul className="stack xs" style={{ paddingLeft: 16 }}>{why.map((w) => <li key={w}>{w}</li>)}</ul>}
          {reasons.length > 0 && <div>Reason codes: {reasons.map((r) => <span key={r} className="code" style={{ marginRight: 4 }}>{r}</span>)}</div>}
          {sup.categories.length > 0 && <div>Model Armor filters: {sup.categories.map((c) => <span key={c} className="code" style={{ marginRight: 4 }}>{c}</span>)}</div>}
          {sup.gates.slice(-1).map((g, i) => (
            <div key={i} className="stack xs">
              <span>Policy gate, round {g.round ?? '—'}: <b>{String(g.verdict)}</b></span>
              {g.results.filter((r) => r.verdict !== 'PASS').map((r) => <span key={r.rule} className="mono">{maskVpasIn(`${r.rule} ${r.verdict} ${r.reason_code || ''} ${r.detail || ''}`)}</span>)}
            </div>
          ))}
        </Evidence>
      )}
    </article>
  );
}
