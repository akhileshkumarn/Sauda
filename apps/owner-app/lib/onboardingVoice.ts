'use client';
// Conversational onboarding client: /tn/onboarding*. NEXT_PUBLIC_MOCK=1 runs a small local stand-in so the
// screen can be exercised without a backend (validation there is format-only, like the form).
import { API_BASE, ApiError, MOCK } from './api';
import { getIdToken } from './auth';
import { createBusiness, gstinCheck, pinCheck, runVerification } from './network';
import type { TnRole } from './types';

export type OnbLang = 'en' | 'hi' | 'te';
export type OnbStatus = 'collecting' | 'confirming' | 'created' | 'cancelled';

export interface OnbDraft {
  roles: TnRole[]; display_name: string; legal_name: string | null; constitution: string | null; category: string | null;
  products: string[]; gst_registered: boolean | null; gstin: string | null; udyam: string | null; fssai: string | null; cin_llpin: string | null;
  address: { line: string; city: string; state: string; pin: string; district?: string };
  representative: { name: string; role: string }; phone: string | null; email: string | null; brand_claims: string[];
  service_area: string | null; consents: { registry: boolean; address: boolean; store: boolean } | null;
}
export interface OnbApplied { field: string; value: string | string[] | null; shown: string; check?: string | null }
export interface OnbTurn { role: 'owner' | 'sauda'; text: string; ts?: string; source?: string; lang?: string; applied?: OnbApplied[] }
export interface OnbSession {
  oid: string; role: TnRole; status: OnbStatus; version: number; draft: OnbDraft; missing: string[]; asked: string | null;
  question: string; checks: Record<string, string>; turns: OnbTurn[]; bid?: string | null; lang: OnbLang; is_fixture?: boolean;
}
export interface OnbTurnResponse {
  session: OnbSession; reply: string; applied: OnbApplied[]; latency_ms: Record<string, number>; fast_path: boolean; dedup: boolean;
  screened?: { blocked: boolean; categories: string[] };
}
export interface OnbConfirmResponse { bid: string; summary: unknown; session: OnbSession; latency_ms?: Record<string, number> }
export type OnbCandidate = { bid?: string; display_name?: string; city?: string; gstin_masked?: string };

export const CONSTITUTION_LABEL: Record<string, string> = {
  proprietorship: 'Sole proprietorship', partnership: 'Partnership firm', llp: 'LLP', private_limited: 'Private limited company',
  public_limited: 'Public limited company', other: 'Other (HUF, trust, society)',
};

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const t = await getIdToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(`${API_BASE}${path}`, { method, headers, cache: 'no-store', body: body !== undefined ? JSON.stringify(body) : undefined });
  if (!res.ok) {
    let code = `HTTP_${res.status}`; let message = res.statusText; let b: unknown;
    try { const j = await res.json(); b = j; code = j.detail?.code || j.code || code; message = j.detail?.message || j.message || (typeof j.detail === 'string' ? j.detail : message); } catch { /* not JSON */ }
    throw new ApiError(res.status, code, message, b);
  }
  return res.json() as Promise<T>;
}

export async function startOnboarding(role: TnRole, lang: OnbLang): Promise<{ session: OnbSession; reply: string }> {
  if (MOCK) return mockStart(role, lang);
  return req('POST', '/tn/onboarding', { role, lang });
}
export async function sendTurn(oid: string, t: { client_turn_id: string; text: string; source: 'voice' | 'text'; lang: OnbLang }): Promise<OnbTurnResponse> {
  if (MOCK) return mockTurn(oid, t);
  return req('POST', `/tn/onboarding/${encodeURIComponent(oid)}/turns`, t);
}
export async function editField(oid: string, version: number, updates: Record<string, unknown>, skip: string[] = []): Promise<{ session: OnbSession }> {
  if (MOCK) return mockEdit(oid, updates);
  return req('PATCH', `/tn/onboarding/${encodeURIComponent(oid)}`, { version, updates, skip });
}
export async function confirmOnboarding(oid: string, version: number, consents: { registry: boolean; address: boolean; store: boolean }, confirmNotDuplicate = false): Promise<OnbConfirmResponse> {
  if (MOCK) return mockConfirm(oid, consents, confirmNotDuplicate);
  return req('POST', `/tn/onboarding/${encodeURIComponent(oid)}/confirm`, { version, consents, confirm_not_duplicate: confirmNotDuplicate });
}

/** The draft in the shape the step-by-step form keeps in sessionStorage, so "switch to the form" carries it over. */
export function toFormDraft(s: OnbSession) {
  const d = s.draft;
  return {
    role: s.role, display_name: d.display_name || '', legal_name: d.legal_name || '', constitution: d.constitution || 'proprietorship',
    kind: d.category || (s.role === 'seller' ? 'distributor' : 'kirana'), gst_registered: d.gst_registered === true ? 'yes' : d.gst_registered === false ? 'no' : '',
    gstin: d.gstin || '', udyam: d.udyam || '', fssai: d.fssai || '', cin_llpin: d.cin_llpin || '', handles_food: true,
    line: d.address.line || '', city: d.address.city || '', state: d.address.state || '', pin: d.address.pin || '',
    rep_name: d.representative.name || '', rep_role: d.representative.role || 'Proprietor',
    products: d.products || [], brands: (d.brand_claims || []).join(', '),
  };
}
export function carryToForm(s: OnbSession) { try { sessionStorage.setItem('sauda-tn-onboard', JSON.stringify(toFormDraft(s))); } catch { /* ignore */ } }

// ---------------------------------------------------------------- mock (deterministic, format checks only)
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const store: Record<string, OnbSession & { skipped: string[] }> = {};
const QS: Record<string, Record<OnbLang, string>> = {
  opening: { en: 'Tell me about your shop: its name, where it is, and what you sell.', hi: 'अपनी दुकान के बारे में बताइए: नाम, कहाँ है, और क्या बेचते हैं।', te: 'మీ షాప్ గురించి చెప్పండి: పేరు, ఎక్కడ ఉంది, ఏమి అమ్ముతారు.' },
  display_name: { en: "What's the name on your shop board?", hi: 'आपकी दुकान के बोर्ड पर क्या नाम है?', te: 'మీ షాప్ బోర్డు మీద పేరు ఏమిటి?' },
  constitution: { en: 'Is it a sole proprietorship, a partnership, an LLP or a company?', hi: 'यह प्रोपराइटरशिप है, पार्टनरशिप, LLP या कंपनी?', te: 'ఇది ప్రొప్రైటర్‌షిప్, పార్ట్‌నర్‌షిప్, LLP లేదా కంపెనీనా?' },
  gst_registered: { en: 'Is the business registered for GST?', hi: 'क्या कारोबार GST में रजिस्टर्ड है?', te: 'మీ వ్యాపారం GST లో రిజిస్టర్ అయిందా?' },
  gstin: { en: "What's your GSTIN? I ask so suppliers can check your registration; you can skip it if you aren't registered.", hi: 'आपका GSTIN क्या है? इससे सप्लायर आपका रजिस्ट्रेशन जाँच सकते हैं; रजिस्टर्ड नहीं हैं तो छोड़ सकते हैं।', te: 'మీ GSTIN ఏమిటి? సప్లయర్లు మీ రిజిస్ట్రేషన్ చూసుకోవడానికి అడుగుతున్నాను; రిజిస్టర్ కాకపోతే వదిలేయవచ్చు.' },
  pin: { en: "What's the PIN code of the shop?", hi: 'दुकान का पिन कोड क्या है?', te: 'షాప్ పిన్ కోడ్ ఏమిటి?' },
  address_line: { en: "What's the street or area, so partners can find you?", hi: 'गली या इलाका क्या है?', te: 'వీధి లేదా ఏరియా ఏమిటి?' },
  rep_name: { en: "Who am I speaking with, and what's your role: proprietor, partner or manager?", hi: 'मैं किससे बात कर रहा हूँ, और आपकी भूमिका क्या है?', te: 'నేను ఎవరితో మాట్లాడుతున్నాను, మీ పాత్ర ఏమిటి?' },
  products: { en: 'What do you mostly buy for the shop: staples, oil, snacks, personal care?', hi: 'दुकान के लिए ज़्यादातर क्या खरीदते हैं?', te: 'షాప్ కోసం ఎక్కువగా ఏమి కొంటారు?' },
  consent: { en: 'Last thing: may I check the numbers you gave and your address with official records? Results stay private; partners see only a summary. Yes or no?', hi: 'आख़िरी बात: क्या मैं आपके नंबर और पता सरकारी रिकॉर्ड से जाँच सकता हूँ? हाँ या ना?', te: 'చివరిగా: మీ నంబర్లు, చిరునామాను అధికారిక రికార్డులతో చెక్ చేయవచ్చా? అవునా కాదా?' },
};
function mockMissing(s: OnbSession & { skipped: string[] }) {
  const d = s.draft; const m: string[] = [];
  if (!d.display_name) m.push('display_name');
  if (!d.constitution) m.push('constitution');
  if (d.gst_registered === null) m.push('gst_registered'); else if (d.gst_registered && !d.gstin) m.push('gstin');
  if (!d.address.pin) m.push('pin');
  if (!d.address.line) m.push('address_line');
  if (!d.representative.name) m.push('rep_name');
  if (!d.products.length) m.push('products');
  if (!d.consents) m.push('consent');
  return m;
}
function mockSummary(d: OnbDraft) {
  return `Here's what I have: ${[d.display_name, (CONSTITUTION_LABEL[d.constitution || ''] || '').replace('Sole ', '').toLowerCase(), d.gstin ? `GSTIN ${d.gstin.slice(0, 2)}…${d.gstin.slice(-3)}` : 'not GST registered',
    [d.address.line, d.address.city, d.address.pin].filter(Boolean).join(' '), d.representative.name && `${d.representative.name} (${(d.representative.role || '').toLowerCase()})`, d.products.length && `buying ${d.products.join(', ').toLowerCase()}`].filter(Boolean).join(', ')}. Shall I create your profile?`;
}
function mockNext(s: OnbSession & { skipped: string[] }) {
  s.missing = mockMissing(s);
  if (!s.missing.length) { s.status = 'confirming'; s.asked = 'confirm'; return mockSummary(s.draft); }
  s.status = 'collecting'; s.asked = s.missing[0];
  return QS[s.asked]?.[s.lang] || QS[s.asked]?.en || '';
}
function mockStart(role: TnRole, lang: OnbLang) {
  const oid = `onb_${Math.random().toString(16).slice(2, 14).padEnd(12, '0')}`;
  const draft: OnbDraft = { roles: [role], display_name: '', legal_name: null, constitution: null, category: null, products: [], gst_registered: null, gstin: null, udyam: null, fssai: null, cin_llpin: null,
    address: { line: '', city: '', state: '', pin: '' }, representative: { name: '', role: '' }, phone: null, email: null, brand_claims: [], service_area: null, consents: null };
  const q = QS.opening[lang];
  const s = { oid, role, status: 'collecting' as OnbStatus, version: 1, draft, missing: [], asked: null, question: q, checks: {}, turns: [{ role: 'sauda' as const, text: q }], lang, skipped: [] };
  store[oid] = s; s.missing = mockMissing(s) as never;
  return sleep(250).then(() => ({ session: structuredClone(s), reply: q }));
}
const YES = /^(yes|yeah|ok|sure|haan?|हाँ|हां|avunu|అవును)\b/i;
const NO = /^(no|nahi|नहीं|ledu|లేదు)\b/i;
async function mockTurn(oid: string, t: { text: string; lang: OnbLang; source: 'voice' | 'text' }): Promise<OnbTurnResponse> {
  await sleep(500);
  const s = store[oid]; if (!s) throw new ApiError(404, 'not_found', 'onboarding session not found');
  s.lang = t.lang;
  const text = t.text.trim(); const d = s.draft; const ap: OnbApplied[] = []; const notes: string[] = [];
  const add = (field: string, value: string | string[], shown: string, check?: string) => ap.push({ field, value, shown, check });
  if (/\d{4}\s?\d{4}\s?\d{4}/.test(text) || /aadh?aa?r|आधार|ఆధార్/i.test(text)) notes.push("Sauda never asks for Aadhaar, so I haven't kept that number. Please don't share it here.");
  else if (/ignore (all )?previous/i.test(text)) notes.push("I can only take details about your business here, so I've ignored that.");
  else {
    const g = text.replace(/[\s-]/g, '').toUpperCase().match(/\d{2}[A-Z0-9]{13}/)?.[0];
    const pin = text.match(/(?<!\d)[1-9]\d{5}(?!\d)/)?.[0];
    if (g) { const c = gstinCheck(g); if (c.ok) { d.gstin = g; d.gst_registered = true; add('gstin', g, `GSTIN ${g.slice(0, 2)}…${g.slice(-3)}`, 'format check only'); } else notes.push(`That GSTIN doesn't look right (${c.message}). Could you read it again?`); }
    else if (pin) { const p = pinCheck(pin); d.address.pin = pin; d.address.state = p.state || ''; if (!d.address.city) d.address.city = 'Hyderabad'; add('pin', pin, `PIN ${pin} (${d.address.city}, ${d.address.state})`, 'format check only'); }
    else if (s.asked === 'consent' && (YES.test(text) || NO.test(text))) { const y = YES.test(text); d.consents = { registry: y, address: y, store: true }; add('consent', y ? 'yes' : 'no', y ? 'checks agreed' : 'no lookups'); }
    else if (s.asked === 'gst_registered' && (YES.test(text) || NO.test(text) || /not registered/i.test(text))) { const y = YES.test(text); d.gst_registered = y; add('gst_registered', y ? 'yes' : 'no', y ? 'GST registered' : 'not GST registered'); }
    else if (/propriet|partner|llp|private|company/i.test(text) && (s.asked === 'constitution' || !d.constitution)) { const c = /llp/i.test(text) ? 'llp' : /partner/i.test(text) ? 'partnership' : /private|company/i.test(text) ? 'private_limited' : 'proprietorship'; d.constitution = c; add('constitution', c, CONSTITUTION_LABEL[c].toLowerCase()); }
    else if (!d.display_name) {
      const m = text.match(/(?:this is|we are|name is|called)\s+([^,.]+?)(?:,| in | at |\.|$)/i);
      d.display_name = (m?.[1] || text).trim().slice(0, 120); add('display_name', d.display_name, d.display_name);
      const where = text.match(/\bin ([A-Z][a-z]+(?:,? [A-Z][a-z]+)?)/); if (where) { const parts = where[1].split(/,? /); d.address.line = parts[0]; d.address.city = parts[1] || parts[0]; add('address_line', d.address.line, where[1]); }
      const sells = text.match(/sell (.+)$/i); if (sells) { d.products = sells[1].split(/,| and /).map((x) => x.trim()).filter(Boolean).map((x) => x[0].toUpperCase() + x.slice(1)).slice(0, 6); add('products', d.products, d.products.join(', ').toLowerCase()); }
    } else if (s.asked === 'rep_name') { const m = text.match(/(?:i am|i'm|this is)\s+([A-Za-z ]+?)(?:,|$| the| and)/i); d.representative = { name: (m?.[1] || text).trim(), role: /partner/i.test(text) ? 'Partner' : /manager/i.test(text) ? 'Manager' : 'Proprietor' }; add('rep_name', d.representative.name, `you're ${d.representative.name}, ${d.representative.role.toLowerCase()}`); }
    else if (s.asked === 'address_line') { d.address.line = text; add('address_line', text, text); }
    else if (s.asked === 'products') { d.products = text.split(/,| and /).map((x) => x.trim()).filter(Boolean); add('products', d.products, d.products.join(', ').toLowerCase()); }
  }
  const q = mockNext(s);
  if (!ap.length && !notes.length) notes.push("Sorry, I didn't catch that.");
  const reply = [ap.length ? `Got it: ${ap.map((a) => a.shown).join(', ')}.` : '', ...notes, q].filter(Boolean).join(' ');
  s.question = q; s.version += 1;
  s.checks = { ...(d.gstin ? { gstin: 'format check only' } : {}), ...(d.address.pin ? { pin: 'format check only' } : {}) };
  s.turns.push({ role: 'owner', text: notes[0]?.includes('Aadhaar') ? text.replace(/\d{4}\s?\d{4}\s?\d{4}/, '[removed]') : text, source: t.source }, { role: 'sauda', text: reply, applied: ap });
  return { session: structuredClone(s), reply, applied: ap, latency_ms: { extract: 420, apply: 3, total: 510 }, fast_path: !!(ap[0] && ['gstin', 'pin', 'consent', 'gst_registered'].includes(ap[0].field)), dedup: false };
}
async function mockEdit(oid: string, updates: Record<string, unknown>) {
  await sleep(200);
  const s = store[oid]; if (!s) throw new ApiError(404, 'not_found', 'onboarding session not found');
  const d = s.draft as unknown as Record<string, unknown>;
  for (const [k, v] of Object.entries(updates)) {
    if (k === 'gstin') { if (!gstinCheck(String(v)).ok) throw new ApiError(422, 'invalid_field', "That GSTIN doesn't look right."); s.draft.gstin = String(v).toUpperCase(); s.draft.gst_registered = true; }
    else if (k === 'pin') { const p = pinCheck(String(v)); if (!p.ok) throw new ApiError(422, 'invalid_field', 'A PIN code has 6 digits.'); s.draft.address.pin = String(v); s.draft.address.state = p.state || s.draft.address.state; }
    else if (k === 'city' || k === 'address_line') s.draft.address[k === 'city' ? 'city' : 'line'] = String(v);
    else if (k === 'rep_name') s.draft.representative.name = String(v);
    else if (k === 'rep_role') s.draft.representative.role = String(v);
    else if (k === 'products') s.draft.products = String(v).split(',').map((x) => x.trim()).filter(Boolean);
    else if (k === 'consents') s.draft.consents = v as OnbDraft['consents'];
    else d[k] = v;
  }
  s.question = mockNext(s); s.version += 1;
  return { session: structuredClone(s) };
}
async function mockConfirm(oid: string, consents: { registry: boolean; address: boolean; store: boolean }, confirmNotDuplicate: boolean): Promise<OnbConfirmResponse> {
  const s = store[oid]; if (!s) throw new ApiError(404, 'not_found', 'onboarding session not found');
  const d = s.draft;
  const b = await createBusiness({ roles: d.roles, display_name: d.display_name, legal_name: d.legal_name, constitution: d.constitution, category: d.category || 'kirana', products: d.products,
    gstin: d.gstin, address: { line: d.address.line, city: d.address.city, state: d.address.state, pin: d.address.pin }, representative: { name: d.representative.name, role: d.representative.role, authority_status: 'self_declared' },
    brand_claims: d.brand_claims, ...(confirmNotDuplicate ? { confirm_not_duplicate: true } : {}) } as never);
  const reg = consents.registry;
  const v = await runVerification(b.bid, { gst: reg, udyam: reg, fssai: reg, mca: reg, address: consents.address, store: consents.store, location: false });
  s.status = 'created'; s.bid = b.bid; s.version += 1;
  return { bid: b.bid, summary: (v as { summary?: unknown }).summary, session: structuredClone(s) };
}
