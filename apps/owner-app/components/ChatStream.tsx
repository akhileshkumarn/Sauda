'use client';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { chat, getMandate, normalizeGate } from '@/lib/api';
import { maskVpasIn, reasonText } from '@/lib/format';
import { rememberNegotiation } from '@/lib/session';
import type { Draft, GateReport as GR, SseEvent } from '@/lib/types';
import { DraftCard } from './DraftCard';
import { emptyNeg, negDown, negGate, negGuard, negOffer, NegotiationPanel, type NegState } from './Negotiation';
import { Button, ButtonLink, Callout, Card, Evidence, Icon, PageHead } from './ui';

// Voice capture belongs to the voice agent; loaded client-side only.
const VoiceCapture = dynamic(() => import('@/components/voice').then((m) => m.VoiceCapture), { ssr: false, loading: () => null });

type Item =
  | { k: 'me'; text: string }
  | { k: 'agent'; text: string }
  | { k: 'tool'; name: string; status: string }
  | { k: 'draft'; draft: Draft }
  | { k: 'neg' }
  | { k: 'gate'; report: GR }
  | { k: 'confirm'; confirmation_id: string }
  | { k: 'done'; negotiation_id: string; status: string }
  | { k: 'error'; code: string; message: string }
  | { k: 'busy'; message: string; retry: string; mandate_id?: string };

const TOOL_LABEL: Record<string, [string, string]> = {
  draft_order: ['Reading your list and drafting the order', 'Draft ready'],
  run_negotiation: ['Asking suppliers for quotes and negotiating', 'Negotiation finished'],
  explain_cart: ['Explaining the cart', 'Explained'],
  place_order: ['Preparing the cart for your approval', 'Waiting for your approval'],
  issue_payment_mandate: ['Preparing the payment link', 'Payment link ready'],
};

const EXAMPLES = [
  'Diwali restock: 10 atta 5 kg, 20 sunflower oil 1 L, 12 Parle-G, 24 Maggi, 20 toor dal, sugar. Keep under ₹24,000',
  'Weekly restock: 5 Tata salt, 10 Maggi, 6 Fortune oil',
];

function asDraft(result: unknown): Draft | null {
  if (!result || typeof result !== 'object') return null;
  const r = result as Record<string, unknown>;
  if (Array.isArray(r.lines)) return r as unknown as Draft;
  if (r.draft && typeof r.draft === 'object' && Array.isArray((r.draft as Draft).lines)) return r.draft as Draft;
  return null;
}

function addDraft(next: Item[], d: Draft) {
  const key = JSON.stringify(d.lines.map((l) => [l.gtin, l.qty]));
  const dup = next.some((i) => i.k === 'draft' && JSON.stringify(i.draft.lines.map((l) => [l.gtin, l.qty])) === key);
  if (!dup) next.push({ k: 'draft', draft: d });
}

function reduce(items: Item[], ev: SseEvent): Item[] {
  const next = [...items];
  const last = next[next.length - 1];
  const ensureNeg = () => { if (!next.some((i) => i.k === 'neg')) next.push({ k: 'neg' }); };
  switch (ev.event) {
    case 'agent.text': {
      const text = String(ev.data?.text ?? '');
      if (!text) return items;
      if (last?.k === 'agent') {
        const sep = /[.!?]$/.test(last.text) && /^[A-Z0-9₹]/.test(text) ? '\n' : '';
        next[next.length - 1] = { k: 'agent', text: last.text + sep + text };
      } else next.push({ k: 'agent', text });
      return next;
    }
    case 'agent.tool': {
      const name = String(ev.data?.name ?? 'tool'); const status = String(ev.data?.status ?? '');
      if (/unreachable/.test(status) || name === 'supplier.load' || name === 'a2a.send' || name === 'adk') return next; // shown on supplier cards
      const idx = next.map((i) => (i.k === 'tool' ? i.name : '')).lastIndexOf(name);
      if (idx >= 0) next[idx] = { k: 'tool', name, status };
      else next.push({ k: 'tool', name, status });
      const d = asDraft(ev.data?.result);
      if (d) addDraft(next, d);
      return next;
    }
    case 'draft': { const d = asDraft(ev.data); if (d) addDraft(next, d); return next; }
    case 'offer': case 'guard.verdict': ensureNeg(); return next;
    case 'gate.report': {
      const g = normalizeGate(ev.data);
      if ((ev.data as { supplier_id?: string }).supplier_id) { ensureNeg(); return next; }
      if (g.verdict === 'DENY') next.push({ k: 'gate', report: g });
      return next;
    }
    case 'confirmation.request': next.push({ k: 'confirm', confirmation_id: ev.data.confirmation_id }); return next;
    case 'done': next.push({ k: 'done', negotiation_id: ev.data.negotiation_id, status: ev.data.status }); return next;
    case 'error': next.push({ k: 'error', code: ev.data?.code || 'ERROR', message: ev.data?.message || 'Something went wrong' }); return next;
    default: return items; // unknown events are ignored: the stream can never trigger an action
  }
}

function reduceNeg(s: NegState, ev: SseEvent): NegState {
  switch (ev.event) {
    case 'offer': return negOffer(s, ev.data);
    case 'guard.verdict': return negGuard(s, ev.data);
    case 'gate.report': return negGate(s, normalizeGate(ev.data) as GR & { supplier_id?: string; round?: number });
    case 'agent.tool': {
      const m = /^(\w+) unreachable/.exec(String(ev.data?.status || ''));
      if (m) return negDown(s, m[1], 'unreachable');
      if (ev.data?.name === 'run_negotiation' && /done|complete|finished/.test(String(ev.data.status))) return { ...s, done: true };
      return s;
    }
    case 'confirmation.request': case 'done': return s.order.length ? { ...s, done: true } : s;
    default: return s;
  }
}

export function ChatStream({ runMandateId }: { runMandateId?: string }) {
  const [items, setItems] = useState<Item[]>([]);
  const [neg, setNeg] = useState<NegState>(() => emptyNeg());
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const abort = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const started = useRef(false);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const send = useCallback(async (message: string, mandate_id?: string, display?: string) => {
    if (!message.trim() || busyRef.current) return;
    busyRef.current = true;
    abort.current?.abort();
    const ac = new AbortController(); abort.current = ac;
    setBusy(true); setInput('');
    if (taRef.current) taRef.current.style.height = '';
    setItems((it) => [...it, { k: 'me', text: display || message }]);
    try {
      const seen = new Set<string>();
      for await (const ev of chat({ message, mandate_id }, ac.signal)) {
        if (ev.event === 'done' && ev.data?.negotiation_id) rememberNegotiation(ev.data.negotiation_id);
        if (ev.event !== 'agent.text') {
          const key = ev.event + JSON.stringify(ev.data);
          if (seen.has(key)) continue; // server can relay the same event twice
          seen.add(key);
        }
        if (ev.event === 'error' && /409/.test(String(ev.data?.code))) {
          // Another owner session holds this shop's negotiation: a friendly wait state, not an error.
          setItems((it) => [...it, { k: 'busy', message: String(ev.data?.message || ''), retry: message, mandate_id }]);
          continue;
        }
        setNeg((s) => reduceNeg(s, ev));
        setItems((it) => reduce(it, ev));
      }
    } catch (e) {
      if (!ac.signal.aborted) setItems((it) => [...it, { k: 'error', code: 'NETWORK', message: e instanceof Error ? e.message : String(e) }]);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (runMandateId && !started.current) {
      started.current = true;
      getMandate(runMandateId)
        .then((m) => {
          const b = m.body as { allowed_supplier_ids?: string[]; max_advance_pct?: number };
          setNeg((s) => (s.order.length ? { ...s, maxAdvance: b.max_advance_pct ?? null } : emptyNeg(b.allowed_supplier_ids || [], b.max_advance_pct ?? null)));
        })
        .catch(() => { /* the cards fill in from events anyway */ });
      send(`Start the negotiation under mandate ${runMandateId}.`, runMandateId, 'Start negotiating within my signed limits.');
    }
  }, [runMandateId, send]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [items.length]);
  // No abort-on-unmount: React strict mode's dev double-mount would kill the first stream. A stale stream only updates unmounted state (a no-op).

  const lastDraftIdx = items.map((i) => i.k).lastIndexOf('draft');

  return (
    <div className="stack lg">
      <PageHead eyebrow="Restock" title={runMandateId ? 'Sauda is negotiating for you' : 'What do you need to restock?'}>
        {runMandateId ? 'Live view of quotes and safety checks. Nothing is ordered until you approve.' : 'Type or speak your list. You check every line and sign your limits before Sauda talks to any supplier.'}
      </PageHead>

      {items.length === 0 && !runMandateId && (
        <Card title="Try an example" subtitle="Tap one to send it, or write your own below.">
          <div className="chips">
            {EXAMPLES.map((s) => <button key={s} type="button" className="chip-btn" disabled={busy} onClick={() => send(s)}>{s}</button>)}
          </div>
        </Card>
      )}

      <div className="chat" aria-live="polite" aria-relevant="additions">
        {items.map((it, i) => <ItemView key={i} it={it} neg={neg} stale={it.k === 'draft' && i !== lastDraftIdx} busy={busy} onRetry={send} />)}
        {busy && <div className="event-line" role="status"><span className="spinner" aria-hidden /> Sauda is working…</div>}
        <div ref={endRef} />
      </div>

      <form className="composer" style={{ flexDirection: 'column', alignItems: 'stretch' }} onSubmit={(e) => { e.preventDefault(); send(input); }}>
        {!runMandateId && (
          <div className="voice-slot">
            <VoiceCapture disabled={busy} onUseTranscript={(t: string) => send(t)} />
          </div>
        )}
        <div className="row sm" style={{ alignItems: 'flex-end' }}>
          <label htmlFor="chat-input" className="sr-only">Message Sauda</label>
          <textarea id="chat-input" ref={taRef} className="input grow" rows={1} value={input}
            onChange={(e) => { setInput(e.target.value); const t = e.target; t.style.height = 'auto'; t.style.height = `${Math.min(160, t.scrollHeight)}px`; }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder={runMandateId ? 'Ask Sauda about this restock' : 'Type your list, e.g. 10 atta, 20 oil'} maxLength={2000} />
          <Button type="submit" disabled={busy || !input.trim()} aria-label="Send message">{busy ? <span className="spinner" aria-hidden /> : 'Send'}</Button>
        </div>
      </form>
    </div>
  );
}

function ItemView({ it, neg, stale, busy, onRetry }: { it: Item; neg: NegState; stale: boolean; busy: boolean; onRetry: (m: string, mandate?: string) => void }) {
  switch (it.k) {
    case 'busy':
      return (
        <div style={{ alignSelf: 'stretch' }} className="callout warn" role="status">
          <Icon name="user" />
          <div className="stack sm grow">
            <span><b>Someone else is restocking this shop right now.</b> Only one negotiation can run per shop at a time, so your limits and money stay safe. Try again in a minute.</span>
            <div><Button size="sm" variant="secondary" icon="refresh" disabled={busy} onClick={() => onRetry(it.retry, it.mandate_id)}>Try again</Button></div>
          </div>
        </div>
      );
    case 'me': return <div className="bubble me">{it.text}</div>;
    case 'agent': return <div className="bubble agent">{it.text}</div>;
    case 'tool': {
      const running = /run|start|pending/i.test(it.status);
      const waiting = /await/i.test(it.status);
      const lbl = TOOL_LABEL[it.name];
      return (
        <div className="event-line">
          {running ? <span className="spinner" aria-hidden /> : <span style={{ color: waiting ? 'var(--warn)' : 'var(--ok)' }}><Icon name={waiting ? 'pause' : 'check'} /></span>}
          <span>{lbl ? (running ? lbl[0] : lbl[1]) : it.name.replace(/_/g, ' ')}</span>
        </div>
      );
    }
    case 'draft':
      return stale
        ? <div className="event-line"><Icon name="info" /> An earlier draft was replaced by the one below.</div>
        : <DraftCard draft={it.draft} />;
    case 'neg': return <NegotiationPanel s={neg} />;
    case 'gate': {
      const denied = it.report.results.filter((r) => r.verdict === 'DENY');
      return (
        <div style={{ alignSelf: 'stretch' }} className="stack sm">
          <Callout tone="bad" title="Sauda stopped.">{denied.map((r) => reasonText(r.reason_code || '')).join('. ') || 'A safety check failed.'}</Callout>
          <Evidence>{denied.map((r) => <span key={r.rule} className="mono">{maskVpasIn(`${r.rule} ${r.reason_code} ${r.detail || ''}`)}</span>)}</Evidence>
        </div>
      );
    }
    case 'confirm':
      return (
        <Card tone="warn" title={<span className="row sm"><Icon name="alert" size={18} />Your approval is needed</span>} subtitle="The cart is ready. Check every line, the supplier and the payment terms on one screen.">
          <ButtonLink href={`/confirm/${encodeURIComponent(it.confirmation_id)}`} block icon="arrow">Review cart and approve</ButtonLink>
        </Card>
      );
    case 'done':
      return (
        <div className="event-line">
          <Icon name="shield" />
          <Link href={`/trust/${encodeURIComponent(it.negotiation_id)}`}>See the signed record of this restock</Link>
        </div>
      );
    case 'error':
      return (
        <div style={{ alignSelf: 'stretch' }} className="stack sm">
          <Callout tone="bad" title={it.code === 'NETWORK' ? 'Connection lost.' : 'Sauda could not finish.'}>
            {it.code === 'NETWORK' ? 'Check your internet and send your message again. Nothing was ordered.' : `${it.message}. Nothing was ordered; you can try again.`}
          </Callout>
          <Evidence><span className="mono">{maskVpasIn(`${it.code}: ${it.message}`)}</span></Evidence>
        </div>
      );
  }
}

