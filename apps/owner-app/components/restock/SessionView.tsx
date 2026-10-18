'use client';
// One persistent restock session (/restock/[sid]). The server copy is the source of truth: the page loads it
// from GET /restock/sessions/{sid}, autosaves line edits with PATCH (+version), and applies every spoken or typed
// sentence as one POST /turns. Survives refresh, navigation, closing the browser and a new sign-in.
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  MOCK, cancelSession, postVoiceTelemetry, conflictSession, createSession, getNegotiation, getSession, patchSession, postTurn, prepareSession,
} from '@/lib/api';
import { ist, relTime } from '@/lib/format';
import { allUtts, debugOn, mark, newUtt, setServer } from '@/lib/latency';
import type { Clarification, ClarOption, Draft, NegotiationView, PrepareResponse, ProductRef, RestockSession, TurnClarification, TurnOp } from '@/lib/types';
import type { FinalMeta } from '@/lib/voice';
import { DraftEditor, type EditLine } from '../DraftCard';
import { MandateForm } from '../MandateForm';
import { EDITABLE_STATUSES, negotiationLabel, OrderPill, SessionPill } from '../status';
import { Button, ButtonLink, Callout, Card, ErrorState, Evidence, Icon, Money, Skeleton, StatusPill, Steps } from '../ui';
import { BrandMark } from '../BrandMark';

import { RESTOCK_STEPS } from './steps';
const STEP_OF: Record<string, number> = { draft: 0, awaiting_review: 0, negotiating: 2, awaiting_approval: 3, ordered: 4, completed: 4 };
import { Sheet } from '../ui-client';
import { LatencyPanel } from './LatencyPanel';

const VoiceControl = dynamic(() => import('@/components/voice').then((m) => m.VoiceControl), { ssr: false, loading: () => null });

type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error';
const SAVE_DEBOUNCE_MS = 600;

const statusOf = (e: unknown) => (e as { status?: number })?.status;
const codeOf = (e: unknown) => (e as { code?: string })?.code;
const uuid = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `c${Date.now()}${Math.random().toString(36).slice(2)}`);
const optLabel = (o: ClarOption) => (typeof o === 'string' ? o : [o.brand && !o.name.toLowerCase().includes(o.brand.toLowerCase()) ? o.brand : '', o.name, o.pack_size && !o.name.toLowerCase().includes(String(o.pack_size).toLowerCase()) ? o.pack_size : ''].filter(Boolean).join(' '));
const toLines = (s: RestockSession): EditLine[] => (s.draft?.lines || []).map((l) => ({ ...l }));
// Server contract: [{gtin, qty, confidence?}] (it re-derives names and ceilings). Mock mode keeps the full line.
const patchLine = (l: EditLine) => {
  if (!MOCK) return { gtin: l.gtin, qty: l.qty, ...(l.confidence ? { confidence: l.confidence } : {}) };
  const { applied: _a, added: _b, ...rest } = l; void _a; void _b; return rest;
};

function toDraft(s: RestockSession, prep?: PrepareResponse | null): Draft {
  const sm = prep?.suggested_mandate || {};
  return {
    shop_id: s.shop_id,
    lines: s.draft.lines,
    stated_budget_paise: s.draft.stated_budget_paise ?? null,
    suggested_budget_paise: sm.budget_paise ?? s.draft.stated_budget_paise ?? s.draft.budget_estimate_paise ?? null,
    budget_estimate_paise: s.draft.budget_estimate_paise ?? null,
    clarifications: s.draft.clarifications || [],
    unmatched: s.draft.unmatched || [],
    festival: s.draft.festival ?? null,
    assumptions: s.draft.assumptions,
    budget_notes: s.draft.budget_notes,
    deliver_by: sm.deliver_by || s.draft.deliver_by,
    allowed_supplier_ids: sm.allowed_supplier_ids || s.draft.allowed_supplier_ids,
  };
}

function changedGtins(before: EditLine[], after: EditLine[], ops: TurnOp[]): Set<string> {
  const b = new Map(before.map((l) => [l.gtin, l.qty]));
  const out = new Set<string>();
  for (const l of after) if (b.get(l.gtin) !== l.qty) out.add(l.gtin);
  for (const o of ops) { if (o.gtin) out.add(String(o.gtin)); if (o.to) out.add(String(o.to)); }
  return out;
}

export function SessionView({ sid }: { sid: string }) {
  const router = useRouter();
  const [s, setS] = useState<RestockSession | null>(null);
  const [loadErr, setLoadErr] = useState<unknown>(null);
  const [lines, setLinesState] = useState<EditLine[]>([]);
  const [save, setSave] = useState<SaveState>('idle');
  const [notice, setNotice] = useState<string | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [clar, setClar] = useState<TurnClarification | null>(null);
  const [lowConf, setLowConf] = useState<{ text: string; utt: string } | null>(null);
  const [highlight, setHighlight] = useState<Set<string>>(new Set());
  const [inflight, setInflight] = useState(0);
  const [turnErr, setTurnErr] = useState<{ text: string; source: 'voice' | 'text'; ctid: string; utt: string; msg: string } | null>(null);
  const [prep, setPrep] = useState<PrepareResponse | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [prepBusy, setPrepBusy] = useState(false);
  const [prepErr, setPrepErr] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [titleText, setTitleText] = useState('');
  const [arming, setArming] = useState(false);
  const [busyAct, setBusyAct] = useState(false);
  const [dbg, setDbg] = useState(false);
  const [topSlot, setTopSlot] = useState<HTMLDivElement | null>(null);
  const [footSlot, setFootSlot] = useState<HTMLDivElement | null>(null);

  const ver = useRef(0);
  const linesRef = useRef<EditLine[]>([]);
  const editGen = useRef(0);
  const dirty = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const renderUtt = useRef<string | null>(null);
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const hlTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const adopt = useCallback((x: RestockSession, replaceLines = true) => {
    setS(x); ver.current = x.version; setTitleText(x.title);
    if (replaceLines) { const ls = toLines(x); linesRef.current = ls; setLinesState(ls); dirty.current = false; }
  }, []);

  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      const x = await getSession(sid);
      adopt(x);
      if (x.status === 'awaiting_review' && x.negotiation_id) setReviewing(true);
    } catch (e) { setLoadErr(e); }
  }, [sid, adopt]);
  useEffect(() => { setDbg(debugOn()); void load(); }, [load]);

  // Mark "draft rendered" after the DOM commits the server's new draft.
  useEffect(() => {
    const u = renderUtt.current;
    if (!u) return;
    renderUtt.current = null;
    requestAnimationFrame(() => {
      mark(u, 'draft_rendered');
      const x = allUtts().find((z) => z.id === u);
      if (x) void postVoiceTelemetry(sid, Object.entries(x.marks).map(([name, t]) => ({ name, t: Math.round(t as number), utt: u })));
    });
  }, [s, sid]);

  const enqueue = useCallback(<T,>(f: () => Promise<T>): Promise<T> => {
    const p = queue.current.then(f, f);
    queue.current = p.catch(() => undefined);
    return p;
  }, []);

  const doSave = useCallback(() => enqueue(async () => {
    if (!dirty.current) return;
    const gen = editGen.current;
    setSave('saving');
    try {
      const x = await patchSession(sid, { version: ver.current, lines: linesRef.current.map(patchLine) });
      const untouched = editGen.current === gen;
      adopt(x, untouched);
      if (untouched) { dirty.current = false; setSave('saved'); } else setSave('dirty');
    } catch (e) {
      const srv = conflictSession(e);
      if (statusOf(e) === 409 && srv) {
        adopt(srv); setSave('saved');
        setNotice(codeOf(e) === 'version_conflict'
          ? 'This restock was changed in another tab or device. Showing the latest saved version; check your last change.'
          : 'This restock can no longer be edited. Showing the saved version.');
      } else if (statusOf(e) === 409) {
        setSave('idle'); setNotice('This restock can no longer be edited.'); void load();
      } else setSave('error');
    }
  }), [enqueue, sid, adopt, load]);

  const flushSave = useCallback(async () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    if (dirty.current) await doSave();
  }, [doSave]);

  const setLines = useCallback((f: (ls: EditLine[]) => EditLine[]) => {
    const next = f(linesRef.current);
    linesRef.current = next; setLinesState(next);
    dirty.current = true; editGen.current++;
    setSave('dirty');
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { timer.current = null; void doSave(); }, SAVE_DEBOUNCE_MS);
  }, [doSave]);

  // Save pending edits before leaving the page.
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty.current) { void doSave(); e.preventDefault(); } };
    window.addEventListener('beforeunload', warn);
    return () => { window.removeEventListener('beforeunload', warn); if (dirty.current) void doSave(); };
  }, [doSave]);

  const rename = useCallback((t: string) => {
    const title = t.trim().slice(0, 80);
    if (!s || !title || title === s.title) { setTitleText(s?.title || ''); return; }
    void enqueue(async () => {
      setSave('saving');
      try { const x = await patchSession(sid, { version: ver.current, title }); adopt(x, !dirty.current); setSave(dirty.current ? 'dirty' : 'saved'); }
      catch (e) { const srv = conflictSession(e); if (srv) { adopt(srv); setSave('saved'); setNotice('This restock was changed elsewhere; the name was not saved. Try again.'); } else setSave('error'); }
    });
  }, [s, sid, enqueue, adopt]);

  const startReview = useCallback(async () => {
    setPrepErr(null); setPrepBusy(true);
    try {
      await flushSave();
      const r = await enqueue(() => prepareSession(sid));
      adopt(r.session); setPrep(r); setReviewing(true);
      requestAnimationFrame(() => document.getElementById('limits')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    } catch (e) {
      setPrepErr(statusOf(e) === 409 ? 'Someone else is restocking this shop right now. Only one negotiation runs per shop at a time; try again in a minute.'
        : statusOf(e) === 422 ? `Fix this first: ${(e as Error).message}` : (e as Error)?.message || 'Could not prepare the limits.');
    } finally { setPrepBusy(false); }
  }, [flushSave, enqueue, sid, adopt]);

  const sendTurn = useCallback(async (text: string, source: 'voice' | 'text', uttIn?: string, ctidIn?: string) => {
    const t = text.trim();
    if (!t) return;
    const utt = uttIn || newUtt(source, source === 'text' ? 'typed' : 'webspeech');
    const ctid = ctidIn || uuid();
    setTurnErr(null); setLowConf(null);
    setInflight((n) => n + 1);
    try {
      await flushSave();
      const before = linesRef.current;
      const r = await enqueue(() => { mark(utt, 'turn_sent'); return postTurn(sid, { client_turn_id: ctid, text: t, source }); });
      mark(utt, 'turn_applied');
      setServer(utt, r.latency_ms || null, t.length);
      renderUtt.current = utt;
      adopt(r.session);
      const ch = changedGtins(before, toLines(r.session), r.ops || []);
      setHighlight(ch);
      if (hlTimer.current) clearTimeout(hlTimer.current);
      hlTimer.current = setTimeout(() => setHighlight(new Set()), 2600);
      setReply(r.reply || null);
      setClar(r.clarification && r.clarification.options?.length ? r.clarification : null);
      const nav = (r.ops || []).find((o) => o.op === 'navigate');
      if (nav?.to === 'approval') {
        if (r.session.confirmation_id) router.push(`/confirm/${encodeURIComponent(r.session.confirmation_id)}`);
        else setReply('There is no cart to approve yet. First sign your limits; Sauda then negotiates and brings the cart to you.');
      } else if (nav?.to === 'review') void startReview();
      else if (nav?.to === 'new_restock') { const n = await createSession(); router.push(`/restock/${encodeURIComponent(n.sid)}`); }
    } catch (e) {
      if (statusOf(e) === 409) { setReply('This restock is locked now, so changes cannot be applied.'); void load(); }
      else setTurnErr({ text: t, source, ctid, utt, msg: statusOf(e) ? (e as Error).message : 'Could not reach Sauda.' });
    } finally { setInflight((n) => n - 1); }
  }, [flushSave, enqueue, sid, adopt, router, startReview, load]);

  const onVoiceFinal = useCallback((text: string, meta: FinalMeta) => {
    if (meta.confidence !== undefined && meta.confidence > 0 && meta.confidence < 0.6) { setLowConf({ text, utt: meta.uttId }); return; }
    void sendTurn(text, 'voice', meta.uttId || undefined);
  }, [sendTurn]);

  const sendTyped = () => {
    const t = input.trim(); if (!t) return;
    setInput(''); if (taRef.current) taRef.current.style.height = '';
    void sendTurn(t, 'text');
  };

  // The server keeps the pending op; a new turn naming the option answers it.
  const pickClar = (o: ClarOption, ownerWords?: string) => {
    const qty = MOCK && ownerWords ? /(\d+)/.exec(ownerWords)?.[1] : undefined;
    setClar(null);
    void sendTurn(`${qty ? `${qty} ` : ''}${typeof o === 'string' ? o : o.name}`, 'text');
  };
  const onDraftClarify = (c: Clarification, opt: ProductRef) => pickClar(opt, c.owner_words);

  async function cancel() {
    setBusyAct(true);
    try { await flushSave(); const x = await cancelSession(sid); adopt(x); setArming(false); setReviewing(false); }
    catch (e) { setNotice((e as Error)?.message || 'Could not cancel'); }
    finally { setBusyAct(false); }
  }
  async function copyToNew() {
    if (!s) return;
    setBusyAct(true);
    try {
      const n = await createSession(`${s.title} (copy)`.slice(0, 80));
      const x = s.draft.lines.length ? await patchSession(n.sid, { version: n.version, lines: s.draft.lines.map((l) => patchLine(l)), stated_budget_paise: s.draft.stated_budget_paise ?? null }) : n;
      router.push(`/restock/${encodeURIComponent(x.sid)}`);
    } catch (e) { setNotice((e as Error)?.message || 'Could not copy'); setBusyAct(false); }
  }

  if (loadErr) {
    return (
      <div className="stack lg">
        <ErrorState error={loadErr} onRetry={load} title={statusOf(loadErr) === 404 ? 'This restock was not found' : 'Could not load this restock'} />
        <ButtonLink href="/restock" variant="secondary" icon="arrow">All restocks</ButtonLink>
      </div>
    );
  }
  if (!s) return <SessionSkeleton />;

  const editable = EDITABLE_STATUSES.has(s.status);
  const draft = toDraft(s, prep);
  const turns = s.turns || [];
  const lastSauda = [...turns].reverse().find((t) => t.role === 'sauda');
  const showReply = reply || lastSauda?.text || null;
  const draftClar = s.draft.clarifications || [];

  const atCeiling = lines.reduce((t, l) => t + l.qty * l.ceiling_paise, 0);
  // The same question is already shown under its line; don't repeat it above the composer.
  const clarOnLine = !!clar && draftClar.some((c) => c.question === clar.question || (!!clar.gtin && c.gtin === clar.gtin && lines.some((l) => l.gtin === c.gtin)));
  const sauda = inflight > 0 ? null : clar && showReply?.endsWith(clar.question) ? showReply.slice(0, -clar.question.length).trim() || showReply : showReply;
  const budget = draft.stated_budget_paise || 0;
  const overBudget = budget > 0 && atCeiling > budget;
  const jumpToQuestion = () => {
    const el = document.querySelector<HTMLElement>('.rf-lines .ask');
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
  };

  const step = reviewing && editable ? 1 : STEP_OF[s.status];
  const hasDock = editable && !reviewing;
  const ownerTurns = turns.filter((t) => t.role === 'owner').length;
  return (
    <div className={`stack lg rs ${hasDock ? 'has-dock' : ''}`} style={{ flex: 1 }}>
      <div className="stack sm rs-head">
        <div className="row between sm">
          <Link href="/restock" className="rf-back"><span style={{ transform: 'rotate(180deg)', display: 'inline-flex' }}><Icon name="chev" size={14} /></span>Restocks</Link>
          <div className="row sm">
            {editable && <SaveIndicator state={save} onRetry={() => { dirty.current = true; void doSave(); }} />}
            <SessionPill status={s.status} />
          </div>
        </div>
        <label className="sr-only" htmlFor="sess-title">Restock name</label>
        <input id="sess-title" className="title-input" value={titleText} readOnly={!editable} maxLength={80} title={`Started ${ist(s.created_at)} · saved ${relTime(s.updated_at)}`}
          onChange={(e) => setTitleText(e.target.value)} onBlur={(e) => editable && rename(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') { setTitleText(s.title); (e.target as HTMLInputElement).blur(); } }} />
        {step !== undefined && <div className="rs-steps"><Steps steps={RESTOCK_STEPS} current={step} label="Restock progress" /></div>}
      </div>

      {notice && <Callout tone="warn">{notice} <button type="button" className="linkbtn rf-tap" style={{ minHeight: 32 }} onClick={() => setNotice(null)}>OK</button></Callout>}

      {!editable && <LockedStatus s={s} />}

      <DraftEditor draft={draft} lines={lines} setLines={setLines} readOnly={!editable || reviewing} highlight={highlight} hideHead={editable && !reviewing}
        title={editable ? 'Your list' : 'The list'} onClarify={editable ? onDraftClarify : undefined}
        footer={editable && reviewing ? (
          <div><Button variant="secondary" size="sm" icon="pen" onClick={() => setReviewing(false)}>Edit the list</Button></div>
        ) : null} />

      {turns.length > 0 && (
        <details className="evidence rs-convo">
          <summary><span className="chev"><Icon name="chev" size={14} /></span>Conversation · {ownerTurns}</summary>
          <div className="ev-body turns" style={{ fontFamily: 'inherit' }}>
            {turns.slice(-12).map((t) => (
              <div key={t.turn_id} className={`bubble ${t.role === 'owner' ? 'me' : 'agent'}`} style={{ fontSize: 14 }}>
                {t.role === 'owner' && t.source === 'voice' ? <span title="Spoken" style={{ marginRight: 4, display: 'inline-flex', verticalAlign: 'middle' }}><Icon name="mic" size={12} label="Spoken" /></span> : null}{t.text}
              </div>
            ))}
          </div>
        </details>
      )}

      {editable && reviewing && (
        <div id="limits" className="stack lg panel panel-accent rs-limits">
          <div className="rs-auth">
            <span className="rs-auth-ico" aria-hidden><Icon name="lock" size={16} /></span>
            <div className="stack xs">
              <b>Now you authorise money</b>
              <span className="small muted">Up to here Sauda only understood your list. These limits are the most it may spend; signing still buys nothing.</span>
            </div>
          </div>
          <MandateForm draft={draft} lines={lines} negotiationId={prep?.negotiation_id || s.negotiation_id || undefined} sid={sid} />
        </div>
      )}

      {editable && !reviewing && (
        <div className="rf-cancel">
          <button type="button" className="linkbtn muted rf-tap" onClick={() => setArming(true)}>Cancel this restock</button>
          <Sheet open={arming} onClose={() => !busyAct && setArming(false)} title="Cancel this restock?">
            <p className="muted">It stays in your history as cancelled. Nothing has been signed or ordered.</p>
            <Button variant="danger-solid" block busy={busyAct} busyLabel="Cancelling…" onClick={cancel}>Cancel restock</Button>
            <Button variant="ghost" block onClick={() => setArming(false)} disabled={busyAct}>Keep it</Button>
          </Sheet>
        </div>
      )}

      {!editable && (
        <div><Button variant="secondary" size="sm" icon="plus" busy={busyAct} busyLabel="Copying…" onClick={copyToNew}>Copy into a new restock</Button></div>
      )}

      {dbg && <LatencyPanel />}

      {editable && !reviewing && (
        <form className="dock rf-dock rs-assist" aria-label="Talk to Sauda to change the list" onSubmit={(e) => { e.preventDefault(); sendTyped(); }}>
          <div className="sr-only" role="status" aria-live="polite">{inflight > 0 ? 'Updating the list…' : sauda || ''}</div>
          <div className="as-head">
            <BrandMark size={24} />
            <div className="stack xs grow">
              <b>Sauda</b>
              <span className="as-sub">{inflight > 0 ? 'Updating your list…' : 'Understands your list. Cannot spend money.'}</span>
            </div>
          </div>
          {turns.length > 0 && (
            <ol className="as-log" aria-label="Conversation so far">
              {turns.slice(-8).map((t) => (
                <li key={t.turn_id} className={t.role === 'owner' ? 'me' : 'sauda'}>
                  {t.role === 'owner' && t.source === 'voice' ? <span className="as-src"><Icon name="mic" size={12} label="Spoken" /></span> : null}{t.text}
                </li>
              ))}
            </ol>
          )}
          {inflight > 0 ? (
            <div className="rf-toast busy" aria-hidden><span className="spinner" />Updating the list…</div>
          ) : sauda ? (
            <div className={`rf-toast ${lastSauda && sauda && lastSauda.text.startsWith(sauda) ? 'in-log' : ''}`} key={sauda} aria-hidden>
              <span className="s">S</span>
              <span className="grow clamp2">{sauda}</span>
            </div>
          ) : null}
          {clar && !clarOnLine && (
            <div className="ask" role="group" aria-label={clar.question} style={{ paddingTop: 0 }}>
              <span className="ask-q clamp2">{clar.question}</span>
              <div className="chips">
                {clar.options.slice(0, 4).map((o, i) => (
                  <button type="button" key={typeof o === 'string' ? o : o.gtin || i} className="chip-btn" disabled={inflight > 0} onClick={() => pickClar(o, clar.owner_words)}>{optLabel(o)}</button>
                ))}
                <button type="button" className="chip-btn rf-skip" onClick={() => setClar(null)}>Skip</button>
              </div>
            </div>
          )}
          {!clar && draftClar.length > 0 && (
            <button type="button" className="rf-qhint" onClick={jumpToQuestion}><span className="dot" aria-hidden /><span>Sauda has a question on the list above</span></button>
          )}
          {lowConf && <LowConfidence text={lowConf.text} onSend={(t) => sendTurn(t, 'voice', lowConf.utt)} onDrop={() => setLowConf(null)} />}
          {turnErr && (
            <Callout tone="warn" title="Not applied yet.">
              {turnErr.msg} “{turnErr.text}”{' '}
              <span className="row sm wrap" style={{ marginTop: 6 }}>
                <Button size="sm" icon="refresh" onClick={() => sendTurn(turnErr.text, turnErr.source, turnErr.utt, turnErr.ctid)}>Retry</Button>
                <Button size="sm" variant="ghost" onClick={() => { setInput(turnErr.text); setTurnErr(null); }}>Edit</Button>
              </span>
            </Callout>
          )}
          {prepErr && <Callout tone="warn">{prepErr}</Callout>}
          <div ref={setTopSlot} />
          {lines.length > 0 && (
            <div className="summary rf-summary">
              <div className="rf-sum">
                <span className="rf-sum-total"><span className="sr-only">Up to </span><Money paise={atCeiling} whole /></span>
                <span className="rf-sum-meta">
                  at most · {lines.length} {lines.length === 1 ? 'item' : 'items'}
                  {budget ? <> · <span className={overBudget ? 'over' : undefined}>budget <Money paise={budget} whole />{overBudget ? ' (over)' : ''}</span></> : null}
                </span>
              </div>
              <Button busy={prepBusy} busyLabel="Preparing…" disabled={!lines.length || inflight > 0} onClick={startReview} title="Nothing is signed or bought until you choose to">Review limits<Icon name="arrow" size={16} /></Button>
            </div>
          )}
          {lines.length > 0 && <p className="as-next"><Icon name="lock" size={12} />Next: set spending limits. Nothing is signed yet.</p>}
          <div className="cfield">
            <label htmlFor="turn-input" className="sr-only">Type a change or a list</label>
            <textarea id="turn-input" ref={taRef} rows={1} value={input} maxLength={2000}
              onChange={(e) => { setInput(e.target.value); const t = e.target; t.style.height = 'auto'; t.style.height = `${Math.min(160, t.scrollHeight)}px`; }}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTyped(); } }}
              placeholder={lines.length ? 'Make oil 8, remove salt…' : '10 atta, 20 oil, budget 8000'} />
            <VoiceControl onFinal={onVoiceFinal} onTypeInstead={() => taRef.current?.focus()} slots={{ top: topSlot, foot: footSlot }} />
            <button type="submit" className="ibtn send" disabled={!input.trim()} aria-label="Send"><Icon name="send" size={18} stroke={1.75} /></button>
          </div>
          <div className="cfoot" ref={setFootSlot} />
        </form>
      )}
    </div>
  );
}

function SessionSkeleton() {
  return (
    <div className="rf-skel" aria-busy="true" aria-label="Loading this restock">
      <div className="stack sm"><div className="skeleton rf-sm" /><div className="skeleton rf-h1" /></div>
      <div className="rf-skel-rows">
        {[78, 64, 70, 52].map((w) => <div key={w} className="rf-skel-row"><div className="skeleton" style={{ width: `${w}%` }} /><div className="skeleton" /></div>)}
      </div>
    </div>
  );
}

function SaveIndicator({ state, onRetry }: { state: SaveState; onRetry: () => void }) {
  if (state === 'idle') return null;
  if (state === 'error') return <span className="save-ind err" role="alert"><Icon name="alert" size={12} />Couldn’t save · <button type="button" className="btn ghost sm" style={{ minHeight: 44, padding: '0 8px', color: 'var(--bad)' }} onClick={onRetry}>Retry</button></span>;
  if (state === 'saved') return <span className="save-ind ok" role="status">Saved</span>;
  return <span className="save-ind" role="status">Saving…</span>;
}

function LowConfidence({ text, onSend, onDrop }: { text: string; onSend: (t: string) => void; onDrop: () => void }) {
  const [t, setT] = useState(text);
  return (
    <div className="callout warn" role="group" aria-label="Check what Sauda heard">
      <Icon name="mic" />
      <div className="stack sm grow">
        <span className="small"><b>Did you say…?</b> Sauda was not sure it heard this right, so nothing changed yet.</span>
        <input className="input" value={t} onChange={(e) => setT(e.target.value)} aria-label="What you said" />
        <div className="row sm"><Button size="sm" onClick={() => onSend(t)} disabled={!t.trim()}>Send</Button><Button size="sm" variant="ghost" onClick={onDrop}>Discard</Button></div>
      </div>
    </div>
  );
}

/** Status of a session that is past drafting, read from the backend (never replays the SSE stream). */
function LockedStatus({ s }: { s: RestockSession }) {
  const [nv, setNv] = useState<NegotiationView | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!s.negotiation_id) return;
    setErr(null);
    getNegotiation(s.negotiation_id).then(setNv).catch(setErr);
  }, [s.negotiation_id, tick]);
  const n = nv?.negotiation;
  const cid = s.confirmation_id || (n?.confirmation_id as string | undefined) || null;
  const mid = s.intent_mandate_id || n?.intent_mandate_id || null;
  const notStarted = !!mid && /^(created|drafted|draft|mandate_signed|signed)$/.test(String(n?.status || ''));
  const lbl = n ? (notStarted ? negotiationLabel('mandate_signed') : negotiationLabel(n.status, n.round)) : null;
  const orders = nv?.orders || [];
  const waiting = s.status === 'awaiting_approval' || n?.status === 'awaiting_confirmation';

  if (s.status === 'cancelled') return <Callout tone="neutral" icon="x" title="Cancelled.">This restock was cancelled. Nothing was ordered. You can copy the list into a new restock.</Callout>;
  return (
    <Card tone={waiting ? 'warn' : s.status === 'failed' ? 'bad' : 'accent'}
      title={waiting ? 'Your approval is needed' : s.status === 'negotiating' ? (notStarted ? 'Limits signed: ready to negotiate' : 'Sauda is negotiating') : s.status === 'failed' ? 'This restock stopped' : 'Ordered'}
      subtitle={s.status === 'ordered' || s.status === 'completed' ? 'Read-only. Payment is on the Orders tab.' : lbl && lbl.label !== 'Needs your approval' ? lbl.label : 'The list is locked while Sauda works on it.'}>
      <div className="stack">
        {s.error?.message && <Callout tone="bad">{s.error.message}</Callout>}
        {s.resumable === false && (s.status === 'negotiating' || s.status === 'awaiting_approval') && <Callout tone="warn">The signed limits expired or were switched off, so Sauda cannot continue buying with them. The list is still here to copy.</Callout>}
        {err ? <span className="small muted">Could not load the live status right now.</span> : null}
        {!n && s.negotiation_id && !err && <Skeleton lines={1} />}
        {waiting && cid && <ButtonLink href={`/confirm/${encodeURIComponent(cid)}`} block>Review and approve</ButtonLink>}
        {s.status === 'negotiating' && mid && notStarted && (
          <ButtonLink href={`/mandate/${encodeURIComponent(mid)}?sid=${encodeURIComponent(s.sid)}`} block>Start negotiating</ButtonLink>
        )}
        {s.status === 'negotiating' && !notStarted && n && (
          <Button variant="secondary" icon="refresh" onClick={() => setTick((x) => x + 1)}>Refresh status</Button>
        )}
        {orders.length > 0 && (
          <div className="list">
            {orders.map((o) => (
              <Link key={o.order_id} href={`/pay/${encodeURIComponent(o.order_id)}`} className="li row between wrap sm" style={{ color: 'inherit', textDecoration: 'none' }}>
                <span className="strong">{o.supplier_name || o.supplier_id}</span>
                <OrderPill o={o} />
              </Link>
            ))}
          </div>
        )}
        <div className="row wrap">
          {mid && <Link className="small muted" href={`/mandate/${encodeURIComponent(mid)}?sid=${encodeURIComponent(s.sid)}`}>Your signed limits</Link>}
          {s.negotiation_id && <Link className="small muted" href={`/trust/${encodeURIComponent(s.negotiation_id)}`}>Signed record</Link>}
        </div>
        <Evidence><span className="mono">session {s.sid} · v{s.version}{s.negotiation_id ? ` · ${s.negotiation_id}` : ''}{mid ? ` · ${mid}` : ''}{cid ? ` · ${cid}` : ''}</span></Evidence>
      </div>
    </Card>
  );
}
