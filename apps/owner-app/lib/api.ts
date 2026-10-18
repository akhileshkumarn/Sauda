// The ONE typed client for the buyer-agent service. All integration fixes go here.
import { getIdToken } from './auth';
import * as mock from './mock';
import type {
  NegotiationView, PrepareResponse, RestockSession, SessionSummary, TurnResponse,
  AttackResponse, AttackScenario, Confirmation, GateReport, ConfirmResponse, IntentMandateBody, LedgerEvent, Mandate, Metrics,
  Order, Overview, Product, ProofResponse, ScenarioResult, SignMandateResponse, SseEvent, VerifyResponse,
} from './types';

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || '').replace(/\/$/, '');
export const MOCK = process.env.NEXT_PUBLIC_MOCK === '1';
export const SHOP_ID = process.env.NEXT_PUBLIC_DEMO_SHOP_ID || 'demo';

/** Backend `detail` is a dict of rule evidence; render it as one short text line. */
function detailText(d: unknown): string | undefined {
  if (d === null || d === undefined || d === '') return undefined;
  if (typeof d !== 'object') return String(d);
  const parts = Object.entries(d as Record<string, unknown>)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`);
  return parts.length ? parts.join(' · ').slice(0, 240) : undefined;
}

/** Backend gate results use `reason` (with "OK" for a pass); the UI reads `reason_code`. Normalise both. */
export function normalizeGate(r: GateReport | null | undefined): GateReport {
  const g = (r || { action: '', verdict: 'DENY', results: [] }) as GateReport;
  return {
    ...g,
    action: g.action || '',
    verdict: (String(g.verdict || '').toUpperCase() || 'DENY') as GateReport['verdict'],
    results: (g.results || []).map((x) => {
      const code = x.reason_code ?? x.reason ?? null;
      return {
        ...x,
        verdict: String(x.verdict).toUpperCase() as GateReport['verdict'],
        reason_code: code === 'OK' ? null : code,
        detail: detailText(x.detail),
      };
    }),
  };
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public body?: unknown) { super(message); }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function request<T>(method: string, path: string, opts: { body?: unknown; auth?: boolean; signal?: AbortSignal } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.auth) {
    const t = await getIdToken();
    if (t) headers.Authorization = `Bearer ${t}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method, headers, signal: opts.signal, cache: 'no-store',
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let code = `HTTP_${res.status}`; let message = res.statusText; let body: unknown;
    try {
      const j = await res.json(); body = j;
      code = j.code || j.error?.code || code;
      code = j.detail?.code || code;
      const d = j.detail;
      const fromList = Array.isArray(d) ? d.map((x: { msg?: string; loc?: unknown[] }) => [x.loc?.slice(1).join('.'), x.msg].filter(Boolean).join(': ')).join('; ') : null;
      message = j.message || d?.message || (typeof d === 'string' ? d : null) || fromList || j.error?.message || message;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, code, message, body);
  }
  return res.json() as Promise<T>;
}

// ---------- owner routes (Bearer) ----------

/** POST /chat {shop_id, message, preferred_supplier_id?, mandate_id?} -> text/event-stream (SM-5). */
export async function* chat(
  input: { message: string; mandate_id?: string; preferred_supplier_id?: string },
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  if (MOCK) {
    if (mock.mockMode() === 'busy') { await sleep(400); yield { event: 'error', data: { code: 'HTTP_409', message: 'Another owner is negotiating for this shop right now' } }; return; }
    for (const { delay, ev } of mock.mockChatScript(input.message)) {
      await sleep(delay);
      if (signal?.aborted) return;
      yield ev;
    }
    return;
  }
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'text/event-stream' };
  const t = await getIdToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST', headers, signal, cache: 'no-store',
    body: JSON.stringify({ shop_id: SHOP_ID, ...input }),
  });
  if (!res.ok || !res.body) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.message || j.detail?.message || (typeof j.detail === 'string' ? j.detail : '') || msg; } catch { /* ignore */ }
    yield { event: 'error', data: { code: `HTTP_${res.status}`, message: String(msg) } };
    return;
  }
  for await (const ev of parseSse(res.body)) {
    if (ev.event === 'gate.report') yield { event: 'gate.report', data: normalizeGate(ev.data) };
    else yield ev;
  }
}

/** Parses a text/event-stream body. Accepts `event:` + `data:` lines, or bare `data:` JSON carrying {type|event, ...}. */
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  const flush = (block: string): SseEvent | null => {
    let name = ''; const data: string[] = [];
    for (const raw of block.split('\n')) {
      const line = raw.replace(/\r$/, '');
      if (!line || line.startsWith(':')) continue;
      const i = line.indexOf(':');
      const field = i === -1 ? line : line.slice(0, i);
      const value = i === -1 ? '' : line.slice(i + 1).replace(/^ /, '');
      if (field === 'event') name = value;
      else if (field === 'data') data.push(value);
    }
    if (!data.length) return null;
    let parsed: unknown;
    try { parsed = JSON.parse(data.join('\n')); } catch { parsed = { text: data.join('\n') }; }
    const obj = (parsed ?? {}) as Record<string, unknown>;
    if (!name) {
      name = String(obj.event || obj.type || 'agent.text');
      if (obj.data && typeof obj.data === 'object') parsed = obj.data;
    }
    return { event: name, data: parsed } as SseEvent;
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.search(/\r?\n\r?\n/)) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx).replace(/^\r?\n\r?\n/, '');
      const ev = flush(block);
      if (ev) yield ev;
    }
  }
  if (buf.trim()) { const ev = flush(buf); if (ev) yield ev; }
}

/** POST /mandates {kind:'intent', body} -> {mandate_id, body_hash, signature, kms_key_version} */
export async function signMandate(body: IntentMandateBody, negotiation_id?: string): Promise<SignMandateResponse> {
  if (MOCK) { await sleep(600); mock.mockSessionSigned(negotiation_id, mock.MOCK_MANDATE_ID); return { mandate_id: mock.MOCK_MANDATE_ID, body_hash: mock.mockMandate.body_hash, signature: mock.mockMandate.signature, kms_key_version: 1 }; }
  return request('POST', '/mandates', { body: { kind: 'intent', body, ...(negotiation_id ? { negotiation_id } : {}) }, auth: true });
}

/** GET /mandates/{id} -> Mandate */
export async function getMandate(id: string): Promise<Mandate> {
  if (MOCK) return { ...mock.mockMandate, mandate_id: id, status: mockRevoked.has(id) ? 'revoked' : 'active' };
  return request('GET', `/mandates/${encodeURIComponent(id)}`, { auth: true });
}

const mockRevoked = new Set<string>();
/** POST /mandates/{id}/revoke {} -> {status:'revoked'} */
export async function revokeMandate(id: string): Promise<{ status: string }> {
  if (MOCK) { await sleep(400); mockRevoked.add(id); return { status: 'revoked' }; }
  return request('POST', `/mandates/${encodeURIComponent(id)}/revoke`, { body: {}, auth: true });
}

/** GET /confirm/{id} -> Confirmation (cart + gate report; refresh-safe per SM-1) */
export async function getConfirmation(id: string): Promise<Confirmation> {
  if (MOCK) return { ...mock.mockConfirmation, confirmation_id: id };
  const c = await request<Confirmation>('GET', `/confirm/${encodeURIComponent(id)}`, { auth: true });
  return { ...c, gate_report: normalizeGate(c.gate_report) };
}

/** POST /confirm {confirmation_id, approved} -> {status, order_ids?, payment_mandate_id?} */
export async function answerConfirmation(confirmation_id: string, approved: boolean): Promise<ConfirmResponse> {
  if (MOCK) {
    await sleep(700);
    if (mock.mockMode() === 'conflict') throw new ApiError(409, 'cart_changed', 'cart changed since it was shown');
    return approved ? { status: 'ordered', order_ids: [mock.MOCK_ORDER_ID], payment_mandate_id: 'mdt_pay_01' } : { status: 'declined' };
  }
  return request('POST', '/confirm', { body: { confirmation_id, approved }, auth: true });
}

/** GET /orders/{order_id} -> Order with payment_mandate */
export async function getOrder(orderId: string): Promise<Order> {
  if (MOCK) return { ...mock.mockOrder, order_id: orderId };
  return request('GET', `/orders/${encodeURIComponent(orderId)}`, { auth: true });
}

/** POST /payments/{order_id}/proof {utr, amount_paise?} -> {status:'settled'|'mismatch', utr?, reason?} */
export async function submitPaymentProof(orderId: string, proof: { utr: string; amount_paise?: number; payee_vpa?: string }): Promise<ProofResponse> {
  if (MOCK) { await sleep(700); return /^\d{12}$/.test(proof.utr) ? { status: 'claimed', utr: proof.utr } : { status: 'invalid', reason: 'UTR must be 12 digits' }; }
  const r = await request<ProofResponse>('POST', `/payments/${encodeURIComponent(orderId)}/proof`, { body: proof, auth: true });
  return { ...r, status: r.status === 'settled' ? 'claimed' : r.status };
}

// ---------- judge routes (no auth, demo shop only) ----------

/** GET /metrics/{shop_id} */
export async function getMetrics(shopId: string): Promise<Metrics> {
  if (MOCK) return mock.mockMetrics;
  return request('GET', `/metrics/${encodeURIComponent(shopId)}`);
}

/** GET /verify/{negotiation_id} -> {events:[{seq,type,hash_ok,link_ok,sig_ok}], chain_ok} */
export async function verifyChain(negotiationId: string): Promise<VerifyResponse> {
  if (MOCK) return mock.mockVerify();
  return request('GET', `/verify/${encodeURIComponent(negotiationId)}`);
}

/** GET /events?negotiation={id} -> {events: LedgerEvent[]} (a bare array is also accepted) */
export async function getEvents(negotiationId: string): Promise<LedgerEvent[]> {
  if (MOCK) return mock.mockEvents();
  const r = await request<{ events: LedgerEvent[] } | LedgerEvent[]>('GET', `/events?negotiation=${encodeURIComponent(negotiationId)}`);
  return Array.isArray(r) ? r : r.events;
}

/** POST /attack {message} -> {guard_verdict, gate_report, ledger_seq} */
export async function attack(message: string): Promise<AttackResponse> {
  if (MOCK) { await sleep(800); return mock.mockAttack(message); }
  const r = await request<AttackResponse>('POST', '/attack', { body: { message } });
  return { ...r, gate_report: normalizeGate(r.gate_report) };
}

/** GET /shops/{shop}/overview (contract 4) */
export async function getOverview(shopId = SHOP_ID): Promise<Overview> {
  if (MOCK) { await sleep(350); return mock.mockOverview(); }
  return request('GET', `/shops/${encodeURIComponent(shopId)}/overview`, { auth: true });
}

/** POST /shops/{shop}/kill-switch {on} (owner only): while on, every gated action is refused (R12). */
let mockKill = false;
export async function setKillSwitch(on: boolean, shopId = SHOP_ID): Promise<{ kill_switch: boolean }> {
  if (MOCK) { await sleep(500); mockKill = on; return { kill_switch: mockKill }; }
  return request('POST', `/shops/${encodeURIComponent(shopId)}/kill-switch`, { body: { on }, auth: true });
}

/** GET /products?q=&limit= (contract 2) */
export async function searchProducts(q: string, limit = 20, signal?: AbortSignal): Promise<Product[]> {
  if (MOCK) { await sleep(250); return mock.mockSearch(q); }
  const r = await request<{ products: Product[] }>('GET', `/products?q=${encodeURIComponent(q)}&limit=${limit}`, { auth: true, signal });
  return r.products || [];
}

/** GET /attack/scenarios (contract 6, no auth) */
export async function getScenarios(): Promise<AttackScenario[]> {
  if (MOCK) { await sleep(300); return mock.mockScenarios; }
  const r = await request<{ scenarios: AttackScenario[] }>('GET', '/attack/scenarios');
  return r.scenarios || [];
}

/** POST /attack/scenarios/{id} (contract 6, no auth, rate-limited) */
export async function runScenario(id: string): Promise<ScenarioResult> {
  if (MOCK) { await sleep(700); return mock.mockScenarioRun(id); }
  return request('POST', `/attack/scenarios/${encodeURIComponent(id)}`, { body: {} });
}

export const DEFAULT_NEGOTIATION_ID = process.env.NEXT_PUBLIC_DEMO_NEGOTIATION_ID || (MOCK ? mock.MOCK_NEGOTIATION_ID : '');

// ---------- restock sessions (CONTRACT2) ----------

/** Session in a 409 version_conflict / session_locked body (top level or under FastAPI `detail`). */
export function conflictSession(e: unknown): RestockSession | null {
  if (!(e instanceof ApiError)) return null;
  const b = e.body as { session?: RestockSession; detail?: { session?: RestockSession } } | undefined;
  return b?.session || b?.detail?.session || null;
}

export async function createSession(title?: string): Promise<RestockSession> {
  if (MOCK) { await sleep(200); return mock.mockCreateSession(title); }
  return request('POST', '/restock/sessions', { body: title ? { title } : {}, auth: true });
}

export async function listSessions(opts: { status?: string; limit?: number } = {}): Promise<SessionSummary[]> {
  if (MOCK) { await sleep(250); return mock.mockListSessions(); }
  const q = new URLSearchParams();
  if (opts.status) q.set('status', opts.status);
  q.set('limit', String(opts.limit ?? 20));
  const r = await request<{ sessions: SessionSummary[] }>('GET', `/restock/sessions?${q}`, { auth: true });
  return r.sessions || [];
}

export async function getSession(sid: string): Promise<RestockSession> {
  if (MOCK) { await sleep(200); return mock.mockGetSession(sid); }
  return request('GET', `/restock/sessions/${encodeURIComponent(sid)}`, { auth: true });
}

export interface SessionPatch { version: number; title?: string; lines?: { gtin: string; qty: number; [k: string]: unknown }[]; stated_budget_paise?: number | null }
export async function patchSession(sid: string, patch: SessionPatch): Promise<RestockSession> {
  if (MOCK) {
    await sleep(mock.mockMode() === 'slow' ? 1500 : 250);
    const r = mock.mockPatchSession(sid, patch);
    if ('ok' in r) return r.ok;
    if ('conflict' in r) throw new ApiError(409, 'version_conflict', 'Changed elsewhere', { code: 'version_conflict', session: r.conflict });
    throw new ApiError(r.error, r.code, r.message);
  }
  return request('PATCH', `/restock/sessions/${encodeURIComponent(sid)}`, { body: patch, auth: true });
}

export async function postTurn(sid: string, t: { client_turn_id: string; text: string; source: 'voice' | 'text'; lang?: string }): Promise<TurnResponse> {
  if (MOCK) { await sleep(350); return mock.mockTurn(sid, t); }
  return request('POST', `/restock/sessions/${encodeURIComponent(sid)}/turns`, { body: t, auth: true });
}

export async function prepareSession(sid: string): Promise<PrepareResponse> {
  if (MOCK) { await sleep(400); return mock.mockPrepare(sid); }
  return request('POST', `/restock/sessions/${encodeURIComponent(sid)}/prepare`, { body: {}, auth: true });
}

export async function cancelSession(sid: string): Promise<RestockSession> {
  if (MOCK) { await sleep(250); return mock.mockCancel(sid); }
  const r = await request<RestockSession | { session: RestockSession }>('POST', `/restock/sessions/${encodeURIComponent(sid)}/cancel`, { body: {}, auth: true });
  return 'session' in r && r.session ? r.session : (r as RestockSession);
}

export async function getNegotiation(nid: string): Promise<NegotiationView> {
  if (MOCK) { await sleep(200); return mock.mockNegotiationView(nid); }
  return request('GET', `/negotiations/${encodeURIComponent(nid)}`, { auth: true });
}

/** POST /telemetry/voice (optional on the backend): numbers only, never text. Failures are ignored. */
export async function postVoiceTelemetry(sid: string, marks: { name: string; t: number; utt?: string }[]): Promise<void> {
  if (MOCK || !marks.length) return;
  try { await request('POST', '/telemetry/voice', { body: { sid, marks }, auth: true }); } catch { /* optional route */ }
}
