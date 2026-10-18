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
