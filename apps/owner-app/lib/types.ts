// Shapes mirror the buyer-agent API contracts, data model and SSE event protocol.
// Money is always integer paise. GTIN is the product key.

export type Paise = number;

export interface ProductRef { gtin: string; name: string; brand?: string | null; pack_size?: string | null }

export interface Product extends ProductRef {
  category?: string | null;
  mrp_paise?: Paise | null;
  ceiling_paise: Paise;
  ceiling_source: string;
  ceiling_as_of?: string | null;
}

export interface Clarification { owner_words: string; question: string; options: ProductRef[]; gtin?: string }

export interface DraftLine {
  gtin: string;
  name: string;
  qty: number;
  /** contract 1: "owner" = the owner said this number; "inferred" = Sauda's default */
  qty_source?: 'owner' | 'inferred';
  requested_qty?: number | null;
  suggested_qty?: number | null;
  suggestion_reason?: string | null;
  confidence?: 'high' | 'low';
  owner_words?: string;
  alternatives?: ProductRef[];
  brand?: string | null;
  pack_size?: string | null;
  forecast_qty?: number;
  last_paid_paise: Paise | null;
  ceiling_paise: Paise;
  ceiling_source: string;
  ceiling_as_of?: string;
  reason: string;
  category?: string;
}

export interface Draft {
  draft_id?: string;
  shop_id: string;
  festival?: string | null;
  lines: DraftLine[];
  budget_paise?: Paise;
  deliver_by?: string;
  allowed_supplier_ids?: string[];
  assumptions?: string[];
  stated_budget_paise?: Paise | null;
  suggested_budget_paise?: Paise | null;
  clarifications?: Clarification[];
  budget_estimate_paise?: Paise | null;
  budget_notes?: string[];
  unmatched?: (string | { owner_words?: string; text?: string; reason?: string })[];
}

export interface IntentMandateBody {
  kind: 'intent';
  shop_id: string;
  budget_paise: Paise;
  allowed_supplier_ids: string[];
  lines: { gtin: string; qty: number; ceiling_paise: Paise; ceiling_source: string }[];
  max_advance_pct: number;
  deliver_by: string;
  autonomy_tier: number;
  expires_at: string;
  nonce: string;
}

export interface SignMandateResponse {
  mandate_id: string;
  body_hash: string;
  signature: string;
  kms_key_version: string | number;
}

export type MandateStatus = 'draft' | 'active' | 'consumed' | 'revoked' | 'expired';

export interface Mandate {
  mandate_id: string;
  kind: 'intent' | 'cart' | 'payment';
  shop_id: string;
  parent_mandate_id?: string | null;
  body: Record<string, unknown>;
  body_hash: string;
  signature: string;
  kms_key_version: string | number;
  status: MandateStatus;
  created_at: string;
  expires_at: string;
}

export type RuleVerdict = 'PASS' | 'ALLOW' | 'CONFIRM' | 'DENY';

export interface GateRuleResult {
  rule: string; // R1..R12
  verdict: RuleVerdict;
  reason_code?: string | null;
  reason?: string | null; // backend alias of reason_code
  detail?: string;
  check?: string;
}

export interface GateReport {
  action: string;
  mandate_id?: string;
  verdict: RuleVerdict;
  results: GateRuleResult[];
}

export interface CartLine {
  gtin: string;
  name: string;
  qty: number;
  unit_price_paise: Paise;
  opening_price_paise?: Paise;
  ceiling_paise: Paise;
  ceiling_source: string;
  ceiling_as_of?: string;
}

export interface Allocation {
  supplier_id: string;
  supplier_name?: string;
  lines: CartLine[];
  subtotal_paise: Paise;
  delivery_days: number;
  advance_pct: number;
  payee_vpa?: string | null;
  payout_vpa_masked?: string | null;
}

export interface Confirmation {
  confirmation_id: string;
  negotiation_id: string;
  cart_draft_id: string;
  status: 'requested' | 'approved' | 'declined' | 'expired';
  expires_at?: string;
  cart: {
    allocations: Allocation[];
    total_paise: Paise;
    savings_paise: Paise;
    savings_pct?: number;
    budget_paise?: Paise;
    blocked_suppliers?: { supplier_id: string; reason_codes: string[] }[];
    opening_cost_paise?: Paise;
    why?: { gtin: string; supplier_id: string; text: string }[];
    dropped_lines?: { gtin: string; name: string; qty: number; reason: string }[];
  };
  intent_mandate?: Mandate | null;
  gate_report: GateReport;
}

export interface ConfirmResponse {
  status: string;
  order_ids?: string[];
  payment_mandate_id?: string;
}

export interface Order {
  order_id: string;
  negotiation_id?: string;
  supplier_id: string;
  supplier_name?: string;
  total_paise: Paise;
  status: 'placed' | 'cooling_off' | 'settled' | 'cancelled' | string;
  /** contract 5: issued | claimed | mismatch (legacy "settled" is read as "claimed") */
  payment_status?: PaymentStatus | 'settled' | 'cancelled' | null;
  utr?: string | null;
  created_at?: string;
  po_ack?: { status?: string; [k: string]: unknown } | null;
  po_error?: string | null;
  payout_vpa_masked?: string | null;
  demo_amount?: boolean;
  order_total_paise?: Paise;
  po_status?: string | null;
  lines?: CartLine[];
  payment_mandate?: {
    mandate_id: string;
    amount_paise: Paise;
    payee_vpa: string;
    payee_name?: string;
    upi_link?: string;
    cooling_off_until?: string;
    status: 'issued' | 'settled' | 'claimed' | 'mismatch' | 'cancelled' | string;
    order_total_paise?: Paise;
    payee_vpa_masked?: string | null;
    payout_vpa_masked?: string | null;
    demo_amount?: boolean;
    body_hash?: string;
  } | null;
}

export type PaymentStatus = 'issued' | 'claimed' | 'mismatch';

export interface OverviewOrder {
  order_id: string;
  negotiation_id: string;
  supplier_id: string;
  supplier_name?: string | null;
  total_paise: Paise;
  status: string;
  payment_status?: string | null;
  po_ack?: string | { status?: string } | null;
  created_at: string;
}

export interface Overview {
  shop: { shop_id: string; name: string; kill_switch?: boolean | null };
  active_negotiation: { negotiation_id: string; status: string; round?: number | null; intent_mandate_id?: string | null; cart_draft_id?: string | null; started_at?: string | null } | null;
  pending_confirmation_id: string | null;
  recent_orders: OverviewOrder[];
}

export interface AttackScenario { id: string; title: string; attempt: string; layer: string; expected: string; simulated?: boolean | string }
export interface ScenarioCheck { layer: 'guard' | 'gate' | 'ledger' | string; rule: string; verdict: string; reason?: string | null; detail?: unknown }
export interface ScenarioResult {
  id: string;
  title: string;
  attempted_action: string;
  checks: ScenarioCheck[];
  outcome: 'blocked' | 'allowed' | 'needs_approval' | string;
  explanation: string;
  evidence: { ledger_seq?: number; negotiation_id?: string; [k: string]: unknown };
}

export interface ProofResponse {
  status: 'claimed' | 'settled' | 'invalid' | 'mismatch' | string;
  problems?: string[];
  bank_verified?: boolean;
  note?: string;
  utr?: string;
  reason?: string;
}

export interface Metrics {
  rupees_saved: number; // treated as paise (money is in paise everywhere)
  savings_pct: number;
  ceiling_compliance: number; // 0..1 or 0..100
  time_saved_min: number;
  attacks_blocked: number;
  orders?: number;
  last_negotiation_id?: string | null;
  baseline_label?: string;
  realised_savings_paise?: number;
  realised_savings_pct?: number;
  realised_basis?: string;
  supplier_messages_blocked?: number;
  attack_box_blocked?: number;
  time_saved_assumption_min_per_call?: number;
}

export interface VerifyEvent { seq: number; type: string; hash_ok: boolean; link_ok: boolean; sig_ok: boolean; sig_version?: number; signature_scope?: string }
export interface VerifyResponse { events: VerifyEvent[]; chain_ok: boolean; first_broken_seq?: number | null; head_ok?: boolean | null; head_problem?: string | null }

export interface LedgerEvent {
  seq: number;
  ts: string;
  negotiation_id: string;
  type: string;
  actor: string;
  payload: Record<string, unknown>;
  payload_hash: string;
  prev_hash: string;
  signature: string;
}

export interface GuardVerdict {
  blocked: boolean;
  match_state?: string;
  filters?: string[];
  source?: string;
  categories?: string[];
  [k: string]: unknown;
}

export interface AttackResponse {
  guard_verdict: GuardVerdict | string;
  gate_report: GateReport;
  ledger_seq: number;
}

// SM-5 SSE events
export type SseEvent =
  | { event: 'agent.text'; data: { text: string } }
  | { event: 'agent.tool'; data: { name: string; status: string; result?: unknown } }
  | { event: 'draft'; data: Draft | { draft: Draft } }
  | { event: 'gate.report'; data: GateReport & { supplier_id?: string; round?: number; reasons?: string[] } }
  | { event: 'guard.verdict'; data: { supplier_id: string; round?: number; blocked: boolean; categories?: string[]; source?: string } }
  | { event: 'offer'; data: OfferEvent }
  | { event: 'confirmation.request'; data: { confirmation_id: string; cart_draft_id: string } }
  | { event: 'done'; data: { negotiation_id: string; status: string } }
  | { event: 'error'; data: { code: string; message: string } };

export interface OfferEvent {
  supplier_id: string;
  supplier_name?: string;
  round: number;
  direction?: string;
  lines: { gtin: string; name?: string; unit_price_paise?: Paise; qty?: number }[];
  delivery_days?: number | null;
  advance_pct?: number | null;
  guard_blocked?: boolean;
  gate_verdict?: string;
  reasons?: string[];
  payout_vpa?: string | null;
}

// ---------------------------------------------------------------- restock sessions (CONTRACT2)
export type SessionStatus = 'draft' | 'awaiting_review' | 'negotiating' | 'awaiting_approval' | 'ordered' | 'completed' | 'cancelled' | 'failed';

export interface TurnOp { op: string; gtin?: string; to?: string; qty?: number; delta?: number; paise?: number; name?: string; [k: string]: unknown }

export interface SessionTurn {
  turn_id: string;
  client_turn_id?: string | null;
  role: 'owner' | 'sauda';
  text: string;
  source?: 'voice' | 'text' | null;
  ts: string;
  ops?: TurnOp[];
  latency_ms?: number | Record<string, number> | null;
}

export interface SessionDraft {
  lines: DraftLine[];
  stated_budget_paise?: Paise | null;
  budget_estimate_paise?: Paise | null;
  clarifications?: Clarification[];
  unmatched?: Draft['unmatched'];
  festival?: string | null;
  assumptions?: string[];
  deliver_by?: string;
  allowed_supplier_ids?: string[];
  budget_notes?: string[];
}

export interface RestockSession {
  sid: string;
  shop_id: string;
  owner_uid?: string;
  title: string;
  status: SessionStatus;
  created_at: string;
  updated_at: string;
  version: number;
  turns: SessionTurn[];
  draft: SessionDraft;
  negotiation_id?: string | null;
  intent_mandate_id?: string | null;
  confirmation_id?: string | null;
  order_ids?: string[];
  error?: { code: string; message: string } | null;
  resumable: boolean;
}

export interface SessionSummary {
  sid: string;
  title: string;
  status: SessionStatus;
  updated_at: string;
  line_count: number;
  budget_paise?: Paise | null;
  total_paise?: Paise | null;
  needs_attention: boolean;
  resumable: boolean;
}

export type ClarOption = ProductRef | string;
export interface TurnClarification { question: string; options: ClarOption[]; owner_words?: string; gtin?: string }

export interface TurnResponse {
  session: RestockSession;
  reply: string;
  ops: TurnOp[];
  clarification: TurnClarification | null;
  latency_ms?: { extract?: number; apply?: number; total?: number } | null;
}

export interface PrepareResponse {
  session: RestockSession;
  negotiation_id: string;
  suggested_mandate?: Partial<{ budget_paise: Paise; allowed_supplier_ids: string[]; deliver_by: string; max_advance_pct: number; expires_at: string }> | null;
}

export interface NegotiationView {
  negotiation: { negotiation_id: string; status: string; round?: number | null; intent_mandate_id?: string | null; cart_draft_id?: string | null; confirmation_id?: string | null; started_at?: string | null; [k: string]: unknown };
  cart?: { total_paise?: Paise; [k: string]: unknown } | null;
  orders?: OverviewOrder[];
}

// ======================================================================
// Trust Network (business verification + supplier network). Shapes follow
// CONTRACT_TN "API" exactly; optional extras are tolerated, never required.
// ======================================================================
export type TnRole = 'buyer' | 'seller';
export type TnDim =
  | 'identity' | 'registration' | 'address' | 'operational' | 'representative' | 'product_compliance'
  | 'distribution_authority' | 'trading_references' | 'payment_details' | 'operational_capability';
export type TnCheckStatus =
  | 'verified' | 'partially_verified' | 'self_declared' | 'pending' | 'inconclusive' | 'stale' | 'conflict' | 'failed' | 'not_applicable';
export type TnSourceKind =
  | 'official_registry' | 'authorised_provider' | 'uploaded_evidence' | 'human_review' | 'self_declared'
  | 'preliminary_validation' | 'simulated_fixture' | 'device_signal';
export type TnCategory =
  | 'identity_confirmed' | 'evidence_reviewed' | 'ready_for_counterparty_review' | 'additional_review_required' | 'verification_unsuccessful';
export type TnRelState = 'requested' | 'invited' | 'accepted' | 'onboarding' | 'under_review' | 'approved_for_trading' | 'declined' | 'paused';
export type TnAuthorityStatus = 'unknown' | 'self_declared' | 'pending' | 'verified' | 'rejected';

export interface TnAddress { line: string; city: string; state: string; pin: string }
export interface TnGeo { lat: number; lng: number; accuracy_m?: number | null; captured_at?: string | null; consent: boolean }
export interface TnBusiness {
  bid: string;
  roles: TnRole[];
  display_name: string;
  legal_name?: string | null;
  constitution?: string | null;
  category?: string | null;
  products: string[];
  gstin?: string | null;
  udyam?: string | null;
  fssai?: string | null;
  cin_llpin?: string | null;
  address: TnAddress;
  geo?: TnGeo | null;
  contact?: { phone_masked?: string | null; email_masked?: string | null };
  representative: { name: string; role: string; authority_status: TnAuthorityStatus };
  brand_claims?: string[];
  owner_uid?: string;
  members?: string[];
  is_fixture?: boolean;
  /** A personal sample shop ("Try with a sample shop"): simulated data, visible only to its owner. */
  sandbox?: boolean;
  fixture_label?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  version: number;
}
export interface TnFieldCompare { field: string; declared?: string | null; observed?: string | null; match: boolean | null }
export interface TnCheck {
  check_id: string;
  business_id: string;
  case_id: string;
  dim: TnDim;
  check_type: string;
  source_kind: TnSourceKind;
  source_name: string;
  source_url?: string | null;
  status: TnCheckStatus;
  summary: string;
  fields: TnFieldCompare[];
  evidence_ids: string[];
  checked_at: string;
  expires_at?: string | null;
  provider_ref?: string | null;
  available?: boolean;
  reviewer?: { uid_hash: string; decision: string; reason: string; at: string } | null;
}
export interface TnDimensionSummary { dim: TnDim; status: TnCheckStatus; source_kind?: TnSourceKind | null; summary: string; checked_at?: string | null }
export interface TnSummary {
  category: TnCategory;
  category_label?: string;
  dimensions: TnDimensionSummary[];
  outstanding: string[];
  limitations: string[];
  next_step: string;
  review_reasons?: string[];
}
export interface TnReadiness { tier: string; ready: boolean; missing: string[]; requires_human_review?: boolean; note?: string }
export type TnBusinessMine = TnBusiness & { summary?: TnSummary | null };
/** GET /tn/businesses/{bid}: full record for members/reviewers. Checks may arrive alongside. */
export interface TnBusinessFull { business: TnBusiness; checks: TnCheck[]; summary?: TnSummary | null }

export interface TnCase { case_id: string; bid: string; purpose: string; status: 'open' | 'in_review' | 'completed' }
export interface TnVerifyResponse { case: TnCase; checks: TnCheck[] }
export type TnEvidenceType = 'gst_certificate' | 'udyam_certificate' | 'fssai_licence' | 'authorisation_letter' | 'storefront_photo' | 'brand_authorisation' | 'partnership_deed' | 'other';
export interface TnEvidence { eid: string; bid: string; type: TnEvidenceType | string; mime?: string; size?: number; sha256?: string; guard?: { blocked: boolean; categories?: string[] } }
export interface TnEvidenceResponse { evidence: TnEvidence; checks: TnCheck[] }

/** GET /tn/businesses/{bid}/profile: the REDACTED counterparty view. No documents, no customer/supplier lists. */
export interface TnProfile {
  bid: string;
  display_name: string;
  legal_name?: string | null;
  roles: TnRole[];
  constitution?: string | null;
  category?: string | null;
  products: string[];
  address: { city?: string; state?: string; pin?: string };
  representative?: { name?: string; role?: string; authority_status?: TnAuthorityStatus };
  is_fixture?: boolean;
  summary: TnSummary;
  checks?: Pick<TnCheck, 'check_id' | 'dim' | 'source_kind' | 'source_name' | 'status' | 'summary' | 'checked_at'>[];
  pending_review?: string[];
  readiness?: TnReadiness[] | Record<string, TnReadiness> | null;
  outstanding_count?: number;
  gstin_masked?: string | null;
}

export interface TnRelationship {
  rid: string;
  buyer_bid: string;
  seller_bid: string;
  initiated_by_bid: string;
  state: TnRelState;
  categories: string[];
  provenance: 'invitation' | 'self_declared' | 'confirmed_trade' | 'validated_reference' | 'discovery_request';
  request?: TnConnectRequest | null;
  shared_fields?: string[];
  requirements?: Record<string, unknown>;
  history?: { state?: string; action?: string; reason?: string; by_bid?: string; at: string }[];
  // Display extras (optional): names of the two sides and a masked contact for open invitations.
  buyer_name?: string | null;
  seller_name?: string | null;
  buyer_display_name?: string | null;
  seller_display_name?: string | null;
  counterparty?: { bid?: string; display_name?: string } | null;
  contact_masked?: string | null;
  readiness?: TnReadiness | Record<string, TnReadiness> | null;
  version?: number;
  approved_tiers?: string[];
  created_at?: string | null;
  updated_at?: string | null;
}
export interface TnInvitation {
  iid: string;
  from_bid: string;
  role_invited: TnRole;
  contact_masked: string;
  status: 'sent' | 'accepted' | 'expired' | 'revoked';
  expires_at?: string | null;
  rid?: string | null;
  categories?: string[];
  display_name?: string | null;
  display_name_hint?: string | null;
  created_at?: string | null;
}
/** POST /tn/invitations: the share token is returned ONCE. */
export interface TnInvitationCreated { invitation: TnInvitation; token: string | null; share_url?: string | null; duplicate?: boolean }
export interface TnInvitationPublic { from_display_name: string; role_invited: TnRole; status?: string; expires_at?: string | null }

export type TnReviewStatus = 'open' | 'needs_evidence' | 'approved' | 'rejected' | 'escalated';
export type TnReviewAction = 'approve_identity' | 'approve_claim' | 'reject_claim' | 'request_evidence' | 'escalate';
export interface TnReviewDecision { action: TnReviewAction | string; scope: string; reason: string; reviewer_hash?: string; at: string; demo?: boolean; label?: string }
export interface TnReviewTask {
  tid: string;
  bid: string;
  case_id: string;
  reasons: string[];
  status: TnReviewStatus;
  decisions: TnReviewDecision[];
  created_at: string;
  // Display extras (optional)
  display_name?: string | null;
  roles?: TnRole[];
  is_fixture?: boolean;
  sandbox?: boolean;
  demo?: boolean;
}
export interface TnReviewTaskDetail {
  task: TnReviewTask;
  business?: TnBusiness | null;
  checks: TnCheck[];
  summary?: TnSummary | null;
  audit?: { action: string; reason?: string; actor?: string; at: string }[];
  recommended_action?: string | null;
  manual_checks?: { check_id?: string; title: string; source_url: string; fields: string[] }[];
}
export interface TnLedgerEvent { seq?: number; type?: string; event_type?: string; ts?: string; at?: string; created_at?: string; payload?: Record<string, unknown>; actor?: string; [k: string]: unknown }
export interface TnLedger { chain_id: string; events: TnLedgerEvent[]; verification?: { chain_ok?: boolean; ok?: boolean; [k: string]: unknown } | null }

// ---------------------------------------------------------------- supplier discovery and listings
export type TnAreaKind = 'district' | 'state' | 'pan_india';
export interface TnServiceArea { kind: TnAreaKind; districts: string[]; states: string[]; basis?: 'self_declared'; label?: string }
export interface TnListing {
  listed: boolean;
  categories: string[];
  service_area: TnServiceArea;
  min_order_paise?: number | null;
  notes?: string | null;
  updated_at?: string | null;
}
export type TnConnection = 'none' | 'requested' | 'connected' | 'declined';
export interface TnCardDim { dim: TnDim | string; label?: string; status: TnCheckStatus | string; source_kind?: TnSourceKind | string | null }
export interface TnDiscoverCard {
  bid: string;
  display_name: string;
  city?: string | null;
  district?: string | null;
  state?: string | null;
  categories: string[];
  service_area: TnServiceArea;
  min_order_paise?: number | null;
  notes?: string | null;
  delivers_to_viewer?: boolean;
  trust: { category: TnCategory | string; category_text: string; dims: TnCardDim[] };
  last_checked_at?: string | null;
  is_fixture: boolean;
  fixture_label?: string | null;
  connection: TnConnection;
  rid?: string | null;
}
export type TnDiscoverScope = 'district' | 'state' | 'india';
export interface TnDiscoverQuery { bid?: string; q?: string; category?: string; scope?: TnDiscoverScope; district?: string; state?: string; verified_only?: boolean; limit?: number; cursor?: string | null }
export interface TnDiscoverResponse {
  viewer: { bid: string; display_name?: string; district?: string | null; state?: string | null; pin?: string | null; sandbox?: boolean } | null;
  /** True when the viewer has no buying business: the results are read-only browsing. */
  viewer_needs_profile?: boolean;
  viewer_note?: string;
  scope: TnDiscoverScope;
  area: { district?: string | null; state?: string | null };
  verified_only: boolean;
  results: TnDiscoverCard[];
  next_cursor: string | null;
  sort_note: string;
  total?: number;
}
export interface TnAreas { states: { state: string; districts: string[] }[]; source?: string }
export interface TnConnectRequest { message?: string | null; message_blocked?: boolean; categories?: string[]; at?: string }
export interface TnConnectResponse { relationship: TnRelationship; duplicate: boolean; guard?: { blocked: boolean; categories?: string[] } }
export interface TnListingSaved { business: TnBusiness & { listing?: TnListing | null }; card?: TnDiscoverCard | null }
// The seller's opt-in directory listing (declaration merge keeps the base interface untouched).
export interface TnBusiness { listing?: TnListing | null }
