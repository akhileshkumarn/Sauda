// Continuous voice for restock sessions (CONTRACT2).
// Primary: the browser's Web Speech API (continuous + interim results), auto-restarted on `end` while listening
// is ON, so there is no overall time limit. Fallback: MediaRecorder + WebAudio VAD; each spoken segment
// (ends after ~900 ms silence, max 25 s) goes to POST /voice/parse. Every final utterance becomes one turn.
// Voice has no authority: "sign"/"approve" only navigate to the review screens.
import { getIdToken } from './auth';
import { mark, newUtt } from './latency';
import { API_BASE, MOCK, SHOP_ID } from './api';

export type VoiceLangHint = 'en-IN' | 'hi-IN' | 'te-IN';

export const VOICE_LANGS: { value: VoiceLangHint; label: string; short: string }[] = [
  { value: 'en-IN', label: 'English', short: 'en' },
  { value: 'hi-IN', label: 'हिन्दी', short: 'hi' },
  { value: 'te-IN', label: 'తెలుగు', short: 'te' },
];

/** Per-segment cap for the recorder fallback (the conversation itself is unlimited). */
export const SEGMENT_MAX_MS = 25_000;
export const SEGMENT_SILENCE_MS = 900;
export const IDLE_STOP_MS = 120_000;
export const VOICE_MAX_BYTES = 3 * 1024 * 1024;

export interface VoiceProduct { gtin: string; name?: string | null; brand?: string | null; pack_size?: string | null }

/** A draft line as the parser returns it. Newer fields (contract item 1) are optional so older backends still work. */
export interface VoicePreviewLine extends VoiceProduct {
  qty: number;
  qty_source?: 'owner' | 'inferred' | null;
  requested_qty?: number | null;
  suggested_qty?: number | null;
  suggestion_reason?: string | null;
  confidence?: 'high' | 'low' | null;
  owner_words?: string | null;
  alternatives?: VoiceProduct[];
  ceiling_paise?: number | null;
  category?: string | null;
  [k: string]: unknown;
}

export interface VoiceClarification { owner_words: string; question: string; options: VoiceProduct[] }

export interface VoicePreview {
  lines: VoicePreviewLine[];
  unmatched: string[];
  stated_budget_paise: number | null;
  suggested_budget_paise?: number | null;
  clarifications: VoiceClarification[];
  festival?: string | null;
}

export interface VoiceParseResult {
  transcript: string;
  language: 'en' | 'hi' | 'te' | 'other' | string;
  languages?: string[];
  preview: VoicePreview | null;
  notes: string[];
}

export class VoiceApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

/** Upload one recording. Throws VoiceApiError with a message that is safe to show the owner. */
export async function parseVoice(audio: Blob, langHint: VoiceLangHint, signal?: AbortSignal): Promise<VoiceParseResult> {
  if (audio.size === 0) throw new VoiceApiError(400, 'AUDIO_EMPTY', 'Nothing was recorded. Try again.');
  if (audio.size > VOICE_MAX_BYTES) throw new VoiceApiError(413, 'AUDIO_TOO_LARGE', 'That segment was too large to send. Pause briefly between items.');
  if (MOCK) return mockParse(langHint, signal);

  const type = (audio.type || 'application/octet-stream').split(';')[0];
  const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') || type.includes('m4a') || type.includes('aac') ? 'm4a' : type.includes('wav') ? 'wav' : 'webm';
  const form = new FormData();
  form.append('audio', audio, `recording.${ext}`);
  form.append('lang_hint', langHint);
  form.append('shop_id', SHOP_ID);

  const headers: Record<string, string> = { Accept: 'application/json' };
  const t = await getIdToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/voice/parse`, { method: 'POST', body: form, headers, signal, cache: 'no-store' });
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e;
    throw new VoiceApiError(0, 'NETWORK', 'Could not reach Sauda. Check your connection and try again.');
  }
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    let message = res.status === 401 ? 'Please sign in again.' : 'Could not process the recording. Please try again.';
    try {
      const j = await res.json();
      code = j.code || j.detail?.code || code;
      message = j.message || j.detail?.message || (typeof j.detail === 'string' ? j.detail : '') || message;
    } catch { /* not JSON */ }
    throw new VoiceApiError(res.status, code, message);
  }
  const j = (await res.json()) as VoiceParseResult;
  return { ...j, notes: Array.isArray(j.notes) ? j.notes : [], preview: j.preview ? normalisePreview(j.preview) : null };
}

function normalisePreview(p: Partial<VoicePreview>): VoicePreview {
  return {
    ...p,
    lines: Array.isArray(p.lines) ? p.lines : [],
    unmatched: Array.isArray(p.unmatched) ? p.unmatched : [],
    clarifications: Array.isArray(p.clarifications) ? p.clarifications : [],
    stated_budget_paise: typeof p.stated_budget_paise === 'number' ? p.stated_budget_paise : null,
  };
}

/** Pick a recording format the browser supports that the backend accepts. Safari records MP4/AAC. */
export function pickRecorderMime(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  const prefs = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4;codecs=mp4a.40.2', 'audio/mp4'];
  return prefs.find((m) => { try { return MediaRecorder.isTypeSupported(m); } catch { return false; } });
}

async function mockParse(lang: VoiceLangHint, signal?: AbortSignal): Promise<VoiceParseResult> {
  await new Promise((r, rej) => {
    const id = setTimeout(r, 900);
    signal?.addEventListener('abort', () => { clearTimeout(id); rej(new DOMException('aborted', 'AbortError')); });
  });
  const transcript = lang === 'hi-IN'
    ? 'कल का स्टॉक तैयार करो। Aashirvaad आटा 1 kg के 10 packet, Maggi noodles के 24 packet। कुल खर्च 8,000 rupees से कम रखना।'
    : lang === 'te-IN'
      ? 'రేపటి స్టాక్ సిద్ధం చేయి. Aashirvaad ఆటా 1 kg 10 ప్యాకెట్లు, Maggi నూడుల్స్ 24 ప్యాకెట్లు. మొత్తం 8,000 rupees లోపు ఉంచు.'
      : "Prepare tomorrow's restock. 10 packets of 1 kg Aashirvaad Atta, 20 packets of iodised salt and 24 packets of Maggi noodles. Keep the total under 8,000 rupees.";
  return {
    transcript, language: lang.slice(0, 2), languages: [lang.slice(0, 2)],
    preview: {
      lines: [
        { gtin: '8901725181222', name: 'Aashirvaad Superior MP Atta', brand: 'Aashirvaad', pack_size: '1 kg', qty: 10, qty_source: 'owner', confidence: 'high', owner_words: '10 packets of 1 kg Aashirvaad Atta' },
        { gtin: '8901058000000', name: 'Masala Noodles', brand: 'Maggi', pack_size: '70 g', qty: 24, qty_source: 'owner', confidence: 'low', owner_words: '24 packets of Maggi noodles' },
      ],
      unmatched: [], stated_budget_paise: 800000,
      clarifications: [{ owner_words: 'Maggi noodles', question: 'Which Maggi pack?', options: [{ gtin: '8901058000000', name: 'Masala Noodles', brand: 'Maggi', pack_size: '70 g' }, { gtin: '8901058000001', name: 'Masala Noodles', brand: 'Maggi', pack_size: '280 g' }] }],
    },
    notes: ['Mock voice result.', 'Preview only. Nothing is ordered until you sign a mandate and approve the final cart.'],
  };
}


// ======================================================================= continuous listening
export type VoiceErrorKind = 'denied' | 'network' | 'nodevice' | 'unsupported' | 'insecure' | 'idle' | 'lang' | 'other';
export type ListenState = 'off' | 'starting' | 'listening' | 'paused';
export interface FinalMeta { uttId: string; confidence?: number; engine: 'webspeech' | 'recorder' }
export interface ListenCallbacks {
  onPartial: (text: string) => void;
  onFinal: (text: string, meta: FinalMeta) => void;
  onState: (s: ListenState) => void;
  onError: (kind: VoiceErrorKind, message: string, keptText?: string) => void;
  onLevel?: (lv: number) => void;
  onBusy?: (n: number) => void; // recorder fallback: segments waiting for transcription
}
export interface Listener { start(): void | Promise<void>; pause(): void; stop(): void; readonly engine: 'webspeech' | 'recorder' }

// Only one recogniser/microphone at a time across the app.
let active: Listener | null = null;
function claim(l: Listener) { if (active && active !== l) active.stop(); active = l; }
function release(l: Listener) { if (active === l) active = null; }
export function stopAllListening() { active?.stop(); active = null; }

/* eslint-disable @typescript-eslint/no-explicit-any */
type SR = any;
export function speechCtor(): (new () => SR) | null {
  if (typeof window === 'undefined') return null;
  const w = window as any;
  if (new URLSearchParams(window.location.search).get('voice') === 'recorder') return null; // force fallback (testing)
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}
export function recorderSupported(): boolean {
  return typeof window !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';
}

export class WebSpeechListener implements Listener {
  readonly engine = 'webspeech' as const;
  private r: SR | null = null;
  private want = false;
  private gen = 0;
  private seen = new Set<string>();
  private lastFinal = ''; private lastFinalAt = 0;
  private interim = '';
  private utt: string | null = null;
  private partialMarked = false;
  private lastSpeech = 0;
  private idle: ReturnType<typeof setInterval> | null = null;
  private restartTimer: ReturnType<typeof setTimeout> | null = null;
  private fastEnds = 0; private startedAt = 0;
  constructor(private lang: string, private cb: ListenCallbacks) {}

  private ensureUtt() { if (!this.utt) { this.utt = newUtt('voice', 'webspeech'); this.partialMarked = false; } return this.utt; }

  start() {
    const Ctor = speechCtor();
    if (!Ctor) { this.cb.onError('unsupported', 'Live speech is not available in this browser.'); return; }
    claim(this);
    this.want = true;
    this.lastSpeech = Date.now();
    this.cb.onState('starting');
    if (!this.idle) this.idle = setInterval(() => {
      if (this.want && Date.now() - this.lastSpeech > IDLE_STOP_MS) { this.stop(); this.cb.onError('idle', 'Stopped listening after 2 minutes without speech.'); }
    }, 1000);
    this.spawn(Ctor);
  }

  private spawn(Ctor: new () => SR) {
    const r = new Ctor();
    this.r = r; const gen = ++this.gen;
    r.lang = this.lang; r.continuous = true; r.interimResults = true; r.maxAlternatives = 1;
    r.onstart = () => { this.startedAt = Date.now(); this.cb.onState('listening'); };
    r.onspeechstart = () => { mark(this.ensureUtt(), 'speech_start'); this.lastSpeech = Date.now(); };
    r.onspeechend = () => { if (this.utt) mark(this.utt, 'utterance_end'); };
    r.onresult = (e: any) => {
      if (gen !== this.gen) return;
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        const txt = String(res[0]?.transcript || '').trim();
        if (res.isFinal) {
          const key = `${gen}:${i}`;
          if (this.seen.has(key) || !txt) continue;
          this.seen.add(key);
          this.emitFinal(txt, typeof res[0].confidence === 'number' ? res[0].confidence : undefined);
        } else interim += `${txt} `;
      }
      this.interim = interim.trim();
      if (this.interim) {
        const u = this.ensureUtt();
        if (!this.partialMarked) { mark(u, 'speech_start'); mark(u, 'first_partial'); this.partialMarked = true; }
      }
      this.cb.onPartial(this.interim);
      this.lastSpeech = Date.now();
    };
    r.onerror = (e: any) => {
      const err = String(e?.error || '');
      if (err === 'no-speech' || err === 'aborted') return; // onend restarts
      if (err === 'not-allowed' || err === 'service-not-allowed') { this.halt(); this.cb.onError('denied', 'Microphone permission was denied.'); return; }
      if (err === 'audio-capture') { this.halt(); this.cb.onError('nodevice', 'No microphone was found.'); return; }
      if (err === 'language-not-supported') { this.halt(); this.cb.onError('lang', 'This language is not available for live speech here.'); return; }
      if (err === 'network') { const kept = this.interim; this.halt(); this.cb.onError('network', 'Could not reach the browser speech service.', kept); return; }
      this.halt(); this.cb.onError('other', `Speech stopped (${err || 'unknown'}).`, this.interim);
    };
    r.onend = () => {
      if (gen !== this.gen) return;
      // Chrome ends a session on long silence or after ~60 s; flush any unfinished words, then restart.
      if (this.interim) { const t = this.interim; this.interim = ''; this.emitFinal(t, undefined); }
      this.cb.onPartial('');
      if (!this.want) return;
      const quick = Date.now() - this.startedAt < 1000;
      this.fastEnds = quick ? this.fastEnds + 1 : 0;
      if (this.fastEnds > 5) { this.halt(); this.cb.onError('other', 'The speech service keeps stopping. Type instead, or try again.'); return; }
      this.restartTimer = setTimeout(() => { if (this.want) { try { this.spawn(Ctor); } catch { this.halt(); this.cb.onError('other', 'Could not restart listening.'); } } }, quick ? 300 : 50);
    };
    try { r.start(); } catch { /* already started */ }
  }

  private emitFinal(txt: string, confidence?: number) {
    const norm = txt.toLowerCase().replace(/\s+/g, ' ');
    if (norm === this.lastFinal && Date.now() - this.lastFinalAt < 5000) { this.utt = null; return; } // duplicate final
    this.lastFinal = norm; this.lastFinalAt = Date.now();
    const u = this.ensureUtt();
    mark(u, 'speech_start'); mark(u, 'utterance_end'); mark(u, 'final_transcript');
    this.utt = null; this.partialMarked = false;
    this.cb.onFinal(txt, { uttId: u, confidence, engine: 'webspeech' });
  }

  private halt() {
    this.want = false;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    if (this.idle) clearInterval(this.idle);
    this.idle = null; this.restartTimer = null;
    const r = this.r; this.r = null; this.gen++;
    try { r?.abort(); } catch { /* ignore */ }
    release(this);
  }
  pause() { this.halt(); this.cb.onPartial(''); this.cb.onState('paused'); }
  stop() { this.halt(); this.cb.onPartial(''); this.cb.onState('off'); }
}

/** Fallback: MediaRecorder + simple energy VAD; one upload per spoken segment. */
export class RecorderListener implements Listener {
  readonly engine = 'recorder' as const;
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private rec: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private tick: ReturnType<typeof setInterval> | null = null;
  private want = false;
  private segStart = 0; private hadSpeech = false; private lastVoice = 0; private lastSpeechAny = 0;
  private floor = 0.02;
  private utt: string | null = null;
  private chain: Promise<void> = Promise.resolve();
  private pending = 0;
  private mime: string | undefined;
  constructor(private lang: VoiceLangHint, private cb: ListenCallbacks) {}

  async start() {
    if (typeof window !== 'undefined' && !window.isSecureContext) { this.cb.onError('insecure', 'Voice needs a secure (https) page.'); return; }
    if (!recorderSupported()) { this.cb.onError('unsupported', 'This browser cannot record audio.'); return; }
    claim(this);
    this.want = true;
    this.cb.onState('starting');
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      this.want = false; release(this);
      const n = (e as DOMException)?.name;
      if (n === 'NotAllowedError' || n === 'SecurityError') this.cb.onError('denied', 'Microphone permission was denied.');
      else if (n === 'NotFoundError' || n === 'OverconstrainedError') this.cb.onError('nodevice', 'No microphone was found.');
      else this.cb.onError('other', 'Could not start the microphone. Close other apps using it and try again.');
      this.cb.onState('off');
      return;
    }
    if (!this.want) { this.cleanup(); return; } // stopped while the permission prompt was open
    this.mime = pickRecorderMime();
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AC(); this.ctx = ctx;
    const an = ctx.createAnalyser(); an.fftSize = 1024;
    ctx.createMediaStreamSource(this.stream).connect(an);
    if (ctx.state !== 'running') ctx.resume().catch(() => {});
    const buf = new Uint8Array(an.fftSize);
    this.lastSpeechAny = Date.now();
    this.startSeg();
    this.cb.onState('listening');
    this.tick = setInterval(() => {
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
      const lv = Math.min(1, Math.sqrt(sum / buf.length) * 4);
      this.cb.onLevel?.(lv);
      const now = Date.now();
      const thr = Math.max(0.06, this.floor * 3);
      const speaking = lv > thr;
      if (!speaking) this.floor = this.floor * 0.97 + lv * 0.03;
      if (speaking) {
        this.lastVoice = now; this.lastSpeechAny = now;
        if (!this.hadSpeech) { this.hadSpeech = true; this.utt = newUtt('voice', 'recorder'); mark(this.utt, 'speech_start'); this.cb.onPartial('Listening…'); }
      }
      if (this.hadSpeech && (now - this.lastVoice > SEGMENT_SILENCE_MS || now - this.segStart > SEGMENT_MAX_MS)) this.endSeg(true);
      else if (!this.hadSpeech && now - this.segStart > 8000) this.endSeg(false); // drop silent audio, keep the buffer small
      if (now - this.lastSpeechAny > IDLE_STOP_MS) { this.stop(); this.cb.onError('idle', 'Stopped listening after 2 minutes without speech.'); }
    }, 50);
  }

  private startSeg() {
    if (!this.stream || !this.want) return;
    const rec = this.mime ? new MediaRecorder(this.stream, { mimeType: this.mime, audioBitsPerSecond: 32000 }) : new MediaRecorder(this.stream);
    const chunks: Blob[] = []; // per-recorder buffer: the old recorder's last chunk must not leak into the next segment
    this.rec = rec; this.chunks = chunks; this.segStart = Date.now(); this.hadSpeech = false;
    rec.ondataavailable = (ev) => { if (ev.data?.size) chunks.push(ev.data); };
    rec.start(250);
  }

  private endSeg(keep: boolean) {
    const rec = this.rec; if (!rec) return;
    this.rec = null;
    const utt = this.utt; this.utt = null;
    if (keep && utt) mark(utt, 'utterance_end');
    const chunks = this.chunks;
    rec.onstop = () => {
      if (keep && utt) {
        const blob = new Blob(chunks, { type: rec.mimeType || this.mime || 'audio/webm' });
        this.enqueue(blob, utt);
      }
    };
    try { rec.stop(); } catch { /* ignore */ }
    if (this.want) this.startSeg();
  }

  private enqueue(blob: Blob, utt: string) {
    this.pending++; this.cb.onBusy?.(this.pending);
    this.chain = this.chain.then(async () => {
      try {
        const r = await parseVoice(blob, this.lang);
        mark(utt, 'final_transcript');
        const t = (r.transcript || '').trim();
        if (t) this.cb.onFinal(t, { uttId: utt, engine: 'recorder' });
      } catch (e) {
        const err = e as VoiceApiError;
        if (err?.code === 'AUDIO_EMPTY') return;
        this.cb.onError(err?.status === 0 ? 'network' : 'other', err?.message || 'Could not transcribe that part.');
      } finally {
        this.pending--; this.cb.onBusy?.(this.pending); this.cb.onPartial('');
      }
    });
  }

  private cleanup() {
    if (this.tick) clearInterval(this.tick);
    this.tick = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.cb.onLevel?.(0);
    release(this);
  }
  private halt(flush: boolean) {
    this.want = false;
    if (this.rec) { if (flush && this.hadSpeech) this.endSeg(true); else { try { this.rec.stop(); } catch { /* ignore */ } this.rec = null; } }
    this.cleanup();
  }
  /** Pause/stop send what was already said, then release the microphone. */
  pause() { this.halt(true); this.cb.onState('paused'); }
  stop() { this.halt(true); this.cb.onState('off'); }
}
/* eslint-enable @typescript-eslint/no-explicit-any */
