'use client';
// Continuous voice for a restock session. Listen once; every finished sentence is sent as its own turn
// (no transcript confirmation step). Web Speech where available, MediaRecorder + VAD segments otherwise.
// Voice has no authority: signing and approval stay on their own screens.
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { InfoTip } from '../ui-client';
import {
  RecorderListener, WebSpeechListener, recorderSupported, speechCtor,
  type FinalMeta, type ListenState, type Listener, type VoiceErrorKind,
} from '@/lib/voice';
import { langInfo, loadLang, saveLang, type LangCode } from '@/lib/languages';
import { LangSelect } from './LangSelect';
import s from './VoiceCapture.module.css';

export interface VoiceControlProps {
  onFinal: (text: string, meta: FinalMeta) => void;
  disabled?: boolean;
  /** Called when the owner should type instead (unsupported / denied). */
  onTypeInstead?: () => void;
  /** Composer slots: the mic renders inline; live status goes to `top`, language + info to `foot`. */
  slots?: { top: HTMLElement | null; foot: HTMLElement | null };
  /** Controlled language (the parent shows its own menu); otherwise this control shows one and remembers it. */
  lang?: LangCode;
}

type Err = { kind: VoiceErrorKind; message: string; kept?: string };

export function VoiceControl({ onFinal, disabled, onTypeInstead, slots, lang: langProp }: VoiceControlProps) {
  const [ownLang, setLang] = useState<LangCode>('en');
  const lang = langProp ?? ownLang;
  const info = langInfo(lang);
  const [state, setState] = useState<ListenState>('off');
  const [partial, setPartial] = useState('');
  const [err, setErr] = useState<Err | null>(null);
  const [level, setLevel] = useState(0);
  const [busy, setBusy] = useState(0);
  const [engine, setEngine] = useState<'webspeech' | 'recorder' | 'none'>('none');
  const [forceRecorder, setForceRecorder] = useState(false);
  const lis = useRef<Listener | null>(null);
  const finalRef = useRef(onFinal);
  finalRef.current = onFinal;

  useEffect(() => {
    setLang(loadLang());
    setEngine(speechCtor() ? 'webspeech' : recorderSupported() ? 'recorder' : 'none');
  }, []);

  const useEngine = forceRecorder && engine === 'webspeech' ? 'recorder' : engine;

  const stopNow = useCallback(() => { lis.current?.stop(); lis.current = null; }, []);
  // Release the microphone on unmount / route change / tab close.
  useEffect(() => {
    const off = () => stopNow();
    window.addEventListener('pagehide', off);
    return () => { window.removeEventListener('pagehide', off); stopNow(); };
  }, [stopNow]);
  useEffect(() => { if (disabled) stopNow(); }, [disabled, stopNow]);

  const start = useCallback(() => {
    if (disabled) return;
    setErr(null);
    lis.current?.stop();
    const cb = {
      onPartial: setPartial,
      onFinal: (t: string, m: FinalMeta) => finalRef.current(t, m),
      onState: (st: ListenState) => setState(st),
      onError: (kind: VoiceErrorKind, message: string, kept?: string) => { setErr({ kind, message, kept }); if (kind !== 'other' || !lis.current) setState((x) => (x === 'listening' || x === 'starting' ? 'off' : x)); },
      onLevel: setLevel,
      onBusy: setBusy,
    };
    // Web Speech gets the browser locale (Bhojpuri listens as hi-IN); recorder segments carry the lang_hint.
    const l: Listener = useEngine === 'webspeech' ? new WebSpeechListener(info.speech, cb) : new RecorderListener(info.hint, cb);
    lis.current = l;
    void l.start();
  }, [disabled, info.speech, info.hint, useEngine]);

  const pause = () => { lis.current?.pause(); lis.current = null; };
  const on = state === 'listening' || state === 'starting';

  const pickLang = (v: LangCode) => {
    setLang(v);
    saveLang(v);
    if (on) { lis.current?.stop(); lis.current = null; setState('off'); }
  };

  const note = useEngine === 'webspeech'
    ? "Your browser's speech service (Google in Chrome) processes the audio; Sauda gets the text."
    : 'Spoken parts go to Sauda for transcription; audio is not stored.';
  const langNote = info.beta ? ` ${info.english} is in beta: it listens as Hindi, so check the text.` : '';
  const portal = (el: HTMLElement | null | undefined, node: ReactNode) => (el ? createPortal(node, el) : slots ? null : node);

  if (engine === 'none') {
    return portal(slots?.foot, <span className="xs muted">Voice is not available in this browser. Typing works the same way.</span>);
  }

  const bars = [0.5, 0.9, 0.65, 1, 0.7, 0.45, 0.8];
  const top = (
    <div className={s.root} role="group" aria-label="Voice">
      <div className={s.status} role="status" aria-live="polite">
        {state === 'listening' ? 'Listening. Microphone is on.' : state === 'paused' ? 'Paused. Microphone is off.' : state === 'starting' ? 'Starting the microphone…' : ''}
      </div>
      {on && (
        <div className="rf-live">
          {state === 'starting' ? <span className="spinner" aria-hidden style={{ color: 'var(--ink-2)' }} /> : <span className="live-dot" aria-hidden />}
          {state !== 'starting' && <span className="wave" aria-hidden>{bars.map((k, i) => <i key={i} style={{ height: `${Math.max(3, Math.round(16 * Math.min(1, level * 1.6) * k))}px` }} />)}</span>}
          <span className="rf-partial clamp2" aria-live="off" lang={lang} dir={info.rtl ? 'rtl' : undefined}>
            {state === 'starting' ? <span className="muted">Starting the microphone…</span> : partial ? <>“{partial.length > 110 ? `…${partial.slice(-110)}` : partial}”</> : <span className="muted">Listening. Each sentence is added when you finish it.</span>}
          </span>
          <button type="button" className="rf-pause" onClick={pause}>Pause</button>
        </div>
      )}
      {busy > 0 && <span className="rf-proc" role="status"><span className="spinner" aria-hidden />Working out what you said{busy > 1 ? ` (${busy} parts)` : ''}…</span>}
      {err && <VoiceError err={err} canFallback={useEngine === 'webspeech' && recorderSupported()}
        onRetry={start}
        onFallback={() => { setForceRecorder(true); setErr(null); }}
        onSendKept={(t) => { finalRef.current(t, { uttId: '', engine: 'webspeech' }); setErr(null); }}
        onType={onTypeInstead}
        onClose={() => setErr(null)} />}
    </div>
  );
  const micBtn = !on ? (
    <button type="button" className="ibtn" onClick={start} disabled={disabled} aria-label={state === 'paused' ? 'Resume listening' : 'Start listening'} title={state === 'paused' ? 'Resume' : 'Speak'}>
      <MicSvg />
    </button>
  ) : (
    <button type="button" className="ibtn stop" onClick={stopNow} aria-label="Stop listening" title="Stop">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="3" /></svg>
    </button>
  );
  const foot = (
    <span className="row sm" style={{ gap: 2 }}>
      {langProp === undefined && <LangSelect value={lang} onChange={pickLang} />}
      <InfoTip label="About voice" align="left">{note}{langNote} Stops after 2 min of silence.</InfoTip>
    </span>
  );
  if (!slots) return <div className="stack sm">{top}<div className="row sm">{micBtn}{foot}</div></div>;
  return <>{portal(slots.top, top)}{micBtn}{portal(slots.foot, foot)}</>;
}

function VoiceError({ err, canFallback, onRetry, onFallback, onSendKept, onType, onClose }: {
  err: Err; canFallback: boolean; onRetry: () => void; onFallback: () => void; onSendKept: (t: string) => void; onType?: () => void; onClose: () => void;
}) {
  const tone = err.kind === 'idle' ? 'info' : 'warn';
  return (
    <div className={`callout ${tone} ${s.panel}`} role={err.kind === 'idle' ? 'status' : 'alert'}>
      <div className="stack sm grow">
        {err.kind === 'denied' && <>
          <b>Microphone is blocked for this site.</b>
          <span className="small">Chrome or Android: tap the icon left of the address, choose Microphone, then Allow, and tap Listen again. iPhone Safari: tap “aA”, Website Settings, Microphone, Allow.</span>
        </>}
        {err.kind === 'network' && <>
          <b>Could not reach the speech service.</b>
          <span className="small">Check your internet and tap Retry.{err.kept ? ' What we heard so far is kept:' : ''}</span>
          {err.kept && <span className="small">“{err.kept}”</span>}
        </>}
        {err.kind === 'nodevice' && <><b>No microphone found.</b><span className="small">Connect one, or type your list.</span></>}
        {err.kind === 'insecure' && <><b>Voice needs a secure (https) page.</b></>}
        {err.kind === 'unsupported' && <><b>This browser cannot do voice.</b><span className="small">Type your list instead; it works the same way.</span></>}
        {err.kind === 'lang' && <><b>Live speech does not support this language here.</b><span className="small">Use the recorder mode instead, or switch language.</span></>}
        {err.kind === 'idle' && <span className="small">{err.message} Tap Listen to continue.</span>}
        {err.kind === 'other' && <span className="small">{err.message}</span>}
        <div className="row sm wrap">
          {(err.kind === 'network' || err.kind === 'other') && <button type="button" className="btn sm" onClick={onRetry}>Retry</button>}
          {err.kept && <button type="button" className="btn sm secondary" onClick={() => onSendKept(err.kept!)}>Send what we heard</button>}
          {canFallback && (err.kind === 'network' || err.kind === 'lang' || err.kind === 'other') && <button type="button" className="btn sm secondary" onClick={onFallback}>Use recorder mode</button>}
          {onType && (err.kind === 'denied' || err.kind === 'unsupported' || err.kind === 'nodevice') && <button type="button" className="btn sm secondary" onClick={onType}>Type instead</button>}
          <button type="button" className="btn sm ghost" onClick={onClose}>Dismiss</button>
        </div>
      </div>
    </div>
  );
}

function MicSvg() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><path d="M12 18v3" />
    </svg>
  );
}

/** Legacy adapter for ChatStream: each final utterance is handed over as text. */
export function VoiceCapture({ onUseTranscript, disabled }: { onUseTranscript: (t: string) => void; disabled?: boolean }) {
  return <VoiceControl disabled={disabled} onFinal={(t) => onUseTranscript(t)} />;
}

export default VoiceControl;
