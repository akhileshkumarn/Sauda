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

const isOut = (k: Kind) => k === 'blocked' || k === 'quarantined' || k === 'unverified' || k === 'down';
const latestTotal = (sup: SupplierState) => { const q = sup.quotes[sup.quotes.length - 1]; return q?.total ?? null; };

export function NegotiationPanel({ s }: { s: NegState }) {
  const cur = s.done ? MAX_ROUNDS + 1 : Math.max(1, s.round);
  const ids = s.order;
  // Lowest latest quote among suppliers whose offer is still in play.
  let bestId: string | null = null;
  for (const id of ids) {
    const sup = s.suppliers[id];
    const t = latestTotal(sup);
    if (t == null || isOut(kindOf(sup))) continue;
    if (bestId == null || t < (latestTotal(s.suppliers[bestId]) ?? Infinity)) bestId = id;
  }
  const quoted = ids.filter((id) => s.suppliers[id].quotes.length > 0).length;
  const best = bestId ? s.suppliers[bestId] : null;
  const bestT = best ? latestTotal(best) : null;
  const progress = s.done ? `Finished after ${s.round} ${s.round === 1 ? 'round' : 'rounds'}` : `Round ${Math.max(1, s.round)} of ${MAX_ROUNDS}`;
  return (
    <section className="stack" style={{ alignSelf: 'stretch' }} aria-labelledby="neg-h">
      <div className="rf-neg-head">
        <div className="stack xs" style={{ minWidth: 0 }}>
          <h2 id="neg-h">Comparing suppliers</h2>
          <span className="small muted num">{progress} · {quoted} of {ids.length} quoted</span>
        </div>
        {s.done ? <StatusPill tone="ok">Done</StatusPill> : <StatusPill tone="accent">Live</StatusPill>}
      </div>
      <p className="sr-only" role="status" aria-live="polite">
        {progress}. {best && bestT != null ? `Lowest offer so far: ${best.name}, ${rupees(bestT, true)}.` : 'Waiting for quotes.'}
      </p>
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
      <div className="rf-sups">
        {ids.map((id) => <SupplierCard key={id} sup={s.suppliers[id]} maxAdvance={s.maxAdvance} best={id === bestId && ids.length > 1} />)}
      </div>
      <p className="xs faint">Simulated suppliers. Their messages are read as data, never as instructions.</p>
    </section>
  );
}

function SupplierCard({ sup, maxAdvance, best }: { sup: SupplierState; maxAdvance: number | null; best?: boolean }) {
  const k = kindOf(sup);
  const meta = KIND[k];
  const first = sup.quotes[0];
  const last = sup.quotes[sup.quotes.length - 1];
  const gateCodes = sup.gates.flatMap((g) => [...((g as { reasons?: string[] }).reasons || []), ...g.results.filter((r) => r.verdict === 'DENY').map((r) => r.reason_code || '')]).filter(Boolean) as string[];
  const reasons = Array.from(new Set(sup.quotes.flatMap((q) => q.reasons).concat(sup.guardBlocks ? ['GUARD_BLOCKED'] : []).concat(gateCodes)));
  const why = reasons.map((c) => reasonText(c, { supplier: sup.name, advance: last?.advance, maxAdvance }));
  const dropped = first && last && first.total && last.total && last.total < first.total ? first.total - last.total : 0;
  const blockedish = k === 'blocked' || k === 'quarantined' || k === 'unverified';
  const changed = !!first && !!last && sup.quotes.length > 1 && first.total != null && last.total != null && first.total !== last.total;
  const terms = last ? [last.advance != null ? `${last.advance}% advance` : null, last.delivery != null ? `${last.delivery} ${last.delivery === 1 ? 'day' : 'days'} delivery` : null, sup.quotes.length > 1 ? `round ${last.round}` : null].filter(Boolean).join(' · ') : '';
  const plain = blockedish && why.length > 0 ? why[0]
    : k === 'unverified' ? 'Not in the supplier registry, so Sauda did not contact it'
    : k === 'down' ? 'Did not respond in time. Sauda carried on with the others'
    : null;
  const sub = k === 'quarantined' ? `Sauda stopped talking to ${sup.name} for this restock.` : k === 'approval' ? 'Allowed, but check the cart before approving.' : null;
  return (
    <article className={`rf-sup ${isOut(k) ? 'out' : ''}`} aria-label={`${sup.name}: ${meta.label}`}>
      <div className="rf-sup-main">
        <div className="rf-sup-id">
          <span className="rf-sup-name"><span className="strong" title={sup.name}>{sup.name}</span>{best ? <span className="rf-best">Lowest</span> : <span className="tag">Simulated</span>}</span>
          <StatusPill tone={meta.tone}>{meta.label}{sup.verified === true && !blockedish ? ' · registered' : ''}</StatusPill>
        </div>
        <div className="rf-price">
          {last && last.total != null ? (
            <>
              <span key={last.total} className={`now ${sup.quotes.length > 1 ? 'tick' : ''}`} style={blockedish ? { textDecoration: 'line-through', color: 'var(--ink-2)' } : undefined}>
                <Money paise={last.total} whole />
              </span>
              {changed ? (
                <span className="was"><span className="sr-only">opened at </span><s><Money paise={first.total} whole /></s>{dropped > 0 && !blockedish ? <span className="drop"> −{rupees(dropped, true)}</span> : null}</span>
              ) : (
                <span className="was">{blockedish ? 'not used' : 'opening quote'}</span>
              )}
            </>
          ) : k === 'waiting' ? (
            <><span className="skeleton" aria-hidden /><span className="was">waiting</span></>
          ) : <span className="was">no quote</span>}
        </div>
      </div>
      {terms && <span className="rf-sup-terms">{terms}</span>}
      {plain && (
        <span className="rf-reason"><span className={`dot ${blockedish ? 'bad' : 'neutral'}`} aria-hidden /><span>{plain}.{sub ? <span className="sub"> {sub}</span> : null}</span></span>
      )}
      {!plain && sub && <span className="small muted">{sub}</span>}
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
