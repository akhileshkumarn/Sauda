'use client';
// Conversational onboarding: Sauda asks one short question at a time; voice or typing answers it; the profile card
// fills as answers arrive. Nothing is created until the owner reviews the summary and taps "Create my profile".
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api';
import { errorDetail, rememberBid } from '@/lib/network';
import {
  CONSTITUTION_LABEL, carryToForm, confirmOnboarding, editField, sendTurn, startOnboarding,
  type OnbCandidate, type OnbLang, type OnbSession,
} from '@/lib/onboardingVoice';
import type { TnRole } from '@/lib/types';
import { Button, Callout, Icon } from '../ui';
import { VoiceControl } from '../voice';
import { LangSelect } from '../voice/LangSelect';
import { langInfo, loadLang, saveLang } from '@/lib/languages';


type FieldKey = 'display_name' | 'constitution' | 'gstin' | 'address_line' | 'city' | 'pin' | 'rep_name' | 'rep_role' | 'products' | 'fssai' | 'service_area' | 'brand_claims';

function newId() {
  try { return crypto.randomUUID().slice(0, 18); } catch { return `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`; }
}

export function VoiceOnboard() {
  const sp = useSearchParams();
  const router = useRouter();
  const role: TnRole = sp.get('role') === 'seller' ? 'seller' : 'buyer';
  const [lang, setLang] = useState<OnbLang>('en');
  const [s, setS] = useState<OnbSession | null>(null);
  const [question, setQuestion] = useState('');
  const [startErr, setStartErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [turnErr, setTurnErr] = useState<{ text: string; id: string; source: 'voice' | 'text'; message: string } | null>(null);
  const [typed, setTyped] = useState('');
  const [speak, setSpeak] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [consent, setConsent] = useState({ registry: false, address: false, store: false });
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);
  const [dups, setDups] = useState<OnbCandidate[] | null>(null);
  const [lastLatency, setLastLatency] = useState<number | null>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const sRef = useRef<OnbSession | null>(null);
  sRef.current = s;
  const inputRef = useRef<HTMLInputElement>(null);
  const logEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLang(loadLang());
  }, []);

  const begin = useCallback(async (lg: OnbLang) => {
    setStartErr(null);
    try {
      const r = await startOnboarding(role, lg);
      setS(r.session); setQuestion(headline(r.session, r.reply));
    } catch (e) { setStartErr(e); }
  }, [role]);
  useEffect(() => { void begin(lang); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [role]);

  useEffect(() => { logEnd.current?.scrollIntoView({ block: 'nearest' }); }, [s?.turns.length]);
  useEffect(() => {
    const c = s?.draft.consents;
    if (c) setConsent({ registry: !!c.registry, address: !!c.address, store: true });
  }, [s?.draft.consents]);

  const say = useCallback((text: string) => {
    if (!speak || typeof window === 'undefined' || !('speechSynthesis' in window)) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = lang === 'bho' ? 'hi-IN' : langInfo(lang).speech;
      u.rate = 1;
      u.onstart = () => setSpeaking(true);
      u.onend = () => setSpeaking(false);
      u.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(u);
    } catch { setSpeaking(false); }
  }, [speak, lang]);

  const submit = useCallback((text: string, source: 'voice' | 'text', id = newId()) => {
    const t = text.trim();
    if (!t) return;
    queue.current = queue.current.then(async () => {
      const cur = sRef.current;
      if (!cur || cur.status === 'created') return;
      setBusy(true); setTurnErr(null);
      setS((x) => (x ? { ...x, turns: [...x.turns, { role: 'owner', text: t, source }] } : x));
      try {
        const r = await sendTurn(cur.oid, { client_turn_id: id, text: t, source, lang });
        setS(r.session); setQuestion(headline(r.session, r.reply)); setLastLatency(r.latency_ms?.total ?? null);
        say(r.reply);
      } catch (e) {
        setS((x) => (x ? { ...x, turns: x.turns.slice(0, -1) } : x));
        const msg = e instanceof ApiError && e.status === 404 ? 'This setup was not found. Start again.' : e instanceof Error ? e.message : 'That did not go through.';
        setTurnErr({ text: t, id, source, message: msg });
      } finally { setBusy(false); }
    });
  }, [lang, say]);

  const onFinal = useCallback((text: string) => { if (!speaking) submit(text, 'voice'); }, [submit, speaking]);

  function pickLang(v: OnbLang) {
    setLang(v);
    saveLang(v);
    // Nothing answered yet: restart so the opening question is in the new language. Later answers carry `lang`.
    if (!busy && !(sRef.current?.turns || []).some((t) => t.role === 'owner')) void begin(v);
  }

  function toForm() {
    if (s) carryToForm(s);
    router.push(`/network/onboard?role=${role}`);
  }

  async function saveField(k: FieldKey, value: string) {
    if (!s) return 'Not ready';
    try {
      const updates: Record<string, unknown> = { [k]: k === 'products' || k === 'brand_claims' ? value.split(',').map((x) => x.trim()).filter(Boolean) : value };
      const r = await editField(s.oid, s.version, updates);
      setS(r.session); setQuestion(headline(r.session, r.session.question));
      return null;
    } catch (e) { return e instanceof Error ? e.message : 'Could not save that.'; }
  }

  async function create(confirmNotDuplicate = false) {
    if (!s) return;
    setCreating(true); setCreateErr(null);
    try {
      const r = await confirmOnboarding(s.oid, s.version, consent, confirmNotDuplicate);
      rememberBid(r.bid);
      router.push(`/network/business/${encodeURIComponent(r.bid)}?new=1`);
    } catch (e) {
      const x = errorDetail(e);
      const body = (e instanceof ApiError ? e.body : null) as { session?: OnbSession } | null;
      if (body?.session) setS(body.session);
      if (e instanceof ApiError && x.code === 'possible_duplicate') setDups((x.candidates as OnbCandidate[]) || []);
      else if (e instanceof ApiError && x.code === 'gstin_already_registered') setCreateErr('This GSTIN is already registered on Sauda. Ask the owner of that business to add you as a member.');
      else setCreateErr(e instanceof Error ? e.message : 'That did not finish.');
      setCreating(false);
    }
  }

  if (startErr) {
    return (
      <div className="narrow vo">
        <style>{CSS}</style>
        <BackLink />
        <Callout tone="bad" title="Could not start the conversation.">{startErr instanceof Error ? startErr.message : String(startErr)}</Callout>
        <div className="row sm wrap" style={{ marginTop: 12 }}>
          <Button onClick={() => begin(lang)}>Try again</Button>
          <Link className="btn secondary" href={`/network/onboard?role=${role}`}>Use the form instead</Link>
        </div>
      </div>
    );
  }

  const confirming = s?.status === 'confirming';
  return (
    <div className="vo">
      <style>{CSS}</style>
      <BackLink />
      <div className="vo-grid">
        <section className="vo-main" aria-labelledby="vo-q">
          <div className="vo-top row between wrap">
            <span className="small muted">{role === 'seller' ? 'Set up your supplier profile by voice' : 'Set up your shop by voice'}</span>
            <div className="row sm">
              <LangSelect value={lang} onChange={pickLang} label="Language" />
              <label className="vo-speak small"><input type="checkbox" checked={speak} onChange={(e) => { setSpeak(e.target.checked); if (!e.target.checked) try { window.speechSynthesis?.cancel(); } catch { /* ignore */ } }} /> Read questions aloud</label>
            </div>
          </div>

          <h1 id="vo-q" className="vo-q" aria-live="polite" lang={lang} dir={langInfo(lang).rtl ? 'rtl' : undefined}>{s ? question : <span className="muted">Starting…</span>}</h1>
          {lastLatency !== null && <p className="xs muted" aria-hidden>Answered in {(lastLatency / 1000).toFixed(1)} s</p>}

          {!confirming && s?.status !== 'created' && (
            <div className="vo-mic" key={lang}>
              <VoiceControl lang={lang} onFinal={onFinal} disabled={!s || creating} onTypeInstead={() => inputRef.current?.focus()} />
              {speaking && <p className="small muted">Sauda is speaking; the microphone ignores this.</p>}
            </div>
          )}

          <form className="vo-type row sm" onSubmit={(e) => { e.preventDefault(); submit(typed, 'text'); setTyped(''); }}>
            <label className="sr-only" htmlFor="vo-input">Type your answer</label>
            <input id="vo-input" ref={inputRef} className="input grow" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={confirming ? 'Type a correction, e.g. “the PIN is 500016”' : 'Or type your answer'} autoComplete="off" lang={lang} disabled={!s} />
            <Button type="submit" variant="secondary" disabled={!typed.trim() || !s} busy={busy} busyLabel="Sending…">Send</Button>
          </form>

          {turnErr && (
            <div className="callout warn" role="alert"><Icon name="alert" size={16} /><div className="stack sm grow">
              <span className="small"><b>That answer did not go through.</b> {turnErr.message}</span>
              <div className="row sm wrap">
                <button type="button" className="btn sm" onClick={() => submit(turnErr.text, turnErr.source, turnErr.id)}>Retry</button>
                <button type="button" className="btn sm secondary" onClick={toForm}>Switch to the form</button>
                <button type="button" className="btn sm ghost" onClick={() => setTurnErr(null)}>Dismiss</button>
              </div>
            </div></div>
          )}

          <ol className="vo-log" aria-label="Conversation">
            {(s?.turns || []).slice(-12).map((t, i) => (
              <li key={i} className={t.role === 'owner' ? 'me' : 'sa'}>
                <span className="who">{t.role === 'owner' ? 'You' : 'Sauda'}</span>
                <span className="txt">{t.text}</span>
              </li>
            ))}
            {busy && <li className="sa"><span className="who">Sauda</span><span className="txt muted"><span className="spinner" aria-hidden /> Thinking…</span></li>}
            <div ref={logEnd} />
          </ol>

          {confirming && s && (
            <section className="panel accent vo-confirm" aria-labelledby="vo-confirm-h">
              <h2 id="vo-confirm-h" className="h-section">Check and create</h2>
              <p className="small muted">Nothing has been created yet. Tap any detail on the card to fix it.</p>
              <fieldset className="stack sm vo-fs">
                <legend className="small strong">Checks Sauda will run</legend>
                {(s.draft.gstin || s.draft.fssai || s.draft.udyam) && (
                  <label className="check-row"><input type="checkbox" checked={consent.registry} onChange={(e) => setConsent((c) => ({ ...c, registry: e.target.checked }))} /><span>Compare the registration numbers I gave with official or authorised records, where Sauda has access.</span></label>
                )}
                <label className="check-row"><input type="checkbox" checked={consent.address} onChange={(e) => setConsent((c) => ({ ...c, address: e.target.checked }))} /><span>Check that the address and PIN code exist and match each other.</span></label>
                <label className="check-row"><input type="checkbox" checked={consent.store} onChange={(e) => setConsent((c) => ({ ...c, store: e.target.checked }))} /><span>Keep the results privately and share only a summary with businesses I invite or accept.</span></label>
              </fieldset>
              {dups && (
                <div className="callout warn" role="alert"><Icon name="alert" size={16} /><div>
                  <b>This looks like an existing business.</b>
                  <p className="small" style={{ marginTop: 4 }}>{dups.length ? dups.map((c) => [c.display_name, c.city, c.gstin_masked].filter(Boolean).join(', ')).join('; ') : 'A business with the same name and PIN'} is already on Sauda. If it is yours, ask its owner to add you. If it is a different business, continue.</p>
                  <div style={{ marginTop: 8 }}><Button type="button" size="sm" variant="secondary" busy={creating} busyLabel="Creating…" onClick={() => create(true)}>It is a different business, continue</Button></div>
                </div></div>
              )}
              {createErr && <Callout tone="bad" title="That did not finish.">{createErr} Your answers are kept; try again.</Callout>}
              <Button block busy={creating} busyLabel="Creating your profile…" disabled={!consent.store} onClick={() => create(false)}>Create my profile</Button>
              {!consent.store && <p className="xs muted">Tick the last box to continue. The other checks are optional.</p>}
            </section>
          )}

          <p className="small muted vo-foot">
            Sauda never asks for Aadhaar, OTPs or passwords. <button type="button" className="linklike" onClick={toForm}>Switch to the form</button> any time; your answers come with you.
          </p>
        </section>

        <aside className="vo-card" aria-label="Your profile so far">
          {s ? <ProfileCard s={s} onSave={saveField} /> : <div className="skel" style={{ height: 240 }} />}
        </aside>
      </div>
    </div>
  );
}

const CONFIRM_HEAD: Partial<Record<OnbLang, string>> = {
  en: 'Here is your profile. Shall I create it?', hi: 'यह आपकी प्रोफ़ाइल है। क्या मैं इसे बना दूँ?', te: 'ఇది మీ ప్రొఫైల్. సృష్టించమంటారా?',
  ta: 'உங்க ப்ரொஃபைல்-ஐ கிரியேட் பண்ணட்டுமா?', kn: 'ನಿಮ್ಮ ಪ್ರೊಫೈಲ್ ಕ್ರಿಯೇಟ್ ಮಾಡಲಾ?', ml: 'നിങ്ങളുടെ പ്രൊഫൈൽ ഉണ്ടാക്കട്ടെ?',
  mr: 'मी तुमची प्रोफाइल तयार करू का?', bn: 'আমি কি আপনার প্রোফাইল তৈরি করব?', gu: 'તો હું તમારી પ્રોફાઇલ બનાવી દઉં?',
  pa: 'ਕੀ ਮੈਂ ਤੁਹਾਡਾ ਪ੍ਰੋਫਾਈਲ ਬਣਾ ਦੇਵਾਂ?', or: 'ମୁଁ ଆପଣଙ୍କ ପ୍ରୋଫାଇଲ୍ ତିଆରି କରିବି କି?', ur: 'کیا میں آپ کی پروفائل بنا دوں؟', bho: 'का हम रउआ प्रोफाइल बना दीं?',
};
/** The large heading shows only Sauda's current question; the full reply stays in the conversation log. */
function headline(s: OnbSession, reply: string) {
  if (s.status === 'confirming') return CONFIRM_HEAD[s.lang] || CONFIRM_HEAD.en || '';
  return s.question || reply;
}

function BackLink() {
  return <Link href="/network" className="small muted row sm tn-back" style={{ minHeight: 32 }}><Icon name="chev" size={14} /><span>Network</span></Link>;
}

function ProfileCard({ s, onSave }: { s: OnbSession; onSave: (k: FieldKey, v: string) => Promise<string | null> }) {
  const d = s.draft;
  const rows: { k: FieldKey; label: string; value: string; raw: string; check?: string; show?: boolean }[] = [
    { k: 'display_name', label: 'Business name', value: d.display_name, raw: d.display_name },
    { k: 'constitution', label: 'Business type', value: d.constitution ? CONSTITUTION_LABEL[d.constitution] || d.constitution : '', raw: d.constitution || '' },
    { k: 'gstin', label: 'GSTIN', value: d.gstin ? `${d.gstin.slice(0, 2)}…${d.gstin.slice(-3)}` : d.gst_registered === false ? 'Not registered' : '', raw: d.gstin || '', check: s.checks.gstin },
    { k: 'address_line', label: 'Street or area', value: d.address.line, raw: d.address.line },
    { k: 'city', label: 'City', value: d.address.city, raw: d.address.city },
    { k: 'pin', label: 'PIN', value: d.address.pin ? `${d.address.pin}${d.address.state ? ` · ${d.address.state}` : ''}` : '', raw: d.address.pin, check: s.checks.pin },
    { k: 'rep_name', label: 'You', value: d.representative.name, raw: d.representative.name },
    { k: 'rep_role', label: 'Your role', value: d.representative.role, raw: d.representative.role },
    { k: 'products', label: s.role === 'seller' ? 'You supply' : 'You buy', value: d.products.join(', '), raw: d.products.join(', ') },
    { k: 'service_area', label: 'Delivers to', value: d.service_area || '', raw: d.service_area || '', show: s.role === 'seller' },
    { k: 'brand_claims', label: 'Brands claimed', value: d.brand_claims.join(', '), raw: d.brand_claims.join(', '), show: s.role === 'seller' },
    { k: 'fssai', label: 'FSSAI', value: d.fssai ? `${d.fssai.slice(0, 2)}…${d.fssai.slice(-3)}` : '', raw: d.fssai || '', check: s.checks.fssai },
  ];
  const filled = rows.filter((r) => r.show !== false && r.value).length;
  const total = rows.filter((r) => r.show !== false).length;
  return (
    <div className="vo-pc">
      <div className="row between">
        <h2 className="h-section">Your profile</h2>
        <span className="xs muted">{filled} of {total}</span>
      </div>
      <p className="xs muted">Fills in as you answer. Tap a detail to fix it.</p>
      <ul className="vo-fields">
        {rows.filter((r) => r.show !== false).map((r) => <FieldRow key={r.k} {...r} onSave={onSave} active={s.asked === r.k} />)}
      </ul>
      {(d.phone || d.email) && <p className="xs muted">Contact: {[d.phone, d.email].filter(Boolean).join(' · ')} (masked)</p>}
    </div>
  );
}

function FieldRow({ k, label, value, raw, check, active, onSave }: { k: FieldKey; label: string; value: string; raw: string; check?: string; active: boolean; onSave: (k: FieldKey, v: string) => Promise<string | null> }) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(raw);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [flash, setFlash] = useState(false);
  const prev = useRef(value);
  useEffect(() => { if (value && value !== prev.current) { setFlash(true); const t = setTimeout(() => setFlash(false), 1200); prev.current = value; return () => clearTimeout(t); } prev.current = value; }, [value]);
  if (editing) {
    return (
      <li className="vo-f editing">
        <form className="stack xs" onSubmit={async (e) => { e.preventDefault(); setSaving(true); const er = await onSave(k, v); setSaving(false); if (er) setErr(er); else { setErr(null); setEditing(false); } }}>
          <label className="xs muted" htmlFor={`vo-f-${k}`}>{label}</label>
          {k === 'constitution' ? (
            <select id={`vo-f-${k}`} className="input" value={v} onChange={(e) => setV(e.target.value)}>
              <option value="">Choose…</option>{Object.entries(CONSTITUTION_LABEL).map(([c, l]) => <option key={c} value={c}>{l}</option>)}
            </select>
          ) : <input id={`vo-f-${k}`} className="input" value={v} onChange={(e) => setV(e.target.value)} autoFocus inputMode={k === 'pin' || k === 'fssai' ? 'numeric' : undefined} />}
          {err && <span className="xs" style={{ color: 'var(--bad)' }} role="alert">{err}</span>}
          <div className="row sm"><Button type="submit" size="sm" busy={saving} busyLabel="Saving…">Save</Button><Button type="button" size="sm" variant="ghost" onClick={() => { setEditing(false); setErr(null); setV(raw); }}>Cancel</Button></div>
        </form>
      </li>
    );
  }
  return (
    <li className={`vo-f ${value ? 'has' : ''} ${active ? 'active' : ''} ${flash ? 'flash' : ''}`}>
      <button type="button" className="vo-fbtn" onClick={() => { setV(raw); setEditing(true); }} aria-label={`${label}: ${value || 'not given yet'}. Edit`}>
        <span className="k">{label}</span>
        <span className="v">{value || <span className="muted">{active ? 'Asking now…' : '—'}</span>}</span>
        {check && value && <span className="fmt">Format check only</span>}
      </button>
    </li>
  );
}

const CSS = `
.vo { max-width: var(--wide-w, 1040px); margin: 0 auto; }
.vo-grid { display: grid; gap: var(--s6); grid-template-columns: 1fr; margin-top: var(--s3); }
@media (min-width: 1000px) { .vo-grid { grid-template-columns: minmax(0, 1fr) 340px; align-items: start; } .vo-card { position: sticky; top: var(--s6); } }
.vo-main { display: flex; flex-direction: column; gap: var(--s4); min-width: 0; }
.vo-top { gap: var(--s2); }
.vo-speak { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; color: var(--ink-2); }
.vo-q { font-family: var(--display); font-weight: var(--fw-display, 500); font-size: clamp(24px, 4.2vw, 34px); line-height: 1.22; letter-spacing: -0.01em; color: var(--ink); margin: var(--s2) 0 0; outline: none; }
.vo-mic { display: flex; flex-direction: column; align-items: flex-start; gap: var(--s2); }
.vo-mic .ibtn { width: 76px; height: 76px; background: var(--accent); color: var(--accent-ink, #fff); box-shadow: var(--shadow-1); }
.vo-mic .ibtn:hover:not(:disabled) { background: var(--accent-hover, var(--accent)); color: var(--accent-ink, #fff); }
.vo-mic .ibtn.stop { background: var(--bad); color: #fff; }
.vo-mic .ibtn svg { width: 30px; height: 30px; }
.vo-mic .seg { display: none; }
.vo-type { align-items: stretch; }
.vo-type .input { min-width: 0; }
.vo-log { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--s2); max-height: 340px; overflow-y: auto; border-top: 1px solid var(--line); padding-top: var(--s3); }
.vo-log li { display: grid; grid-template-columns: 56px 1fr; gap: var(--s2); font-size: var(--fs-sm); line-height: 1.45; }
.vo-log .who { color: var(--ink-3); font-size: var(--fs-xs); padding-top: 1px; }
.vo-log li.me .txt { color: var(--ink); }
.vo-log li.sa .txt { color: var(--ink-2); }
.vo-fs { border: 0; padding: 0; margin: 0; min-width: 0; }
.vo-confirm { display: flex; flex-direction: column; gap: var(--s3); }
.vo-foot { border-top: 1px solid var(--line); padding-top: var(--s3); }
.linklike { appearance: none; border: 0; background: none; padding: 0; font: inherit; color: var(--accent); text-decoration: underline; cursor: pointer; min-height: 24px; }
.vo-pc { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-lg); padding: var(--s4); box-shadow: var(--shadow-1); }
.vo-fields { list-style: none; margin: var(--s3) 0 0; padding: 0; }
.vo-f { border-top: 1px solid var(--line); }
.vo-f:first-child { border-top: 0; }
.vo-f.editing { padding: var(--s2) 0; }
.vo-fbtn { appearance: none; border: 0; background: transparent; width: 100%; text-align: left; font: inherit; color: inherit; display: grid; grid-template-columns: 110px 1fr; gap: 2px var(--s2); padding: 10px 6px; min-height: 44px; cursor: pointer; border-radius: var(--r-sm); transition: background-color var(--dur-2) var(--ease); }
.vo-fbtn:hover { background: var(--fill); }
.vo-fbtn:focus-visible { box-shadow: var(--focus); outline: none; }
.vo-fbtn .k { color: var(--ink-3); font-size: var(--fs-xs); padding-top: 2px; }
.vo-fbtn .v { color: var(--ink); font-size: var(--fs-sm); overflow-wrap: anywhere; }
.vo-fbtn .fmt { grid-column: 2; justify-self: start; font-size: 11.5px; color: var(--ink-2); border: 1px solid var(--line-2, var(--line)); border-radius: var(--r-pill); padding: 0 8px; line-height: 18px; }
.vo-f.active .vo-fbtn { box-shadow: inset 3px 0 0 var(--accent); }
.vo-f.flash .vo-fbtn { background: var(--accent-soft); }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
@media (prefers-reduced-motion: reduce) { .vo-fbtn { transition: none; } }
`;
