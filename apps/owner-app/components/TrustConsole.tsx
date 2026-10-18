'use client';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { getEvents, getMetrics, SHOP_ID, verifyChain } from '@/lib/api';
import { canonical, recomputeChain, type LocalCheck } from '@/lib/chain';
import { ist, maskVpasIn, reasonText, rupees, shortHash, supplierName, unmaskWith } from '@/lib/format';
import { lastNegotiationId } from '@/lib/session';
import { useAsync } from '@/lib/useAsync';
import type { LedgerEvent, VerifyEvent } from '@/lib/types';
import { Button, Callout, Card, ErrorState, Evidence, Icon, Skeleton, StatusPill, Timeline, type Step } from './ui';

export function TrustConsole({ negotiationId }: { negotiationId: string }) {
  const router = useRouter();
  const [nid, setNid] = useState(negotiationId === 'latest' ? '' : negotiationId);
  useEffect(() => {
    if (negotiationId === 'latest') {
      const last = lastNegotiationId();
      if (last) { router.replace(`/trust/${encodeURIComponent(last)}`); return; }
      getMetrics(SHOP_ID)
        .then((m) => {
          const id = (m as { last_negotiation_id?: string }).last_negotiation_id;
          if (id) router.replace(`/trust/${encodeURIComponent(id)}`);
        })
        .catch(() => { /* fall back to the picker */ });
    }
  }, [negotiationId, router]);

  if (!nid) return <PickNegotiation onPick={(v) => { setNid(v); router.push(`/trust/${encodeURIComponent(v)}`); }} />;
  return <Console nid={nid} />;
}

function PickNegotiation({ onPick }: { onPick: (v: string) => void }) {
  const [v, setV] = useState('');
  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); if (v.trim()) onPick(v.trim()); }} aria-labelledby="pick-h">
      <div className="stack xs">
        <h2 id="pick-h">Which restock do you want to check?</h2>
        <p className="small muted">No recent restock was found on this device. Paste a negotiation ID (it starts with <span className="code">neg_</span>, shown on the order screens).</p>
      </div>
      <label className="sr-only" htmlFor="nid">Negotiation ID</label>
      <input id="nid" className="input mono" placeholder="neg_…" value={v} onChange={(e) => setV(e.target.value)} />
      <Button block type="submit" disabled={!v.trim()} icon="shield">Check this record</Button>
    </form>
  );
}

function Console({ nid }: { nid: string }) {
  const verify = useAsync(() => verifyChain(nid), [nid]);
  const events = useAsync(() => getEvents(nid), [nid]);
  const [tampered, setTampered] = useState<LedgerEvent[] | null>(null);
  const [local, setLocal] = useState<LocalCheck[] | null>(null);
  const [tamperedSeq, setTamperedSeq] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    if (!tampered) { setLocal(null); return; }
    recomputeChain(tampered).then((c) => { if (live) setLocal(c); });
    return () => { live = false; };
  }, [tampered]);

  const byseq = useMemo(() => new Map((verify.data?.events || []).map((e) => [e.seq, e])), [verify.data]);
  const derived = useMemo(() => derive([...(events.data || [])].sort((a, b) => a.seq - b.seq)), [events.data]);

  if ((verify.loading && !verify.data) || (events.loading && !events.data)) return <Skeleton lines={8} />;
  if (events.error || !events.data) return (
    <div className="stack">
      <ErrorState error={events.error} onRetry={events.reload} title={`No record found for “${nid}”`} />
      <a className="btn secondary block" href="/trust/latest">Check another restock</a>
    </div>
  );

  const evs = [...events.data].sort((a, b) => a.seq - b.seq);
  const shown = tampered || evs;
  const firstBreak = local?.find((c) => c.after_break)?.seq ?? null;
  const headOk = verify.data?.head_ok;
  const serverOk = !!verify.data?.chain_ok && headOk !== false;
  const headText = headProblem(verify.data?.head_problem);
  const sigs = verify.data?.events || [];
  const sigOk = sigs.length > 0 && sigs.every((e) => e.sig_ok);
  const sigBad = sigs.filter((e) => !e.sig_ok).length;
  const serverFirstBad = verify.data?.first_broken_seq ?? sigs.find((e) => !(e.hash_ok && e.link_ok && e.sig_ok))?.seq ?? null;

  const state: 'ok' | 'bad' | 'neutral' = tampered ? (firstBreak !== null ? 'bad' : 'ok') : verify.error ? 'neutral' : serverOk ? 'ok' : 'bad';
  const title = tampered
    ? firstBreak !== null ? `Test result: the record breaks at event ${firstBreak}` : 'Test result: your copy still matches'
    : verify.error ? 'Could not verify right now' : serverOk ? 'Verified: nothing in this record was changed' : `This record does not verify${serverFirstBad ? ` (from event ${serverFirstBad})` : ''}`;
  const explain = tampered
    ? firstBreak !== null
      ? `You changed event ${tamperedSeq}. Its fingerprint (hash) no longer matches, and because every event is linked to the one before it, everything after it is untrusted too. This is your browser copy; the stored record is untouched.`
      : 'Your edit produced the same canonical content, so nothing changed.'
    : verify.error ? 'The verification service did not answer. The events below are shown but not checked; try again in a moment.'
    : serverOk ? `Sauda's server recomputed all ${evs.length} event fingerprints, checked each link to the previous event and verified every Cloud KMS signature.`
    : headOk === false && serverFirstBad === null ? `${headText} Treat this record as untrustworthy.`
    : 'At least one event was altered, is out of order, or has an invalid signature. Treat everything from that point on as untrustworthy.';

  const steps: Step[] = shown.map((e) => {
    const lc = local?.find((c) => c.seq === e.seq);
    const sv = byseq.get(e.seq);
    const bad = lc ? lc.after_break : sv ? !(sv.hash_ok && sv.link_ok && sv.sig_ok) : false;
    const why = lc && lc.after_break ? (!lc.hash_ok ? 'Changed: fingerprint does not match' : !lc.link_ok ? 'Link to previous event broken' : 'After the break: untrusted')
      : sv && bad ? [!sv.hash_ok && 'fingerprint does not match', !sv.link_ok && 'link broken', !sv.sig_ok && 'signature invalid'].filter(Boolean).join(', ') : null;
    return {
      key: String(e.seq),
      state: bad ? 'bad' : (sv || lc) ? 'done' : 'todo',
      title: <span>{plain(e)}</span>,
      meta: <span className="xs faint">#{e.seq} · {ist(e.ts)}</span>,
      body: <>{detail(e)}{why && <div style={{ color: 'var(--bad)', fontWeight: 600 }}>{why}{e.seq === tamperedSeq ? ' (you edited this)' : ''}</div>}</>,
    };
  });

  const badge = tampered
    ? firstBreak !== null ? `Test: record breaks at step ${firstBreak}` : 'Test: your copy still matches'
    : verify.error ? 'Could not verify right now'
    : serverOk ? `Record verified · ${evs.length} signed steps · nothing changed`
    : `Record does not verify${serverFirstBad ? ` from step ${serverFirstBad}` : ''}`;

  return (
    <div className="stack lg">
      <Summary d={derived} />

      <section className="stack xs" aria-live="polite" aria-label="Verification">
        <div className={`ts-badge ${state}`}>
          <span className="ico"><Icon name={state === 'ok' ? 'shield' : state === 'bad' ? 'shieldx' : 'alert'} size={20} /></span>
          <span className="ts-badge-t grow">{badge}</span>
          {!tampered && !verify.error && !sigOk && <StatusPill tone="bad">{sigBad} invalid {sigBad === 1 ? 'signature' : 'signatures'}</StatusPill>}
          {!tampered && !verify.error && headOk === false && <StatusPill tone="bad">{headText}</StatusPill>}
          {tampered && <StatusPill tone="warn">Test copy in your browser</StatusPill>}
          {verify.error ? <Button size="sm" variant="secondary" icon="refresh" onClick={verify.reload}>Try again</Button> : null}
        </div>
        <Evidence label="How this was checked"><span>{title}.</span><span>{explain}</span>{!tampered && !verify.error && headOk == null && <span>No signed head on this record (older format), so missing events at the end cannot be ruled out.</span>}</Evidence>
      </section>

      <Story d={derived} />

      <TamperDemo events={evs} tamperedSeq={tamperedSeq} onTamper={(copy, seq) => { setTampered(copy); setTamperedSeq(seq); }} onReset={() => { setTampered(null); setTamperedSeq(null); }} />

      <section className="stack xs" aria-label="Full record">
        <Evidence label={`All ${evs.length} steps`} open={tampered ? true : undefined}>
          <Timeline steps={steps} label="Record events" />
        </Evidence>
        <Transcript events={evs} />
      <Evidence label="Technical evidence: hashes and signatures">
        <span>Negotiation <span className="code">{nid}</span>. Fingerprint = SHA-256 of the event payload as canonical JSON; the first event links to SHA-256 of the negotiation ID. Public key: <a href={`${process.env.NEXT_PUBLIC_API_BASE || ''}/pubkey`}>/pubkey</a>.</span>
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Type</th><th>Hash</th><th>Prev</th><th>Server</th><th>Signature scope</th></tr></thead>
            <tbody>
              {shown.map((e) => {
                const sv = byseq.get(e.seq); const lc = local?.find((c) => c.seq === e.seq);
                return (
                  <tr key={e.seq}>
                    <td className="mono">{e.seq}</td>
                    <td className="mono">{e.type}</td>
                    <td className="mono">{shortHash(lc && !lc.hash_ok ? lc.computed_hash : e.payload_hash, 6)}</td>
                    <td className="mono">{shortHash(e.prev_hash, 6)}</td>
                    <td className="mono">{sv ? `${sv.hash_ok ? 'h✓' : 'h✗'} ${sv.link_ok ? 'l✓' : 'l✗'} ${sv.sig_ok ? 's✓' : 's✗'}` : '—'}</td>
                    <td className="xs">{sv?.signature_scope || (sv?.sig_version ? `v${sv.sig_version}` : '—')}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Evidence>
      </section>
    </div>
  );
}

function headProblem(p?: string | null): string {
  if (!p) return 'The signed record of this chain doesn’t match.';
  if (/count/.test(p)) return 'Events are missing from the end of this record.';
  if (/last_hash/.test(p)) return 'The last event does not match the signed record of this chain.';
  if (/signature/.test(p)) return 'The signed record of this chain doesn’t match (invalid signature).';
  return 'The signed record of this chain doesn’t match.';
}

function TamperDemo({ events, tamperedSeq, onTamper, onReset }: {
  events: LedgerEvent[]; tamperedSeq: number | null;
  onTamper: (copy: LedgerEvent[], seq: number) => void; onReset: () => void;
}) {
  const candidates = events.filter((e) => e.payload && Object.keys(e.payload).length);
  const preferred = candidates.find((e) => /offer|cart|gate/.test(e.type)) || candidates[0];
  const [seq, setSeq] = useState<number>(preferred?.seq ?? 1);
  const target = events.find((e) => e.seq === seq);
  // UPI IDs are shown masked in the editor and restored before hashing, so an untouched field is not a change.
  const rawOf = (e?: LedgerEvent) => (e ? JSON.stringify(e.payload, null, 2) : '{}');
  const [text, setText] = useState(() => maskVpasIn(rawOf(target)));
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { if (target) setText(maskVpasIn(rawOf(target))); setErr(null); }, [seq]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!events.length) return null;

  function apply(payload: Record<string, unknown>) {
    const copy = events.map((e) => (e.seq === seq ? { ...e, payload } : { ...e }));
    onTamper(copy, seq);
  }

  function applyText() {
    try {
      const p = JSON.parse(unmaskWith(text, rawOf(target)));
      if (!p || typeof p !== 'object' || Array.isArray(p)) throw new Error('The event must be a JSON object');
      setErr(null);
      if (target && canonical(p) === canonical(target.payload)) { setErr('No change yet: edit a value first.'); return; }
      apply(p);
    } catch (e) { setErr(e instanceof Error ? `That is not valid JSON: ${e.message}` : String(e)); }
  }

  function oneByte() {
    if (!target) return;
    const p = structuredClone(target.payload) as Record<string, unknown>;
    const numKeys = Object.keys(p).filter((k) => typeof p[k] === 'number');
    const numKey = numKeys.find((k) => k.endsWith('_paise')) || numKeys[0];
    if (numKey) p[numKey] = (p[numKey] as number) - 1;
    else { const k = Object.keys(p)[0]; p[k] = String(p[k]) + ' '; }
    setText(maskVpasIn(JSON.stringify(p, null, 2)));
    apply(p);
  }

  return (
    <Card title="Test: try to break the record"
      subtitle="Change one value in a copy of this record, in this page only, and watch verification fail. The stored record is never touched."
      action={tamperedSeq !== null ? <Button size="sm" variant="secondary" icon="refresh" onClick={onReset}>Reset</Button> : null}>
      <div className="stack">
        <label className="field">Event to change
          <select className="input" value={seq} onChange={(e) => setSeq(parseInt(e.target.value, 10))}>
            {candidates.map((e) => <option key={e.seq} value={e.seq}>#{e.seq} · {plain(e)}</option>)}
          </select>
        </label>
        <div><Button variant="secondary" size="sm" onClick={oneByte}>Change one value (₹0.01)</Button></div>
        <Evidence label="Edit the raw event yourself">
          <label className="sr-only" htmlFor="tamper-json">Event payload JSON</label>
          <textarea id="tamper-json" className="input mono" rows={7} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label="Event payload JSON" />
          {err && <span className="xs" style={{ color: 'var(--bad)' }} role="alert">{err}</span>}
          <Button variant="secondary" onClick={applyText}>Apply my edit</Button>
        </Evidence>
      </div>
    </Card>
  );
}

function text(p: Record<string, unknown>): string {
  const m = p.text ?? p.message ?? p.raw_text ?? p.excerpt ?? '';
  if (m && typeof m === 'object') {
    const o = m as { type?: string; lines?: unknown[]; deliver_by?: string; max_advance_pct?: number; round?: number };
    const n = Array.isArray(o.lines) ? o.lines.length : 0;
    const t = String(o.type || '').toUpperCase();
    if (t === 'RFQ') return `Request for quotation: ${n} items${o.deliver_by ? `, deliver by ${o.deliver_by}` : ''}${o.max_advance_pct != null ? `, advance at most ${o.max_advance_pct}%` : ''}.`;
    if (t === 'COUNTER') return `Counter-offer for ${n} items with target prices.`;
    if (t === 'PO') return `Purchase order for ${n} items.`;
    return `Structured message${t ? ` (${t.toLowerCase()})` : ''}.`;
  }
  return String(m);
}

const ACTION_WORD: Record<string, string> = {
  run_negotiation: 'Starting the negotiation', cart: 'The assembled cart', place_order: 'Placing the order',
  issue_payment_mandate: 'Issuing the payment link', offer: 'An offer',
};

/** One plain sentence per ledger event. */
function plain(e: LedgerEvent): string {
  const p = e.payload || {};
  const sid = typeof p.supplier_id === 'string' ? supplierName(p.supplier_id) : '';
  switch (e.type) {
    case 'mandate.signed': return p.kind === 'cart' ? 'You approved and signed the cart' : p.kind === 'payment' ? 'Payment mandate signed' : 'You signed the limits';
    case 'mandate.revoked': return 'You switched off the limits';
    case 'rfq.sent': return `Asked ${sid} for a quote`;
    case 'offer.received': return `${sid} sent ${p.round && Number(p.round) > 1 ? `a revised offer (round ${p.round})` : 'a quote'}`;
    case 'guard.verdict': return p.blocked ? `${sid}'s message was blocked by safety screening` : `${sid}'s message passed safety screening`;
    case 'gate.decision': {
      const what = sid ? (Number(p.round) === 0 ? `${sid} (identity check)` : `${sid}'s offer`) : ACTION_WORD[String(p.action)] || 'An action';
      const v = String(p.verdict).toUpperCase();
      return v === 'DENY' ? `${what}: refused by the policy checks` : v === 'CONFIRM' ? `${what}: allowed only with your approval` : `${what}: passed the policy checks`;
    }
    case 'counter.sent': return `Sauda sent ${sid} a counter-offer (round ${p.round ?? '—'})`;
    case 'cart.assembled': return 'Sauda put together the best cart';
    case 'confirmation.requested': return 'Sauda asked for your approval';
    case 'confirmation.approved': case 'owner.approved': return 'You approved the cart';
    case 'confirmation.answered': return p.answer === 'approved' ? 'You approved the cart' : p.answer === 'declined' ? 'You declined the cart' : 'You answered the approval request';
    case 'payment.mismatch': return 'Your payment report did not match';
    case 'confirmation.declined': return 'You declined the cart';
    case 'po.sent': return `Purchase order sent to ${sid}`;
    case 'order.placed': return `Order placed with ${sid}`;
    case 'payment.issued': case 'payment_mandate.issued': return 'Payment link issued';
    case 'payment.claimed': case 'payment.settled': return 'You reported payment (UTR, not bank-verified)';
    case 'supplier.quarantined': return `${sid} was quarantined`;
    case 'supplier.spoof_suspected': return `${sid}'s reply did not match our request`;
    case 'attack.tested': return 'Attack test recorded';
    default: return e.type.replace(/[._]/g, ' ');
  }
}

function detail(e: LedgerEvent): string {
  const p = e.payload || {};
  const sid = typeof p.supplier_id === 'string' ? supplierName(p.supplier_id) : undefined;
  switch (e.type) {
    case 'mandate.signed': {
      const b = (p.body && typeof p.body === 'object' ? p.body : p) as Record<string, unknown>;
      return typeof b.budget_paise === 'number' ? `Budget ${rupees(b.budget_paise, true)} · advance at most ${b.max_advance_pct ?? '—'}%` : '';
    }
    case 'payment_mandate.issued': case 'payment.issued': return typeof p.amount_paise === 'number' ? `${rupees(p.amount_paise)} to ${String(p.payee_vpa_masked || 'the payout account on record')}` : '';
    case 'order.placed': return [typeof p.total_paise === 'number' ? rupees(p.total_paise) : '', p.po_ack_status ? `supplier: ${p.po_ack_status}` : ''].filter(Boolean).join(' · ');
    case 'offer.received': {
      const d = (p.data && typeof p.data === 'object' ? p.data : p) as Record<string, unknown>;
      const ls = Array.isArray(d.lines) ? (d.lines as { unit_price_paise?: number; qty?: number }[]) : [];
      return [typeof p.total_paise === 'number' ? rupees(p.total_paise) : ls.length ? `${ls.length} prices` : '', d.advance_pct != null ? `advance ${d.advance_pct}%` : '', d.delivery_days ? `delivery ${d.delivery_days} days` : ''].filter(Boolean).join(' · ');
    }
    case 'gate.decision': {
      const codes = (Array.isArray(p.reason_codes) ? p.reason_codes : Array.isArray(p.reasons) ? p.reasons : []) as string[];
      return codes.map((c) => reasonText(c, { supplier: sid })).join('. ');
    }
    case 'cart.assembled': return `${rupees(p.total_paise as number)}${typeof p.savings_paise === 'number' ? ` · ${rupees(p.savings_paise)} below opening quotes` : ''}`;
    default: return '';
  }
}

function Transcript({ events }: { events: LedgerEvent[] }) {
  const msgs = events.filter((e) => ['rfq.sent', 'offer.received', 'counter.sent', 'guard.verdict', 'attack.tested'].includes(e.type) && (text(e.payload) || e.type === 'guard.verdict'));
  if (!msgs.length) return null;
  return (
    <Evidence label="Messages with suppliers">
      <div className="stack">
        {msgs.map((e) => {
          const p = e.payload || {};
          const out = e.type === 'rfq.sent' || e.type === 'counter.sent';
          const blocked = (e.type === 'guard.verdict' && !!p.blocked) || p.guard_verdict === 'blocked' || (e.type === 'attack.tested' && !!(p.blocked || p.guard_blocked));
          if (e.type === 'guard.verdict' && !blocked) return null;
          const sid = typeof p.supplier_id === 'string' ? supplierName(p.supplier_id) : e.actor;
          return (
            <div key={e.seq} className={`msg ${blocked ? 'blocked' : out ? 'out' : ''}`}>
              <div className="msg-meta">
                <span>{out ? `Sauda → ${sid}` : `${sid} → Sauda`}</span>
                {p.round !== undefined && <span className="faint">round {String(p.round)}</span>}
                {blocked && <StatusPill tone="bad">Blocked · the AI never read it</StatusPill>}
                <span className="faint mono">#{e.seq}</span>
              </div>
              <div>{maskVpasIn(text(p)) || '(message withheld)'}</div>
            </div>
          );
        })}
      </div>
      <p className="xs faint">Supplier text is data, never instructions. Blocked messages are kept as evidence only.</p>
    </Evidence>
  );
}

// ---------------------------------------------------------------- value-first summary
// Everything below is derived from the ledger events already loaded. A figure is omitted when the events do not carry it.

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const sidOf = (p: Record<string, unknown>) => (typeof p.supplier_id === 'string' ? p.supplier_id : '');
const codesOf = (p: Record<string, unknown>) => (Array.isArray(p.reason_codes) ? p.reason_codes : Array.isArray(p.reasons) ? p.reasons : []).map(String);
const isDeny = (p: Record<string, unknown>) => String(p.verdict || '').toUpperCase() === 'DENY';
const listJoin = (xs: string[]) => (xs.length <= 1 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Short, plain clause for why a supplier was blocked ("asked for a 50% advance"). */
function blockClause(code: string, adv: number | null, maxAdv: number | null): string {
  switch (code.toUpperCase()) {
    case 'GUARD_BLOCKED': return 'hid instructions to the agent in its message';
    case 'GUARD_TIMEOUT': return 'sent a message that could not be screened in time';
    case 'ADVANCE_TOO_HIGH': return adv != null ? `asked for a ${adv}% advance${maxAdv != null ? ` (your limit is ${maxAdv}%)` : ''}` : 'asked for more advance than your limit';
    case 'PAYEE_MISMATCH': return 'asked to change its payout account';
    case 'OVER_CEILING': return 'priced items above your ceiling';
    case 'OVER_BUDGET': return 'would have taken you over budget';
    case 'SUPPLIER_UNKNOWN': return 'is not a registered supplier';
    case 'SUPPLIER_QUARANTINED': return 'is quarantined after earlier unsafe messages';
    case 'LATE_DELIVERY': return 'could not deliver by your date';
    case 'NONCE_NOT_ECHOED': return 'sent a reply that did not match our request';
    case 'INVALID_AMOUNT': return 'sent a zero or negative price';
    case 'ANOMALY': return 'sent unusual quantities or prices';
    default: return reasonText(code).replace(/^./, (c) => c.toLowerCase());
  }
}

type Phase = { key: string; title: string; events: LedgerEvent[]; lines: string[]; bad?: boolean; pending?: boolean };

interface Derived {
  asked: string[];
  rounds: { round: number; offers: number; blocked: number }[];
  allowed: string[];
  blocked: { sid: string; clauses: string[] }[];
  cartTotal: number | null;
  savings: number | null;
  approval: 'approved' | 'declined' | 'pending' | null;
  orders: { sid: string; total: number | null; ack: string }[];
  payment: 'claimed' | 'mismatch' | 'issued' | null;
  phases: Phase[];
}

function derive(evs: LedgerEvent[]): Derived {
  const asked: string[] = [];
  const offeredBy = new Set<string>();
  const blockedMap = new Map<string, Set<string>>();
  const roundMap = new Map<number, { offers: number; blocked: Set<string> }>();
  let maxAdv: number | null = null;
  const advBy = new Map<string, number>();
  let cartTotal: number | null = null; let savings: number | null = null;
  let approval: Derived['approval'] = null;
  const orders: Derived['orders'] = [];
  let payment: Derived['payment'] = null;
  let cur = 1;
  const R = (r: number) => { if (!roundMap.has(r)) roundMap.set(r, { offers: 0, blocked: new Set() }); return roundMap.get(r)!; };
  const block = (sid: string, codes: string[], round: number) => {
    if (!sid) return;
    if (!blockedMap.has(sid)) blockedMap.set(sid, new Set());
    codes.forEach((c) => blockedMap.get(sid)!.add(c));
    R(round).blocked.add(sid);
  };
  const lim: LedgerEvent[] = [], neg: LedgerEvent[] = [], appr: LedgerEvent[] = [], ord: LedgerEvent[] = [];

  for (const e of evs) {
    const p = e.payload || {};
    const sid = sidOf(p);
    const r = num(p.round) ?? null;
    if (r && r > 0 && /offer|counter/.test(e.type)) cur = Math.max(cur, r);
    const round = r && r > 0 ? r : cur;
    switch (e.type) {
      case 'mandate.signed': {
        if (p.kind === 'cart') { appr.push(e); break; }
        if (p.kind === 'payment') { ord.push(e); break; }
        const b = (p.body && typeof p.body === 'object' ? p.body : p) as Record<string, unknown>;
        maxAdv = num(b.max_advance_pct) ?? maxAdv;
        lim.push(e); break;
      }
      case 'mandate.revoked': lim.push(e); break;
      case 'rfq.sent': if (sid && !asked.includes(sid)) asked.push(sid); neg.push(e); break;
      case 'offer.received': {
        if (sid) offeredBy.add(sid);
        R(round).offers += 1;
        const d = (p.data && typeof p.data === 'object' ? p.data : p) as Record<string, unknown>;
        const a = num(d.advance_pct); if (sid && a != null) advBy.set(sid, a);
        if (p.guard_verdict === 'blocked' || p.guard_blocked === true) block(sid, ['GUARD_BLOCKED'], round);
        if (String(p.gate_verdict || '').toUpperCase() === 'DENY') block(sid, codesOf(p), round);
        neg.push(e); break;
      }
      case 'guard.verdict': if (p.blocked) block(sid, ['GUARD_BLOCKED'], round); neg.push(e); break;
      case 'gate.decision': {
        if (sid) { if (isDeny(p)) block(sid, codesOf(p), round); neg.push(e); }
        else ord.push(e);
        // Real gate reports carry per-rule results; R5's detail is { advance_pct: { supplier_id: pct } | pct, max_advance_pct }.
        const results = (Array.isArray(p.results) ? p.results : []) as { rule?: string; verdict?: string; reason_code?: string; detail?: unknown }[];
        for (const res of results) {
          const d = (res.detail && typeof res.detail === 'object' ? res.detail : {}) as Record<string, unknown>;
          if (res.reason_code === 'ADVANCE_TOO_HIGH' || res.rule === 'R5') {
            maxAdv = num(d.max_advance_pct) ?? maxAdv;
            const ap = d.advance_pct;
            if (ap && typeof ap === 'object') for (const [k, v] of Object.entries(ap as Record<string, unknown>)) { const n = num(v); if (n != null) advBy.set(k, n); }
            else if (sid && num(ap) != null) advBy.set(sid, num(ap)!);
          }
          if (sid && isDeny(p) && String(res.verdict).toUpperCase() === 'DENY' && res.reason_code) block(sid, [res.reason_code], round);
        }
        const a = num(p.advance_pct); if (sid && a != null) advBy.set(sid, a);
        break;
      }
      case 'counter.sent': case 'supplier.quarantined': case 'supplier.spoof_suspected': neg.push(e); break;
      case 'cart.assembled': cartTotal = num(p.total_paise); savings = num(p.savings_paise); neg.push(e); break;
      case 'confirmation.requested': if (!approval) approval = 'pending'; if (cartTotal == null) cartTotal = num(p.total_paise); appr.push(e); break;
      case 'confirmation.approved': case 'owner.approved': approval = 'approved'; appr.push(e); break;
      case 'confirmation.declined': approval = 'declined'; appr.push(e); break;
      case 'confirmation.answered': approval = p.answer === 'approved' ? 'approved' : p.answer === 'declined' ? 'declined' : approval; appr.push(e); break;
      case 'order.placed': orders.push({ sid, total: num(p.total_paise), ack: String(p.po_ack_status || '') }); ord.push(e); break;
      case 'po.sent': ord.push(e); break;
      case 'payment.issued': case 'payment_mandate.issued': if (!payment) payment = 'issued'; ord.push(e); break;
      case 'payment.claimed': case 'payment.settled': payment = 'claimed'; ord.push(e); break;
      case 'payment.mismatch': payment = 'mismatch'; ord.push(e); break;
      default: (sid ? neg : ord).push(e);
    }
  }
  if (approval === null && (orders.length || evs.some((e) => e.type === 'mandate.signed' && e.payload?.kind === 'cart'))) approval = 'approved';

  const blocked = [...blockedMap.entries()].map(([sid, codes]) => {
    const order = ['ADVANCE_TOO_HIGH', 'PAYEE_MISMATCH', 'GUARD_BLOCKED'];
    const sorted = [...codes].sort((a, b) => (order.indexOf(a) + 1 || 9) - (order.indexOf(b) + 1 || 9));
    return { sid, clauses: sorted.map((c) => blockClause(c, advBy.get(sid) ?? null, maxAdv)) };
  });
  const allowed = [...offeredBy].filter((s) => !blockedMap.has(s));
  const rounds = [...roundMap.entries()].sort((a, b) => a[0] - b[0]).map(([round, v]) => ({ round, offers: v.offers, blocked: v.blocked.size }));

  // Story lines: repetitive events collapse into one line each.
  const negLines: string[] = [];
  if (asked.length) negLines.push(`Asked ${plural(asked.length, 'supplier')} for quotes: ${listJoin(asked.map((s) => supplierName(s)))}`);
  for (const r of rounds) negLines.push(`Round ${r.round}: ${plural(r.offers, 'offer')}${r.blocked ? ` · ${r.blocked} blocked` : ''}`);
  const counters = neg.filter((e) => e.type === 'counter.sent').length;
  if (counters) negLines.push(`Sauda sent ${plural(counters, 'counter-offer')}`);
  if (cartTotal != null && neg.some((e) => e.type === 'cart.assembled')) negLines.push(`Best cart put together: ${rupees(cartTotal)}${savings != null && savings > 0 ? `, ${rupees(savings)} below opening quotes` : ''}`);

  const limLines = lim.map((e) => detail(e) || plain(e));
  const apprLines: string[] = [];
  if (appr.some((e) => e.type === 'confirmation.requested')) apprLines.push('Sauda asked for your approval');
  if (approval === 'approved') apprLines.push('You approved the cart');
  if (approval === 'declined') apprLines.push('You declined the cart');
  if (approval === 'pending') apprLines.push('Waiting for your answer');
  const ordLines: string[] = [];
  for (const o of orders) ordLines.push(`Order placed${o.sid ? ` with ${supplierName(o.sid)}` : ''}${o.total != null ? `: ${rupees(o.total)}` : ''}${o.ack ? ` (supplier: ${o.ack})` : ''}`);
  if (payment === 'issued') ordLines.push('Payment link issued');
  if (payment === 'claimed') ordLines.push('You reported payment (UTR, not bank-verified)');
  if (payment === 'mismatch') ordLines.push('Your payment report did not match');
  const deniedActions = ord.filter((e) => e.type === 'gate.decision' && isDeny(e.payload || {}));
  for (const e of deniedActions) ordLines.push(plain(e));

  const phases: Phase[] = [
    { key: 'lim', title: 'Limits signed', events: lim, lines: limLines },
    { key: 'neg', title: rounds.length ? `Negotiation · ${plural(rounds.length, 'round')}` : 'Negotiation', events: neg, lines: negLines },
    { key: 'appr', title: 'Your approval', events: appr, lines: apprLines, bad: approval === 'declined', pending: approval === 'pending' },
    { key: 'ord', title: 'Order & payment', events: ord, lines: ordLines, bad: payment === 'mismatch' || deniedActions.length > 0 },
  ];
  return { asked, rounds, allowed, blocked, cartTotal, savings, approval, orders, payment, phases };
}

function Summary({ d }: { d: Derived }) {
  const points: { tone: 'ok' | 'bad' | 'warn' | 'neutral'; text: string }[] = [];
  if (d.asked.length) points.push({ tone: 'ok', text: `Asked ${plural(d.asked.length, 'supplier')} for quotes${d.rounds.length ? ` and negotiated over ${plural(d.rounds.length, 'round')}` : ''}.` });
  if (d.allowed.length || d.blocked.length) points.push({ tone: 'ok', text: `${plural(d.allowed.length, 'offer')} allowed${d.allowed.length ? ` (${listJoin(d.allowed.map((s) => supplierName(s)))})` : ''}, ${d.blocked.length} blocked.` });
  for (const b of d.blocked) points.push({ tone: 'bad', text: `Blocked ${supplierName(b.sid)}: it ${listJoin(b.clauses)}.` });
  if (d.cartTotal != null) points.push({ tone: 'ok', text: `Final cart ${rupees(d.cartTotal)}${d.savings != null && d.savings > 0 ? `, ${rupees(d.savings)} less than the opening quotes` : ''}.` });
  if (d.approval === 'approved') points.push({ tone: 'ok', text: 'You approved the cart before anything was ordered.' });
  else if (d.approval === 'declined') points.push({ tone: 'neutral', text: 'You declined the cart, so nothing was ordered.' });
  else if (d.approval === 'pending') points.push({ tone: 'warn', text: 'Waiting for your approval. Nothing is ordered until you say yes.' });
  if (d.orders.length) points.push({ tone: 'ok', text: `${d.orders.length === 1 ? 'Order placed' : `${d.orders.length} orders placed`}${d.payment === 'claimed' ? '; you reported the payment' : d.payment === 'issued' ? '; payment link issued, not yet paid' : d.payment === 'mismatch' ? '; your payment report did not match' : ''}.` });
  else if (d.approval === 'approved') points.push({ tone: 'neutral', text: 'No order placed yet.' });

  const tiles: { label: string; value: string; sub?: string }[] = [];
  if (d.asked.length) tiles.push({ label: 'Suppliers asked', value: String(d.asked.length), sub: d.rounds.length ? plural(d.rounds.length, 'round') : undefined });
  if (d.allowed.length || d.blocked.length) tiles.push({ label: 'Offers blocked', value: `${d.blocked.length}`, sub: `${d.allowed.length} allowed` });
  if (d.cartTotal != null) tiles.push({ label: 'Final cart', value: rupees(d.cartTotal, true) });
  if (d.savings != null && d.savings > 0) tiles.push({ label: 'Saved', value: rupees(d.savings, true), sub: 'vs opening quotes' });

  return (
    <section className="stack" aria-labelledby="ts-h">
      <div className="ts-hero">
        <h1 id="ts-h">What Sauda did for you</h1>
      </div>
      {tiles.length > 0 && <div className="tiles">{tiles.map((t) => <div key={t.label} className="tile"><span className="label">{t.label}</span><span className="value">{t.value}</span>{t.sub && <span className="sub">{t.sub}</span>}</div>)}</div>}
      {points.length > 0 && (
        <ul className="ts-points">
          {points.map((p, i) => <li key={i}><span className={`dot ${p.tone}`} aria-hidden /><span>{p.text}</span></li>)}
        </ul>
      )}
    </section>
  );
}

function Story({ d }: { d: Derived }) {
  return (
    <section className="stack sm" aria-labelledby="story-h">
      <div className="section-h" style={{ marginBottom: 0 }}><h2 id="story-h">How it went</h2></div>
      <ol className="phases">
        {d.phases.map((ph) => {
          const st = ph.bad ? 'bad' : ph.pending ? 'cur' : ph.events.length ? 'done' : 'todo';
          return (
            <li key={ph.key} className={`phase ${st}`}>
              <span className="phase-dot">{st === 'done' ? <Icon name="check" size={12} label="Done" /> : st === 'bad' ? <Icon name="x" size={12} label="Problem" /> : st === 'cur' ? <Icon name="clock" size={12} label="Waiting" /> : <span className="sr-only">Not yet</span>}</span>
              <div className="stack xs" style={{ gap: 2 }}>
                <span className="phase-t">{ph.title}{st === 'todo' && <span className="small faint" style={{ fontWeight: 400 }}> · not yet</span>}</span>
                {ph.lines.length > 0 && <ul className="phase-lines">{ph.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
                {ph.events.length > 1 && (
                  <Evidence label={`${plural(ph.events.length, 'step')}`}>
                    <ul className="phase-lines" style={{ margin: 0 }}>
                      {ph.events.map((e) => { const dt = detail(e); return <li key={e.seq}><span style={{ color: 'var(--ink)' }}>{plain(e)}</span>{dt ? <span> · {dt}</span> : null} <span className="faint">#{e.seq}</span></li>; })}
                    </ul>
                  </Evidence>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
