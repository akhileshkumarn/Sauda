'use client';
// Trust Network client: business verification, invitations, relationships, reviewer console.
// Builds against CONTRACT_TN (API section). NEXT_PUBLIC_MOCK=1 serves fixtures from ./mock.
import { useEffect, useState } from 'react';
import { API_BASE, ApiError, MOCK } from './api';
import { getIdToken, onUser } from './auth';
import * as mock from './mock';
import type {
  TnBusiness, TnBusinessFull, TnEvidence, TnInvitation, TnLedger, TnBusinessMine, TnCategory, TnCheck, TnCheckStatus, TnDim, TnEvidenceResponse, TnEvidenceType,
  TnInvitationCreated, TnInvitationPublic, TnProfile, TnReadiness, TnRelationship, TnRelState, TnReviewAction, TnReviewTask,
  TnReviewTaskDetail, TnRole, TnSourceKind, TnSummary, TnVerifyResponse, TnDimensionSummary,
} from './types';
import type { TnAreas, TnConnectResponse, TnDiscoverQuery, TnDiscoverResponse, TnListing, TnListingSaved, TnServiceArea } from './types';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function req<T>(method: string, path: string, opts: { body?: unknown; form?: FormData; auth?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.auth !== false) {
    const t = await getIdToken();
    if (t) headers.Authorization = `Bearer ${t}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method, headers, cache: 'no-store',
    body: opts.form ? opts.form : opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let code = `HTTP_${res.status}`; let message = res.statusText; let body: unknown;
    try {
      const j = await res.json(); body = j;
      const d = j.detail;
      code = d?.code || j.code || code;
      message = d?.message || j.message || (typeof d === 'string' ? d : null)
        || (Array.isArray(d) ? d.map((x: { msg?: string; loc?: unknown[] }) => [x.loc?.slice(1).join('.'), x.msg].filter(Boolean).join(': ')).join('; ') : null) || message;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, code, message, body);
  }
  return res.json() as Promise<T>;
}

/** Mock errors carry {status, code, body}; turn them into ApiError so screens treat both modes alike. */
async function m<T>(fn: () => T, ms = 300): Promise<T> {
  await sleep(ms);
  try { return fn(); } catch (e) {
    const x = e as { status?: number; code?: string; message?: string; body?: unknown };
    if (typeof x?.status === 'number' && x.status > 0) throw new ApiError(x.status, x.code || `HTTP_${x.status}`, x.message || '', x.body);
    throw e;
  }
}

const list = <T,>(r: unknown, ...keys: string[]): T[] => {
  if (Array.isArray(r)) return r as T[];
  for (const k of keys) { const v = (r as Record<string, unknown> | null)?.[k]; if (Array.isArray(v)) return v as T[]; }
  return [];
};

/** Fields of a 409 body: {detail:{code, missing|candidates}} or top-level. */
export function errorDetail(e: unknown): { code?: string; missing?: string[]; candidates?: { bid?: string; display_name?: string; city?: string }[] } {
  if (!(e instanceof ApiError)) return {};
  const b = e.body as Record<string, unknown> | undefined;
  const d = (b?.detail && typeof b.detail === 'object' ? b.detail : b) as Record<string, unknown> | undefined;
  return { code: (d?.code as string) || e.code, missing: (d?.missing as string[]) || undefined, candidates: (d?.candidates as never) || undefined };
}

// ---------------------------------------------------------------- businesses
export type NewBusiness = Partial<Omit<TnBusiness, 'bid' | 'version'>> & { roles: TnRole[]; display_name: string };

export async function createBusiness(body: NewBusiness & { confirm_not_duplicate?: boolean }): Promise<TnBusiness> {
  if (MOCK) return m(() => mock.mockTnCreate(body), 500);
  const r = await req<TnBusiness | { business: TnBusiness }>('POST', '/tn/businesses', { body });
  return 'business' in r && r.business ? r.business : (r as TnBusiness);
}
export async function myBusinesses(): Promise<TnBusinessMine[]> {
  if (MOCK) return m(() => mock.mockTnMine());
  return list<TnBusinessMine>(await req('GET', '/tn/businesses/mine'), 'businesses', 'items');
}
export async function getBusiness(bid: string): Promise<TnBusinessFull> {
  if (MOCK) return m(() => mock.mockTnBusiness(bid));
  const [r, cr] = await Promise.all([
    req<Record<string, unknown>>('GET', `/tn/businesses/${encodeURIComponent(bid)}`),
    req<unknown>('GET', `/tn/businesses/${encodeURIComponent(bid)}/checks`).catch(() => null),
  ]);
  const business = (r.business || r) as TnBusiness;
  const checks = cr ? list<TnCheck>(cr, 'checks') : list<TnCheck>(r, 'checks');
  return { business, checks, summary: (r.summary as TnSummary) || null };
}
export async function getSummary(bid: string): Promise<TnSummary> {
  if (MOCK) return m(() => mock.mockTnSummary(bid));
  return req('GET', `/tn/businesses/${encodeURIComponent(bid)}/summary`);
}
export async function patchBusiness(bid: string, patch: Partial<TnBusiness> & { version: number }): Promise<TnBusiness> {
  if (MOCK) return m(() => mock.mockTnBusiness(bid).business);
  const r = await req<TnBusiness | { business: TnBusiness }>('PATCH', `/tn/businesses/${encodeURIComponent(bid)}`, { body: patch });
  return 'business' in r && r.business ? r.business : (r as TnBusiness);
}
export type Consents = Record<string, boolean>;
export async function runVerification(bid: string, consents: Consents): Promise<TnVerifyResponse> {
  if (MOCK) return m(() => mock.mockTnVerify(bid), 1400);
  const r = await req<TnVerifyResponse>('POST', `/tn/businesses/${encodeURIComponent(bid)}/verify`, { body: { consents } });
  return { case: r.case, checks: list<TnCheck>(r, 'checks') };
}
export async function requestManualReview(bid: string, note = ''): Promise<{ reason_text: string[] }> {
  if (MOCK) return m(() => ({ reason_text: ['The business asked for a manual review.'] }), 600);
  return req<{ reason_text: string[] }>('POST', `/tn/businesses/${encodeURIComponent(bid)}/request-review`, { body: { note } });
}
export async function uploadEvidence(bid: string, type: TnEvidenceType, file: File): Promise<TnEvidenceResponse> {
  if (MOCK) return m(() => mock.mockTnEvidence(bid, type), 1200);
  const fd = new FormData(); fd.append('type', type); fd.append('file', file); fd.append('consent', 'true');
  const r = await req<TnEvidenceResponse>('POST', `/tn/businesses/${encodeURIComponent(bid)}/evidence`, { form: fd });
  return { evidence: r.evidence, checks: list<TnCheck>(r, 'checks') };
}
export async function shareLocation(bid: string, g: { lat: number; lng: number; accuracy_m: number }): Promise<TnCheck | unknown> {
  if (MOCK) return m(() => mock.mockTnLocation(bid, g), 700);
  return req('POST', `/tn/businesses/${encodeURIComponent(bid)}/location`, { body: { ...g, consent: true } });
}
export async function getProfile(bid: string): Promise<TnProfile> {
  if (MOCK) return m(() => mock.mockTnProfile(bid));
  const r = await req<Record<string, any>>('GET', `/tn/businesses/${encodeURIComponent(bid)}/profile`); // eslint-disable-line @typescript-eslint/no-explicit-any
  const v = r.verification || r.summary || {};
  const summary: TnSummary = {
    category: v.category, category_label: v.category_label, next_step: v.next_step || '', limitations: v.limitations || [],
    outstanding: v.outstanding || [], dimensions: (v.dimensions || []).map((d: TnDimensionSummary) => ({ ...d, summary: d.summary || '' })),
  };
  return {
    ...(r as object), bid: r.bid, display_name: r.display_name, roles: r.roles || [], products: r.products || [],
    address: r.address || { city: r.city, state: r.state, pin: r.pin_prefix }, summary,
    outstanding_count: v.outstanding_count, gstin_masked: r.gstin_masked,
  } as TnProfile;
}

// ---------------------------------------------------------------- invitations + relationships
export async function createInvitation(body: { from_bid: string; role_invited: TnRole; contact: string; categories: string[]; display_name?: string }): Promise<TnInvitationCreated> {
  if (MOCK) return m(() => mock.mockTnInvite(body), 450);
  const { display_name, ...rest } = body;
  const r = await req<TnInvitationCreated & { share_link?: string | null; duplicate?: boolean }>('POST', '/tn/invitations', { body: { ...rest, display_name_hint: display_name || null } });
  return { ...r, share_url: r.share_url || r.share_link || null };
}
export async function getInvitation(token: string): Promise<TnInvitationPublic> {
  if (MOCK) return m(() => mock.mockTnInvitationPublic(token));
  const r = await req<Record<string, unknown>>('GET', `/tn/invitations/${encodeURIComponent(token)}`, { auth: false });
  return {
    from_display_name: String(r.from_display_name || r.inviter_display_name || r.display_name || (r.from as Record<string, unknown>)?.display_name || 'A business'),
    role_invited: (r.role_invited as TnRole) || 'seller', status: r.status as string | undefined, expires_at: r.expires_at as string | undefined,
  };
}
export async function acceptInvitation(token: string, bid: string): Promise<TnRelationship> {
  if (MOCK) return m(() => mock.mockTnAccept(token, bid), 600);
  const r = await req<TnRelationship | { relationship: TnRelationship }>('POST', `/tn/invitations/${encodeURIComponent(token)}/accept`, { body: { bid } });
  return 'relationship' in r && r.relationship ? r.relationship : (r as TnRelationship);
}
export async function listInvitations(bid: string): Promise<TnInvitation[]> {
  if (MOCK) return m(() => mock.mockTnInvitations(bid));
  return list<TnInvitation>(await req('GET', `/tn/invitations?bid=${encodeURIComponent(bid)}`), 'invitations', 'items');
}
export async function revokeInvitation(iid: string): Promise<TnInvitation> {
  if (MOCK) return m(() => mock.mockTnRevoke(iid));
  return req('POST', `/tn/invitations/${encodeURIComponent(iid)}/revoke`, { body: {} });
}
export async function listEvidence(bid: string): Promise<TnEvidence[]> {
  if (MOCK) return m(() => mock.mockTnEvidenceList(bid));
  return list<TnEvidence>(await req('GET', `/tn/businesses/${encodeURIComponent(bid)}/evidence`), 'evidence', 'items');
}
export async function evidenceUrl(eid: string): Promise<string> {
  if (MOCK) { await sleep(300); throw new ApiError(503, 'unavailable', 'signed links are unavailable in this environment'); }
  const r = await req<{ url: string }>('GET', `/tn/evidence/${encodeURIComponent(eid)}/url`);
  return r.url;
}
export async function getLedger(bid: string): Promise<TnLedger> {
  if (MOCK) return m(() => mock.mockTnLedger(bid));
  return req('GET', `/tn/businesses/${encodeURIComponent(bid)}/ledger`);
}
/** Backend history rows use {from, to}; the UI reads `state`. */
function normRel(r: TnRelationship): TnRelationship {
  return { ...r, history: (r.history || []).map((h) => ({ ...h, state: h.state || (h as { to?: string }).to })) };
}
export async function listRelationships(bid: string): Promise<TnRelationship[]> {
  if (MOCK) return m(() => mock.mockTnRelationships(bid));
  return list<TnRelationship>(await req('GET', `/tn/relationships?bid=${encodeURIComponent(bid)}`), 'relationships', 'items').map(normRel);
}
export async function getRelationship(rid: string, bid?: string): Promise<TnRelationship> {
  if (MOCK) return m(() => mock.mockTnRelationship(rid));
  void bid;
  return normRel(await req<TnRelationship>('GET', `/tn/relationships/${encodeURIComponent(rid)}`));
}
export type RelAction = 'accept_request' | 'approve_for_trading' | 'decline' | 'pause' | 'start_review' | 'resume';
export async function decideRelationship(rid: string, action: RelAction, reason: string, tier = 'prepaid_small', version?: number): Promise<TnRelationship> {
  if (MOCK) return m(() => mock.mockTnDecision(rid, action, reason, tier), 600);
  const r = await req<TnRelationship | { relationship: TnRelationship }>('POST', `/tn/relationships/${encodeURIComponent(rid)}/decision`, { body: { action, reason, tier, ...(version !== undefined ? { version } : {}) } });
  return normRel('relationship' in r && r.relationship ? r.relationship : (r as TnRelationship));
}

// ---------------------------------------------------------------- reviewer
export async function reviewQueue(): Promise<TnReviewTask[]> {
  if (MOCK) return m(() => mock.mockReviewQueue());
  return list<TnReviewTask & { reason_text?: string[] }>(await req('GET', '/review/queue'), 'tasks', 'queue', 'items').map((t) => ({ ...t, reasons: t.reason_text?.length ? t.reason_text : t.reasons || [] }));
}
export async function reviewTask(tid: string): Promise<TnReviewTaskDetail> {
  if (MOCK) return m(() => mock.mockReviewTask(tid));
  const r = await req<Record<string, unknown>>('GET', `/review/tasks/${encodeURIComponent(tid)}`);
  const t0 = (r.task || r) as TnReviewTask & { reason_text?: string[] };
  const task = { ...t0, reasons: t0.reason_text?.length ? t0.reason_text : t0.reasons || [], decisions: t0.decisions || [] };
  return { ...(r as object), task, checks: list<TnCheck>(r, 'checks'), business: (r.business as TnBusiness) || null } as TnReviewTaskDetail;
}
export async function reviewDecision(tid: string, body: { action: TnReviewAction; scope: string; reason: string }): Promise<TnReviewTask | unknown> {
  if (MOCK) return m(() => mock.mockReviewDecision(tid, body), 600);
  return req('POST', `/review/tasks/${encodeURIComponent(tid)}/decision`, { body });
}

export type ReviewerMode = { reviewer: boolean; demo: boolean; note?: string | null };
export async function reviewMe(): Promise<ReviewerMode> {
  if (MOCK) return m(() => ({ reviewer: mock.mockMode() !== 'noreview', demo: mock.mockMode() === 'noreview', note: mock.mockMode() === 'noreview' ? DEMO_REVIEW_NOTE : null }), 50);
  return req<ReviewerMode>('GET', '/review/me');
}
export const DEMO_REVIEW_NOTE = 'Demo mode: you can review only simulated demo businesses and your own sample shop. Real businesses are reviewed only by Sauda reviewers.';

let reviewerCache: ReviewerMode | null = null;
/** {reviewer, demo}: real reviewers (REVIEWER_EMAILS) see everything; anyone else gets the demo console on demo data only. */
export function useReviewerMode(): ReviewerMode {
  const [mode, setMode] = useState<ReviewerMode>(reviewerCache || { reviewer: false, demo: true });
  useEffect(() => {
    if (reviewerCache !== null) { setMode(reviewerCache); return; }
    let live = true;
    let unsub: (() => void) | undefined;
    const load = async () => {
      try { reviewerCache = await reviewMe(); } catch { reviewerCache = { reviewer: false, demo: true }; }
      if (live) setMode(reviewerCache);
    };
    if (MOCK) { load(); return () => { live = false; }; }
    // Only ask once someone is signed in; a signed-out visitor never triggers a 401.
    onUser((u) => { if (u && live && reviewerCache === null) load(); })
      .then((u) => { unsub = u; if (!live) unsub?.(); }).catch(() => {});
    return () => { live = false; unsub?.(); };
  }, []);
  return mode;
}
/** True only for real Sauda reviewers. */
export function useIsReviewer(): boolean { return useReviewerMode().reviewer; }

// ---------------------------------------------------------------- sample shop (sandbox)
export type SandboxView = { business: TnBusinessMine; created: boolean; sandbox: true; label: string; status_text: string };
export async function sandboxStart(firstName?: string): Promise<SandboxView> {
  if (MOCK) return m(() => mock.mockSandboxStart(firstName), 500);
  return req<SandboxView>('POST', '/tn/sandbox/start', { body: { first_name: firstName || null } });
}
export async function sandboxDelete(): Promise<{ ok: boolean; removed: number; existed: boolean }> {
  if (MOCK) return m(() => mock.mockSandboxDelete(), 400);
  return req('POST', '/tn/sandbox/delete');  // same as DELETE /tn/sandbox
}
export const SAMPLE_NOTE = 'Sample shop: simulated data so you can try every step. It is not a real business and only you can see it.';

// ---------------------------------------------------------------- WhatsApp share (public wa.me link, no API)
export function whatsappHref(text: string): string { return `https://wa.me/?text=${encodeURIComponent(text)}`; }
/** The only text ever shared: the business display name and a link the recipient must sign in to open. */
export function inviteMessage(business: string, link: string): string {
  return `${business} invited you to trade on Sauda. Open this link to verify your business and connect: ${link}`;
}
export function absoluteUrl(path: string): string {
  if (/^https?:/.test(path)) return path;
  const o = typeof window !== 'undefined' ? window.location.origin : '';
  return `${o}${path.startsWith('/') ? '' : '/'}${path}`;
}

// ---------------------------------------------------------------- active business
const BID_KEY = 'sauda-tn-bid';
export function rememberBid(bid: string) { try { localStorage.setItem(BID_KEY, bid); } catch { /* ignore */ } }
export function pickBusiness<T extends { bid: string }>(mine: T[]): T | null {
  let saved = '';
  try { saved = localStorage.getItem(BID_KEY) || ''; } catch { /* ignore */ }
  return mine.find((b) => b.bid === saved) || mine[0] || null;
}

// ---------------------------------------------------------------- words
export const CATEGORY_WORD: Record<TnCategory, { label: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' }> = {
  ready_for_counterparty_review: { label: 'Ready for supplier review', tone: 'ok' },
  identity_confirmed: { label: 'Identity confirmed', tone: 'ok' },
  evidence_reviewed: { label: 'Evidence reviewed', tone: 'ok' },
  additional_review_required: { label: 'Partially verified', tone: 'warn' },
  verification_unsuccessful: { label: 'Verification unsuccessful', tone: 'bad' },
};
export function categoryWord(c: TnCategory | string | undefined, role?: TnRole[], sample?: boolean): { label: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' } {
  const w0 = CATEGORY_WORD[c as TnCategory] || { label: c ? 'Verification pending' : 'Not checked yet', tone: 'neutral' as const };
  const w = sample ? { ...w0, label: `${w0.label} (sample)` } : w0;
  if (c === 'ready_for_counterparty_review' && role && role.includes('seller') && !role.includes('buyer')) return { ...w, label: 'Ready for buyer review' };
  return w;
}

export const STATUS_WORD: Record<TnCheckStatus, { label: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' | 'info' }> = {
  verified: { label: 'Verified', tone: 'ok' },
  partially_verified: { label: 'Partially verified', tone: 'warn' },
  self_declared: { label: 'Self-declared', tone: 'neutral' },
  pending: { label: 'Pending', tone: 'info' },
  inconclusive: { label: 'Inconclusive', tone: 'neutral' },
  stale: { label: 'Stale', tone: 'warn' },
  conflict: { label: 'Conflict', tone: 'bad' },
  failed: { label: 'Did not match', tone: 'bad' },
  not_applicable: { label: 'Not applicable', tone: 'neutral' },
};
export const statusWord = (s: string) => STATUS_WORD[s as TnCheckStatus] || { label: s.replace(/_/g, ' '), tone: 'neutral' as const };

export const SOURCE_WORD: Record<TnSourceKind, string> = {
  official_registry: 'Official record',
  authorised_provider: 'Authorised provider',
  uploaded_evidence: 'Uploaded document',
  human_review: 'Human-reviewed',
  self_declared: 'Self-declared',
  preliminary_validation: 'Preliminary check',
  simulated_fixture: 'Simulated (demo data)',
  device_signal: 'Device location',
};
export const sourceWord = (s?: string | null) => (s ? SOURCE_WORD[s as TnSourceKind] || s.replace(/_/g, ' ') : '');

export const DIM_WORD: Record<TnDim, { label: string; help: string }> = {
  identity: { label: 'Business identity', help: 'Is the name the same as on the registration record?' },
  registration: { label: 'Registration', help: 'GSTIN, Udyam, CIN or LLPIN, when the business has one.' },
  address: { label: 'Address', help: 'Does the stated address exist and match the PIN?' },
  operational: { label: 'Shop or warehouse', help: 'Signs the business operates at this place, such as a storefront photo.' },
  representative: { label: 'Person acting for the business', help: 'Is this person allowed to act for the business?' },
  product_compliance: { label: 'Product licences', help: 'FSSAI for food businesses.' },
  distribution_authority: { label: 'Brand authorisation', help: 'For distributors who say they are authorised by a brand.' },
  trading_references: { label: 'Trading references', help: 'Confirmed trades with other businesses on Sauda.' },
  payment_details: { label: 'Payment details', help: 'The account payments go to belongs to this business.' },
  operational_capability: { label: 'Capacity to supply', help: 'Delivery area and order sizes.' },
};
export const dimWord = (d: string) => DIM_WORD[d as TnDim] || { label: d.replace(/_/g, ' '), help: '' };

export const REL_WORD: Record<TnRelState, { label: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' | 'info' }> = {
  requested: { label: 'Requested', tone: 'info' },
  invited: { label: 'Invited', tone: 'neutral' },
  accepted: { label: 'Accepted', tone: 'info' },
  onboarding: { label: 'Onboarding', tone: 'info' },
  under_review: { label: 'Under review', tone: 'warn' },
  approved_for_trading: { label: 'Approved for trading', tone: 'ok' },
  declined: { label: 'Declined', tone: 'bad' },
  paused: { label: 'Paused', tone: 'neutral' },
};
export const relWord = (s: string) => REL_WORD[s as TnRelState] || { label: s.replace(/_/g, ' '), tone: 'neutral' as const };

/** Outstanding items come as short codes (or sentences); map the known codes to actions. */
export const OUTSTANDING_WORD: Record<string, { label: string; action: 'upload' | 'location' | 'review' | 'none'; doc?: TnEvidenceType }> = {
  gst_certificate: { label: 'Upload your GST registration certificate', action: 'upload', doc: 'gst_certificate' },
  udyam_certificate: { label: 'Upload your Udyam certificate', action: 'upload', doc: 'udyam_certificate' },
  fssai_licence: { label: 'Upload your FSSAI licence or registration', action: 'upload', doc: 'fssai_licence' },
  authorisation_letter: { label: 'Upload a letter showing you can act for the business', action: 'upload', doc: 'authorisation_letter' },
  storefront_photo: { label: 'Add a photo of your shop front with the name board', action: 'upload', doc: 'storefront_photo' },
  location: { label: 'Share your location once, from the shop', action: 'location' },
  manual_review: { label: 'Ask a Sauda reviewer to look at this', action: 'review' },
  human_review: { label: 'A Sauda reviewer needs to look at this', action: 'review' },
};
export function outstandingWord(code: string): { label: string; action: 'upload' | 'location' | 'review' | 'none'; doc?: TnEvidenceType } {
  const k = code.toLowerCase().trim();
  if (OUTSTANDING_WORD[k]) return OUTSTANDING_WORD[k];
  const label = code.includes(' ') ? code : code.replace(/_/g, ' ');
  if (/resolve the problem|conflict|failed/.test(k)) return { label, action: 'review' };
  if (/^business identity|^registration|gst/.test(k)) return { label, action: 'upload', doc: 'gst_certificate' };
  if (/^(business )?address|location/.test(k)) return { label, action: 'location' };
  if (/^operating|operational status|photo|storefront/.test(k)) return { label, action: 'upload', doc: 'storefront_photo' };
  if (/^authorised representative|representative|authori[sz]ation letter/.test(k)) return { label, action: 'upload', doc: 'authorisation_letter' };
  if (/^product licen|fssai/.test(k)) return { label, action: 'upload', doc: 'fssai_licence' };
  if (/^brand distribution|brand/.test(k)) return { label, action: 'upload', doc: 'brand_authorisation' };
  if (/udyam/.test(k)) return { label, action: 'upload', doc: 'udyam_certificate' };
  if (/review/.test(k)) return { label, action: 'review' };
  return { label, action: 'none' };
}

export const DOC_WORD: Record<TnEvidenceType, string> = {
  gst_certificate: 'GST registration certificate',
  udyam_certificate: 'Udyam certificate',
  fssai_licence: 'FSSAI licence or registration',
  authorisation_letter: 'Authorisation letter',
  storefront_photo: 'Storefront photo',
  brand_authorisation: 'Brand authorisation letter',
  partnership_deed: 'Partnership deed',
  other: 'Other document',
};

export const REQUIREMENT_WORD: Record<string, string> = {
  identity: 'Business identity confirmed',
  registration: 'A registration (GSTIN, Udyam, CIN or LLPIN) checked',
  address: 'Address checked',
  representative: 'Person acting for the business confirmed',
  human_review: 'A Sauda reviewer has looked at the record',
  trading_references: 'Trading references',
  product_compliance: 'Product licence (FSSAI) checked',
  distribution_authority: 'Brand authorisation reviewed',
  payment_details: 'Payment details confirmed',
  relationship_review: 'A Sauda reviewer has approved this relationship',
};
export const requirementWord = (k: string) => REQUIREMENT_WORD[k] || dimWord(k).label;

export const TIER_WORD: Record<string, string> = {
  prepaid_small: 'Small prepaid orders',
  prepaid_regular: 'Regular prepaid orders',
  prepaid: 'Prepaid orders',
  credit: 'Orders on credit',
  large_order: 'Large orders',
  large_orders: 'Large orders',
};
export function readinessList(r: TnProfile['readiness'] | TnReadiness | null | undefined): TnReadiness[] {
  if (!r) return [];
  if (Array.isArray(r)) return r;
  if ('tier' in r && typeof (r as TnReadiness).tier === 'string') return [r as TnReadiness];
  return Object.entries(r as Record<string, TnReadiness>).map(([tier, v]) => ({ ...v, tier: v.tier || tier }));
}

// ---------------------------------------------------------------- preliminary validation (format only)
const GST_STATE: Record<string, string> = {
  '01': 'Jammu and Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab', '04': 'Chandigarh', '05': 'Uttarakhand', '06': 'Haryana', '07': 'Delhi',
  '08': 'Rajasthan', '09': 'Uttar Pradesh', '10': 'Bihar', '11': 'Sikkim', '12': 'Arunachal Pradesh', '13': 'Nagaland', '14': 'Manipur',
  '15': 'Mizoram', '16': 'Tripura', '17': 'Meghalaya', '18': 'Assam', '19': 'West Bengal', '20': 'Jharkhand', '21': 'Odisha', '22': 'Chhattisgarh',
  '23': 'Madhya Pradesh', '24': 'Gujarat', '26': 'Dadra and Nagar Haveli and Daman and Diu', '27': 'Maharashtra', '29': 'Karnataka', '30': 'Goa',
  '31': 'Lakshadweep', '32': 'Kerala', '33': 'Tamil Nadu', '34': 'Puducherry', '35': 'Andaman and Nicobar Islands', '36': 'Telangana', '37': 'Andhra Pradesh', '38': 'Ladakh',
};
export const INDIAN_STATES = [...new Set(Object.values(GST_STATE))].sort();

const B36 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
export function gstinCheck(raw: string): { ok: boolean; message: string; state?: string } {
  const g = raw.replace(/\s/g, '').toUpperCase();
  if (!g) return { ok: false, message: '' };
  if (!/^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(g)) return { ok: false, message: 'A GSTIN has 15 characters, like 36ABCDE1234F1Z5.' };
  const state = GST_STATE[g.slice(0, 2)];
  if (!state) return { ok: false, message: `State code ${g.slice(0, 2)} is not a valid GST state code.` };
  let sum = 0;
  for (let i = 0; i < 14; i++) { const p = B36.indexOf(g[i]) * (i % 2 ? 2 : 1); sum += Math.floor(p / 36) + (p % 36); }
  if (B36[(36 - (sum % 36)) % 36] !== g[14]) return { ok: false, message: 'The last character does not match. Check for a typing mistake.', state };
  return { ok: true, message: `Well-formed. State code ${g.slice(0, 2)} is ${state}.`, state };
}

/** First digits of an Indian PIN code to the state they usually belong to. Approximate; format check only. */
const PIN3: [string, string][] = [
  ['403', 'Goa'], ['605', 'Puducherry'], ['737', 'Sikkim'], ['744', 'Andaman and Nicobar Islands'], ['682', 'Kerala'], ['160', 'Chandigarh'],
  ['246', 'Uttarakhand'], ['247', 'Uttarakhand'], ['248', 'Uttarakhand'], ['249', 'Uttarakhand'], ['262', 'Uttarakhand'], ['263', 'Uttarakhand'],
  ['190', 'Jammu and Kashmir'], ['191', 'Jammu and Kashmir'], ['192', 'Jammu and Kashmir'], ['193', 'Jammu and Kashmir'], ['194', 'Ladakh'],
  ['790', 'Arunachal Pradesh'], ['791', 'Arunachal Pradesh'], ['792', 'Arunachal Pradesh'], ['793', 'Meghalaya'], ['794', 'Meghalaya'], ['795', 'Manipur'], ['796', 'Mizoram'], ['797', 'Nagaland'], ['798', 'Nagaland'], ['799', 'Tripura'],
  ['814', 'Jharkhand'], ['815', 'Jharkhand'], ['816', 'Jharkhand'], ['822', 'Jharkhand'], ['825', 'Jharkhand'], ['826', 'Jharkhand'], ['827', 'Jharkhand'], ['828', 'Jharkhand'], ['829', 'Jharkhand'], ['831', 'Jharkhand'], ['832', 'Jharkhand'], ['833', 'Jharkhand'], ['834', 'Jharkhand'], ['835', 'Jharkhand'],
];
const PIN2: [number, number, string][] = [
  [11, 11, 'Delhi'], [12, 13, 'Haryana'], [14, 16, 'Punjab'], [17, 17, 'Himachal Pradesh'], [18, 19, 'Jammu and Kashmir'], [20, 28, 'Uttar Pradesh'],
  [30, 34, 'Rajasthan'], [36, 39, 'Gujarat'], [40, 44, 'Maharashtra'], [45, 48, 'Madhya Pradesh'], [49, 49, 'Chhattisgarh'], [50, 50, 'Telangana'],
  [51, 53, 'Andhra Pradesh'], [56, 59, 'Karnataka'], [60, 66, 'Tamil Nadu'], [67, 69, 'Kerala'], [70, 74, 'West Bengal'], [75, 77, 'Odisha'],
  [78, 78, 'Assam'], [79, 79, 'Assam'], [80, 85, 'Bihar'],
];
export function pinCheck(raw: string): { ok: boolean; message: string; state?: string } {
  const p = raw.replace(/\s/g, '');
  if (!p) return { ok: false, message: '' };
  if (!/^[1-9]\d{5}$/.test(p)) return { ok: false, message: 'A PIN code has 6 digits and does not start with 0.' };
  const s3 = PIN3.find(([k]) => p.startsWith(k))?.[1];
  const n = Number(p.slice(0, 2));
  const state = s3 || PIN2.find(([a, b]) => n >= a && n <= b)?.[2];
  return state ? { ok: true, message: `Usually in ${state}.`, state } : { ok: true, message: 'Well-formed PIN.' };
}
export function udyamCheck(raw: string) {
  const u = raw.trim().toUpperCase();
  if (!u) return { ok: false, message: '' };
  return /^UDYAM-[A-Z]{2}-\d{2}-\d{7}$/.test(u) ? { ok: true, message: 'Well-formed Udyam number.' } : { ok: false, message: 'Looks like UDYAM-TS-02-0012345.' };
}
export function fssaiCheck(raw: string) {
  const f = raw.replace(/\s/g, '');
  if (!f) return { ok: false, message: '' };
  return /^[12]\d{13}$/.test(f) ? { ok: true, message: 'Well-formed 14-digit FSSAI number.' } : { ok: false, message: 'An FSSAI number has 14 digits.' };
}
export function cinCheck(raw: string, kind: 'company' | 'llp') {
  const c = raw.trim().toUpperCase();
  if (!c) return { ok: false, message: '' };
  if (kind === 'llp') return /^[A-Z]{3}-\d{4}$/.test(c) ? { ok: true, message: 'Well-formed LLPIN.' } : { ok: false, message: 'An LLPIN looks like AAB-1234.' };
  return /^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$/.test(c) ? { ok: true, message: 'Well-formed CIN.' } : { ok: false, message: 'A CIN has 21 characters, like U15400TG2015PTC099999.' };
}
/** Never accept an Aadhaar-like 12-digit number in any free-text field. */
export const looksLikeAadhaar = (s: string) => /(^|\D)\d{4}\s?\d{4}\s?\d{4}(\D|$)/.test(s);

export function ageText(ts?: string | null): string {
  if (!ts) return '';
  const s = Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000));
  if (Number.isNaN(s)) return '';
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
}

export function counterpartyOf(r: TnRelationship, myBid: string): { bid: string; name: string; role: TnRole } {
  const iAmBuyer = r.buyer_bid === myBid || (r.seller_bid !== myBid && !r.buyer_bid);
  const role: TnRole = iAmBuyer ? 'seller' : 'buyer';
  const bid = iAmBuyer ? r.seller_bid : r.buyer_bid;
  const name = r.counterparty?.display_name || (iAmBuyer ? r.seller_display_name || r.seller_name : r.buyer_display_name || r.buyer_name) || r.contact_masked || 'Invited business';
  return { bid, name, role };
}

// ---------------------------------------------------------------- supplier discovery and listings

export const LISTING_CATEGORIES = ['staples', 'rice', 'edible oil', 'packaged foods', 'personal care', 'cleaning', 'dry fruits', 'spices', 'beverages', 'dairy', 'snacks', 'fmcg'];
export const SORT_NOTE = 'Sorted by delivery area and verification status, not by price or quality';

export async function tnDiscover(q: TnDiscoverQuery): Promise<TnDiscoverResponse> {
  if (MOCK) return m(() => mock.mockTnDiscover(q), 450);
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  return req('GET', `/tn/discover?${p.toString()}`);
}
export async function tnConnect(body: { from_bid: string; to_bid: string; categories: string[]; message?: string }): Promise<TnConnectResponse> {
  if (MOCK) return m(() => mock.mockTnConnect(body), 600);
  return req('POST', '/tn/connect', { body });
}
export async function tnPutListing(bid: string, body: { version: number; listed: boolean; categories: string[]; service_area: Pick<TnServiceArea, 'kind' | 'districts' | 'states'>; min_order_paise?: number | null; notes?: string | null }): Promise<TnListingSaved> {
  if (MOCK) return m(() => mock.mockTnPutListing(bid, body), 500);
  return req('PUT', `/tn/businesses/${encodeURIComponent(bid)}/listing`, { body });
}
let areasCache: TnAreas | null = null;
export async function tnAreas(): Promise<TnAreas> {
  if (areasCache) return areasCache;
  areasCache = MOCK ? await m(() => mock.mockTnAreas(), 150) : await req<TnAreas>('GET', '/tn/areas');
  return areasCache;
}

/** "HYDERABAD" -> "Hyderabad"; "ANDHRA PRADESH" -> "Andhra Pradesh". */
export function titleCase(s?: string | null): string {
  return (s || '').toLowerCase().replace(/(^|[\s\-(/])([a-z])/g, (_, a: string, b: string) => a + b.toUpperCase()).replace(/\bAnd\b/g, 'and');
}
export function areaLabel(a?: Pick<TnServiceArea, 'kind' | 'districts' | 'states'> | null): string {
  if (!a) return 'Delivery area not set';
  if (a.kind === 'pan_india') return 'Delivers across India';
  if (a.kind === 'state') return `Delivers across ${a.states.map(titleCase).join(', ') || 'a state'}`;
  return `Delivers in ${a.districts.map(titleCase).join(', ') || 'a district'}`;
}
export const CONNECTION_WORD: Record<string, string> = { none: 'Request to connect', requested: 'Requested', connected: 'Connected', declined: 'Declined' };
export const emptyListing = (): TnListing => ({ listed: false, categories: [], service_area: { kind: 'district', districts: [], states: [] }, min_order_paise: null, notes: '' });
