# Sauda: Roadmap, Dependencies and Residual Risk

Baseline commit: `56927f7`. Issues are tracked in [ISSUE_REGISTER.md](ISSUE_REGISTER.md).

## 1. Prototype versus production-ready: what the evidence supports

| Capability | Prototype evidence (today) | What production-ready would require |
|---|---|---|
| Deterministic policy gate (R1–R12, fails closed) | 20 unit tests. Live chains show offer, cart, and pre/post-confirmation decisions. | Property-based tests over money fields (SAUDA-001). Formal rule spec. Independent review. Versioned rule set recorded in each decision. |
| KMS-signed mandates | Live key v1 P-256. `/pubkey` is public. `signature_valid` shown. | Owner-held key or passkey co-signature (SAUDA-027). Key rotation with per-version verification. HSM protection level. Audit-log alerts. |
| Hash-chained ledger | `/verify` gives `chain_ok` on live chains. Tamper demo works. | Signed metadata and head anchor (SAUDA-010). External anchoring (periodic signed checkpoints to a WORM bucket or transparency log). Retention policy. |
| Guard (Model Armor + regex) | Fails closed inbound. The hostile supplier is blocked and quarantined in live runs. | Measured precision and recall on a multilingual red-team corpus. Outbound fail-closed (SAUDA-015). Template tuning. Probabilistic by nature, and never sole control. |
| Payee lock | Registry-sourced payee plus R8. | Registry in a separate trust domain (SAUDA-026). Payout verified by penny-drop or VPA name match. Change workflow with cooling-off and dual control. |
| Owner authentication | Firebase Google sign-in, ID token verified per request. | Per-shop ownership claim and onboarding. Phone OTP for kirana owners. Session binding. Per-user negotiations (SAUDA-002). |
| Payment | Real UPI deep link and QR for a demo amount. Owner-entered UTR, **not bank-verified**. | PSP or AP2 settlement with webhook-confirmed status. Reconciliation. Refunds on cancel. No "settled" without PSP evidence (SAUDA-003/004). |
| Suppliers | Three simulated A2A agents with published strategies, one hostile. | Real supplier onboarding (section 3.4). |
| Savings metric | Against opening quotes (labelled). | Against the shop's purchase history or a market index. Counted only on delivered orders (SAUDA-011). |
| Reliability | One instance, in-memory sessions. A cold negotiation can exceed 60 s. | Section 3.1–3.3. SLOs. |
| Tests | 248 automated tests (gate rules, mandates, ledger v2 + head, API auth and isolation, confirm concurrency, payments, sessions, voice, scenarios). Live end-to-end scripts; no frontend or accessibility automation yet. | [TEST_PLAN.md](TEST_PLAN.md) fully implemented in CI. |

## 2. Dependencies

| Dependency | Used for | Risk | Mitigation |
|---|---|---|---|
| Gemini 3.5 Flash (Vertex AI, asia-south1) | Chat, request parse, quote-parse fallback, supplier phrasing | Latency, quota, model drift, truncated JSON (fixed in `320b7f0`) | Deterministic fallback router (`chat.py:79-94`). Keyword parser fallback. Pin the model version. |
| ADK + `InMemorySessionService` | Agent turns, confirmation pause and resume | Sessions lost on restart | Firestore session store (3.1). Direct `place_order` fallback is already present. |
| A2A (JSON-RPC v0.3 compat) | Buyer to supplier | Spec churn (v0.3 to v1) | Thin client in `a2a.py` handles both part shapes. |
| Model Armor (us-central1 regional endpoint) | Guard | Cross-region latency (5 s timeout), outage fails closed (blocks all suppliers) | Regional template when available. Alert on `source=timeout` rate. |
| Cloud KMS | Mandate and ledger signatures | Every ledger append is a KMS call (latency, quota) | Batch or anchor signatures. Local cache of the public key (present). |
| Firestore | All state | Non-transactional service code (SAUDA-007) | Transactions on state transitions. |
| Firebase Auth / Hosting | Sign-in, front door | Config drift | n/a |
| data.gov.in mandi API | Reference ceilings | **403 from cloud IPs**, so the scheduler is paused | Fixed-egress proxy, or manual CSV ingest. Staleness warning. Publish `ceiling_as_of`. |
| Open Food Facts | Product master | Data quality (MRP read from pack photos) | Manual verification of the catalogue in use. |

## 3. Future work

### 3.1 Durable negotiation state
- Replace `InMemorySessionService` (`agent/root.py:31`) with a Firestore-backed ADK `SessionService` (sessions, events, state), or Vertex AI Agent Engine sessions.
- Persist the pending `adk_request_confirmation` function-call id with the confirmation (already stored) so that resume works across instances and restarts.
- Make every state transition transactional (`requested → approving → approved/denied`, `cart_ready → awaiting_confirmation → confirmed → ordered`).
- Acceptance: kill the instance between confirmation request and approval, and the approval still produces exactly one PO per supplier.

### 3.2 Multiple negotiations per shop, multiple users
- Replace `shops.active_negotiation_id` with `negotiations where shop_id==X and owner_uid==U and status in active`.
- Use per-request SSE emitters (SAUDA-002).
- Allow a configurable number of concurrent negotiations per shop, with a budget reservation so that two mandates cannot jointly exceed a shop-level monthly cap.
- Allow `max-instances > 1` once state is in Firestore and the rate limiter is shared (Firestore or Memorystore).

### 3.3 Cold start: 5 s or less
- Measure today: buyer `min=1` (warm); suppliers `min=0`.
- Lazy-import ADK, google-genai and the firebase admin SDK on the first request. Slim the Python image (separate images for buyer and supplier). Enable startup CPU boost.
- Set supplier `min-instances=1` during judging, or prewarm with a `/health/deep` fan-out.
- Lower the A2A timeout to about 8 s and run the card fetch in parallel.
- Target: a new revision serves `/health` in 5 s or less, and a cold negotiation completes in 30 s or less.

### 3.4 Real supplier onboarding over A2A
- **Identity:** a verified business identity (GSTIN, FSSAI licence) bound to the agent card. The card is signed by the supplier's key and pinned in the registry (today only a fingerprint is pinned). Mutual auth: a supplier-issued workload identity or mTLS instead of shared Google IAM.
- **Catalogue integrity:** signed catalogue snapshots (GTIN, pack, MRP) with versioning. Quotes reference a catalogue version. Detect bait pricing against the reference (R7 with real refs, SAUDA-018).
- **Payout verification:** VPA name match and penny-drop through the PSP before allowlisting. A payout change goes through an out-of-band confirmation, a cooling-off period and dual control. Payout changes are never accepted over A2A.
- **Revocation:** the registry status is checked per message. Quarantine on guard or nonce failure (present). Revocation propagates to open mandates and payment mandates. A revoked supplier's pending payment mandates are invalidated.
- **Reputation:** delivery and quality history feeding the allocation.

### 3.5 ONDC
- Expose Sauda as an ONDC buyer app (retail B2B domain): search, select, init, confirm through a gateway. ONDC seller apps become supplier adapters behind the same gate.
- Map ONDC quotes to the Quote schema. Map ONDC settlement to the Payment Mandate. Keep the gate as the commit authority.

### 3.6 Bill and shelf photos
- Bill OCR to purchase history (last-paid prices, so ceilings become `last_paid × 1.10`; demand baseline). Gemini vision with structured output. The owner confirms each extracted line, and photos are retained under explicit consent only.
- Shelf photo to a stock estimate (count facings), feeding suggested quantities as suggestions, never silent uplift (contract item 1).

### 3.7 Pooled buying
- Several shops pool demand for an RFQ. The pooled mandate is a composition of individual signed mandates, and each shop's allocation is gated against its own mandate. Delivery is split, and payment is per shop.
- Requires 3.2 and shop-level privacy, so shops do not see each other's quantities.

### 3.8 Real settlement through AP2 or a PSP
- Replace the UPI deep link plus owner-entered UTR with AP2 payment mandates presented to a PSP (UPI Collect or Autopay, or UPI Reserve Pay / single-block-multiple-debit for advances).
- PSP webhooks drive `payment_status` (`authorised`, `captured`, `refunded`). Reconcile against the order.
- Escrow-style advance release on delivery confirmation. Refunds on cancel within cooling-off.
- Delivery and fulfilment tracking (GRN, POD photo) before final payment. Not built today.

### 3.9 Other
- Agent identity on Agent Engine.
- Supplier credit terms in mandates.
- Multilingual voice (hi-IN, te-IN), claimed only after end-to-end tests.
- Consented FMCG demand insights.
- Security headers and CSP (SAUDA-029).
- Structured logs with correlation ids, plus a deep health check (SAUDA-024).

## 4. Residual risks (after the 18:00 build, assuming P0/P1 fixes land)

| Risk | Likelihood | Impact | Notes |
|---|---|---|---|
| Guard false negatives (novel or multilingual injection) | Medium | Low–Medium | The gate bounds money. Text could still mislead the owner in chat summaries. |
| Model-derived numbers in the parse fallback | Low | Medium | Bounded by the ceiling and budget (SAUDA-014). |
| Buyer runtime compromise | Low | High | Can sign anything, rewrite the registry and the ledger. Single trust domain (SAUDA-026/027). |
| UTR not bank-verified | Certain (by design) | Medium | Must stay labelled "claimed". |
| Shared demo shop | High during judging | Medium | Unless SAUDA-002 is fixed, recommend one judge at a time, or a per-judge shop. |
| Stale reference prices | Medium (refresh paused) | Low–Medium | `ceiling_as_of` shown. 7-day freshness window. |
| Single instance / cold suppliers | Medium | Medium | A demo-time warm-up is recommended. |
| Real payee VPA public in git or `/events` | High if pushed publicly | Low–Medium (privacy) | Scrub before pushing (SAUDA-020). |
| Ledger metadata and truncation | Low | Medium | Until v2 events (SAUDA-010). |
