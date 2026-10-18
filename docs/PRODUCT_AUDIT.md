# Sauda: Product and Architecture Audit

Baseline: commit `56927f7` (18 Oct 2026). Auditor role: principal architect, AppSec and QA, read-only on code. Line references are `path:line` at `56927f7`. Issues are tracked in [ISSUE_REGISTER.md](ISSUE_REGISTER.md) as `SAUDA-xxx`. No secrets, tokens or payee UPI IDs are reproduced here.

## 1. Summary

Sauda is a working prototype of bounded agent autonomy. The design is sound:
- a deterministic 12-rule gate that fails closed;
- the payee always read from a registry;
- one side-effect tool behind owner confirmation;
- KMS-signed mandates;
- a hash-chained, signed ledger anyone can re-verify.

The weak points are around the core, not in it:
- **Multi-user state.** Everyone shares the demo shop: one emitter and one active negotiation per shop (SAUDA-002).
- **Payment-state honesty.** The proof check is circular and the result is labelled "settled" (SAUDA-003/004).
- **Non-transactional confirmation and ordering** (SAUDA-007).
- **Ledger signature scope** (SAUDA-010).
- **Unbounded supplier-supplied numbers** (SAUDA-001).
- **Inflated impact metrics** (SAUDA-011).

## 2. System map

| Component | Path | Runtime | Identity | Exposure |
|---|---|---|---|---|
| Owner app (Next.js 15, standalone) | `apps/owner-app` | Cloud Run `owner-app` (min 0, max 3) behind Firebase Hosting `saudaai.web.app` | `owner-app@` (no project roles) | Public (`allUsers` invoker) |
| Buyer agent (FastAPI + ADK, Gemini 3.5 Flash) | `apps/buyer-agent` | Cloud Run `buyer-agent` (min 1, max 1, timeout 600 s) | `buyer-agent@` | Public (`allUsers`); app-level auth |
| Supplier agents ×3 (A2A JSON-RPC, deterministic quote engine, Gemini phrasing) | `apps/supplier-agent`, `suppliers/*.json` | Cloud Run `supplier-metro`, `supplier-sharma`, `supplier-quickstock` (min 0, max 2) | `supplier@` | Private: `run.invoker` only for `buyer-agent@` |
| Trust package | `packages/sauda_trust`: `policy_gate`, `tool_broker`, `guard`, `mandates`, `kms`, `registry` | in buyer | n/a | n/a |
| Ledger package | `packages/sauda_ledger`: `events`, `verify` | in buyer | n/a | n/a |
| Data package | `packages/sauda_data`: products, price_refs, calendar, refresh | buyer + job | n/a | n/a |
| Price refresh | Cloud Run job `price-refresh` + Scheduler `price-refresh-daily` (**PAUSED**; data.gov.in returns 403 to cloud IPs) | job | `price-refresh@` | n/a |
| Firestore (Native) | rules `firestore.rules`: deny all client access | n/a | n/a | server SDK only |
| Cloud KMS | `keyRings/sauda/cryptoKeys/sauda-mandates` v1 `EC_SIGN_P256_SHA256` | n/a | `signerVerifier` + `publicKeyViewer`: `buyer-agent@` only | n/a |
| Model Armor | template `us-central1/templates/sauda-guard` | n/a | `modelarmor.user`: `buyer-agent@` | n/a |
| Secret Manager | `data-gov-in-api-key` (buyer, price-refresh), `demo-owner-token` (buyer; v2 enabled, v1 disabled) | n/a | n/a | n/a |

### 2.1 IAM (from `gcloud projects get-iam-policy` and `gcloud run services get-iam-policy`, 18 Oct 12:19 IST)

| Principal | Project roles | Least-privilege notes |
|---|---|---|
| `buyer-agent@` | aiplatform.user, cloudtrace.agent, datastore.user, firebaseauth.viewer, logging.logWriter, modelarmor.user. KMS key: signerVerifier, publicKeyViewer. Secrets: both. | `datastore.user` is project-wide, which includes writing `suppliers` (payee registry). See SAUDA-026. |
| `supplier@` | aiplatform.user, **datastore.viewer**, logging.logWriter | `datastore.viewer` is unused by supplier code. A hostile supplier can read all data (SAUDA-013). |
| `price-refresh@` | datastore.user. Secret: data-gov-in-api-key. Job: run.invoker. | It could be scoped to `price_refs` only. |
| `owner-app@` | none | Good. |
| `PROJECT_NUMBER-compute@` (default) | artifactregistry.writer, logging.logWriter, storage.objectViewer | Build identity. Acceptable for a hackathon. |
| `user:` project owner | owner | Single human admin. |
| Cloud Run invokers | `buyer-agent`, `owner-app`: allUsers. Suppliers: `buyer-agent@` only. | Matches design. |

### 2.2 Firestore collections and writers

| Collection | Doc id | Written by (code) | Read by |
|---|---|---|---|
| `shops` | shop id | buyer `store.update_shop` (`active_negotiation_id`, `attack_mandate_id`), `scripts/seed.py`, `reset_demo.py` | buyer |
| `products` | gtin | `scripts/seed.py` | buyer (cache 5 min, `store.py:57-80`) |
| `price_refs` | commodity key | `seed.py`, `sauda_data.refresh` (job) | buyer (cache 30 min, `demand.py:100-120`) |
| `negotiations` | `neg_<12hex>` | buyer `store.create_negotiation` / `update_negotiation` | buyer, judge routes |
| `offers` | `off_<12hex>` | buyer negotiator (`loop.py:178,227`) | buyer, `/events` |
| `cart_drafts` | `cart_<nid>` | buyer (`store.py:137-144`) | buyer |
| `confirmations` | `conf_<12hex>` | buyer `confirm.request/answer` | buyer |
| `orders` | `ord_<nid[-12:]>_<sid>` | buyer `orders.place`, `issue_payment`, `submit_proof`, `cancel` | buyer |
| `mandates` | `{intent,cart,payment}_<16hex>` | buyer `mandates.create` (`.create()`, so no overwrite) and `mark` | buyer |
| `suppliers` (registry) | supplier id | `scripts/register_suppliers.py`; buyer `quarantine` | buyer |
| `ledger_events` | `<nid>_<seq:06d>` | `sauda_ledger.append` (transaction + `create`) | buyer, judge routes |

The rules deny every client read and write (`firestore.rules`). All access goes through service accounts.

## 3. Route inventory (buyer-agent, `apps/buyer-agent/buyer_agent/main.py`)

| Method | Route | Auth | Shop binding | Side effects | Line |
|---|---|---|---|---|---|
| GET | `/health` | none | n/a | none; lists supplier ids, model, modes | 126 |
| POST | `/chat` | owner bearer (Firebase ID token, or operator token) | `check_shop_owner(body.shop_id)` | SSE. ADK turn: draft, negotiation, confirmation request, ledger | 132 |
| POST | `/mandates` | owner | `check_shop_owner(body.shop_id)` | KMS sign, `mandates` create, negotiation create/update, shop active id, ledger `mandate.signed` | 144 |
| GET | `/mandates/{id}` | owner | mandate.shop_id | KMS public key fetch | 179 |
| POST | `/mandates/{id}/revoke` | owner | mandate.shop_id | status revoked, ledger, negotiation cancelled | 188 |
| POST | `/confirm` | owner | confirmation.shop_id and `owner_uid` (`confirm.py:90`) | Cart Mandate sign, gate, ADK resume, PO over A2A, orders, Payment Mandate | 203 |
| GET | `/confirm/{id}` | owner | confirmation.shop_id | none | 217 |
| GET | `/negotiations/{nid}` | owner | negotiation.shop_id | none | 229 |
| GET | `/orders/{id}` | owner | order.shop_id | none (QR render) | 236 |
| POST | `/orders/{id}/cancel` | owner | order.shop_id | order cancelled, ledger | 247 |
| POST | `/payments/{id}/proof` | owner | order.shop_id | order settled or mismatch, payment mandate consumed, ledger | 258 |
| GET | `/verify/{nid}` | none (judge) | demo shop or `attack-demo` only (`judge_negotiation`, 81-87) | KMS public key | 270 |
| POST | `/verify` | none | n/a (verifies a client copy; first 500 events) | none | 279 |
| GET | `/events?negotiation=` | none (judge) | demo shop only | none. **Returns full payloads, including payee VPA and attack text** | 288 |
| GET | `/pubkey` | none | n/a | none | 296 |
| GET | `/metrics/{shop_id}` | none (judge) | `demo` only | O(all ledgers) reads | 303 |
| POST | `/attack` | none, 10/min/IP (in memory, spoofable XFF) | demo attack mandate | Model Armor call, ledger `attack.tested` on `attack-demo` | 334 |
| GET/POST | `/attack/scenarios[/{id}]` | none | n/a | **not deployed** (live 404) | n/a |

Owner authorisation (`main.py:46-70`):
- The operator token maps to `demo-owner`, which works on the demo shop only.
- Otherwise the server verifies the Firebase ID token.
- `check_shop_owner` allows the recorded `owner_uid`, and allows **any** authenticated uid on the demo shop while it has no owner. This is by design for judges, but it is the root of SAUDA-002.

## 4. Screens (owner app, `apps/owner-app/app`)

| Screen | Path | API calls | Notes |
|---|---|---|---|
| Home / chat | `/` (`page.tsx`, `ChatStream.tsx`) | POST `/chat` (SSE) | Client-side dedup of identical events (`ChatStream.tsx:100-105`). Auto-start with `?run=<mandate>` (`:118-121`). |
| Mandate sign form | inside the draft card (`MandateForm.tsx`) | POST `/mandates` | Sends `autonomy_tier:2` (`:48`), but the server does not enforce it (SAUDA-009). |
| Mandate view and revoke | `/mandate/[id]` (`MandateCard.tsx`) | GET `/mandates/{id}`, POST `/revoke` | Shows `signature_valid`. |
| Confirmation | `/confirm/[id]` (`ConfirmView.tsx`) | GET/POST `/confirm` | Navigates to `/pay/<first order>` (`:79`). Other orders are only reachable through the API. |
| Pay | `/pay/[orderId]` (`PayView.tsx`) | GET `/orders/{id}`, POST `/payments/{id}/proof` | Prefills the expected amount (SAUDA-003). |
| Trust Console | `/trust/[negotiationId]`, `/trust/latest` (`TrustConsole.tsx`) | GET `/verify`, `/events`, `/metrics` | The tamper demo recomputes hashes client-side (`lib/chain.ts`). Signatures are checked server-side only. POST `/verify` is not used by the UI. |
| Attack box | `/attack` (`AttackBox.tsx`) | POST `/attack` | Free text. |
| Savings | `/savings/[shopId]` (`MetricCards.tsx`) | GET `/metrics` | See SAUDA-011. |
| Auth gate | `AuthGate.tsx`, `lib/auth.ts` | Firebase Google sign-in | No owner token in the firebase-mode bundle (`deploy/cloudrun.sh:48-54`). |

## 5. Schemas (as implemented)

- **Intent Mandate** (`sauda_trust/mandates.py:48-60`), `extra="allow"`:
  - `shop_id`, `budget_paise:int`, `allowed_supplier_ids[]`;
  - `lines[{gtin, qty:int, ceiling_paise:int, ceiling_source}]`;
  - `max_advance_pct:float`, `deliver_by`, `autonomy_tier:int=2`, `expires_at`, `nonce`, `owner_uid`.
- **Cart Mandate** (`:78-87`):
  - `intent_mandate_id`;
  - `allocations[{supplier_id, lines[{gtin,qty,unit_price_paise}], subtotal_paise, delivery_days, advance_pct, payout_vpa}]`;
  - `total_paise`, `savings_paise`, `gate_report`. Built in `confirm.py:72-81`.
- **Payment Mandate** (`:90-102`):
  - `cart_mandate_id`, `cart_hash`, `amount_paise`, `payee_vpa` (from the registry, `orders.py:140-141`), `method:"upi"`, `cooling_off_until`;
  - extras: `order_total_paise`, `demo_amount`.
- **Signing**: `sha256(canonical(body))` signed by KMS P-256 (`mandates.py:117-121`). Canonical form is sorted keys, compact separators, UTF-8.
- **Order** (`orders.py:78-84`): `status` is one of `cooling_off`, `cancelled`, `settled`. `payment_status` is one of `issued`, `settled`, `mismatch`, `cancelled`.

## 6. Negotiation state machine

`negotiation.status` moves through these states:

1. `created`: set by draft or by mandate sign (`main.py:162-163`).
2. `rfq_sent`, then `quoting`, then rounds 1–3 (`loop.py:124,152`).
3. The negotiation ends in one of:
   - `cart_ready`;
   - `failed` (no verified supplier, no clean offer, or cart DENY);
   - `cancelled` (revoked or kill switch, `loop.py:81-90`).
4. From `cart_ready`: `awaiting_confirmation` (`confirm.py:36`), then one of:
   - `confirmed` (`confirm.py:121`), then `ordered` (`orders.py:94`), or `failed` on a post-confirmation DENY;
   - `cancelled` (declined, `confirm.py:107`).

- Revocation sets `cancelled` unless the negotiation is already terminal (`main.py:198-199`).
- There is one active negotiation per shop (`shops.active_negotiation_id`).
- The rules are max 3 rounds and max 3 suppliers.
- Supplier quarantine happens after 2 guard blocks (`loop.py:247-249`) or a missing nonce echo (`loop.py:195-200`).

## 7. SSE event stream (`services/chat.py`)

| Event | Source |
|---|---|
| `agent.text` | ADK text, screened outbound (`chat.py:134-143`), or the fallback router |
| `agent.tool` | ADK function calls and responses, plus tool emits |
| `draft` | `tools.create_draft` |
| `offer` | negotiator |
| `guard.verdict` | negotiator |
| `gate.report` | negotiator, pre-confirmation |
| `cart` | `run_negotiation` |
| `confirmation.request` | ADK `adk_request_confirmation` translation or fallback |
| `error` | exception handler |
| `done` | end of the turn |

Ping every 10 s. Tool emits are routed by `EMITTERS[shop_id]`, which is a process-global map (SAUDA-002). A deterministic fallback re-runs the same brokered tools if the model skips them (`chat.py:79-94`). The same event can therefore be emitted by both paths; the client deduplicates identical payloads.

## 8. Ledger and verification

- **Append** (`sauda_ledger/events.py:79-99`):
  - A Firestore transaction reads the chain, then sets `seq+1` and `prev_hash` to the last `payload_hash` (genesis is `sha256(negotiation_id)`).
  - The signature is KMS over `sha256(payload_hash + prev_hash)`, and the doc is written with `create`.
  - Payloads are float-free (`trust.no_floats`), so the browser can recompute the hash.
- **Verify** (`verify.py:46-80`) checks:
  - payload hash;
  - link (`prev_hash`, contiguous seq, `negotiation_id`);
  - ECDSA signature with the *current* public key.
- **Gaps:** the signature scope, empty and truncated chains, and key versioning (SAUDA-010).

## 9. Real execution paths (UI → API → gate → KMS → ledger)

### 9.1 Sign mandate
1. `MandateForm.tsx:53` calls `signMandate`. `lib/api.ts:147-150` sends POST `/mandates` with the bearer token.
2. `main.py:144-152` authenticates, then runs `check_shop_owner` and the supplier-count and 2x-volume checks (`:153-157`). There is no other validation (SAUDA-009).
3. It reuses or creates the negotiation (`:160-164`), then `trust.create_mandate` (`:166`) goes to `mandates.build` (pydantic shape check, `mandates.py:179-188`).
4. `sign` calls `KmsSigner.sign` (`kms.py:49-55`, 10 s timeout, errors propagate, so signing fails closed). Then `mandates/{id}.create()`.
5. The negotiation gets `intent_mandate_id` and the shop gets `active_negotiation_id` (`main.py:170-171`).
6. Ledger `mandate.signed` with the full body (`:172-174`). The UI goes to `/mandate/<id>?new=1`.

### 9.2 Start negotiation
1. `/?run=<mandate>` makes `ChatStream.tsx:118-121` send "Start the negotiation under mandate …" with `mandate_id`.
2. `main.py:132-141`, then `chat.stream`. It rebinds `active_negotiation_id` if the mandate's negotiation is in this shop (`chat.py:40-43`).
3. ADK turn (`root.py:55-58`). The model calls `run_negotiation(negotiation_id)`.
4. `tool_broker.broker(R1,R2,R12)` (`tools.py:129`). `context_provider` (`tools.py:69-74`) builds the context from the stored mandate (`signature_valid()` gives a KMS public-key verify). `evaluate`, then ledger `gate.decision` (`tool_broker.py:105-117`). A ledger failure means DENY.
5. `loop.run` (`loop.py:92-291`):
   - Load suppliers: card fetch and registry fingerprint (R2, `a2a.py:171-188`). Unverified suppliers are gated R2 and dropped (`loop.py:116-123`).
   - Each round: an R12/R1 re-check (`:151`), then `rfq.sent` or `counter.sent` in the ledger (`:176`).
   - Parallel A2A `message/send` with a nonce (`:185-191`). A missing nonce echo means quarantine.
   - Each reply: ledger `offer.received`, then Guard (`trust.screen`, Model Armor plus regex, `guard.py:79-93`), then ledger `guard.verdict`.
   - Parse: pydantic data part, or the Gemini fallback (SAUDA-014). Then save the offer and run the offer gate `OFFER_RULES` (`:236`), which writes `gate.decision`.
   - Concession targets (`:294-311`).
   - `allocate` (`cart.py`), then the cart gate `CART_RULES` (`:280`), `save_cart_draft`, and ledger `cart.assembled`.
6. The model calls `place_order`. `FunctionTool(require_confirmation=_require_confirmation)` (`tools.py:234`) runs the pre-confirmation gate with all 12 rules (`tools.py:181-202`), which writes `gate.decision` with stage `pre_confirmation`.
7. ADK emits `adk_request_confirmation`. `chat._translate` (`chat.py:116-124`) calls `confirm.request`, which writes `confirmations` and ledger `confirmation.requested`, sets status `awaiting_confirmation`, and sends the SSE `confirmation.request`.

### 9.3 place_order with confirmation
1. `ConfirmView.tsx:78` sends POST `/confirm {approved:true}`. `main.py:203-214` then `confirm.answer` (`confirm.py:84-162`) checks:
   - owner uid (`:90`);
   - status (`:93-96`);
   - TTL (`:97-100`).
2. It signs the Cart Mandate (KMS) if not already present (`:119-123`) and writes ledger `mandate.signed` (cart).
3. Confirmation becomes `approved` and ledger `confirmation.answered` (`:124-125`). **This happens before the gate** (SAUDA-007).
4. `build_place_order_context` (`tools.py:56-66`):
   - live card fingerprints (R2);
   - latest guard verdicts (R9);
   - `seen_keys` (R11);
   - `owner_confirmed=True`.
5. `evaluate(ALL_RULES)`, then ledger `gate.decision` stage `post_confirmation`. On DENY the negotiation fails.
6. ADK resume (`root.py:61-67`). ADK replays `place_order`, which goes through the broker with all 12 rules, then `orders.place`. If the resume fails, the code places the order directly through the same brokered tool (`confirm.py:151-154`).
7. `orders.place` (`orders.py:49-96`), for each allocation:
   - ledger `po.sent`, then the A2A PO;
   - save the order (`cooling_off`) whether or not the PO succeeded (SAUDA-005);
   - ledger `order.placed`.

   Then the intent mandate becomes `consumed` and the negotiation `ordered`.
8. `issue_payment_mandate`, brokered with R1/R8/R11/R12 (`tools.py:224-231`). Payee comes from the registry (`orders.py:140-141`). KMS-signed Payment Mandate, UPI link, ledger `payment_mandate.issued`.

### 9.4 Payment proof
1. `PayView.tsx:43` sends POST `/payments/{id}/proof {utr, amount_paise: <expected>}`.
2. `main.py:258-266`, then `orders.submit_proof` (`orders.py:183-213`) checks the 12-digit format, compares the amount (client-supplied, so it trivially matches), and compares the payee only if one is supplied. The UI never supplies one.
3. The order becomes `settled` and the payment mandate `consumed`. Ledger `payment.settled`. **No bank verification** (SAUDA-003/004).

### 9.5 Verify
1. `TrustConsole.tsx:44-45` sends GET `/verify/{nid}` and `/events`.
2. `main.py:270-276` runs `judge_negotiation` (demo shop only), then `verify_chain` (`verify.py`), which fetches the KMS public key and checks each event.
3. The tamper demo edits a local copy and runs `lib/chain.ts` `recomputeChain`. Signatures cannot be checked client-side, and POST `/verify` exists but is unused.

## 10. Journeys

| Journey | Status | Evidence |
|---|---|---|
| Sign in with Google, then restock chat, draft, sign mandate | Works | Live `auth_mode=firebase`. Ledger on `neg_326c40363a4c` has `mandate.signed` ×2 (intent + cart). |
| Negotiate with 3 suppliers; hostile QuickStock blocked or quarantined | Works | Same chain: 3 `rfq.sent`, 8 `offer.received`, 8 `guard.verdict`, 1 `supplier.quarantined`, 15 `gate.decision`. |
| Confirm, then PO and payment mandate | Works (single user) | Same chain: `confirmation.answered`, `po.sent`, `order.placed`, `payment_mandate.issued`. `/verify` gives `chain_ok=true`, 48 events. |
| UTR proof | "Works", but is circular and overclaims | SAUDA-003/004 |
| Trust Console verify and tamper demo | Works | Live `/verify` 200 in 0.18 s |
| Attack box (free text) | Works; rate limit spoofable | `/verify/attack-demo` gives `chain_ok=true`, 29 events |
| Attack scenarios (10 fixed) | **Fails**: not deployed | `GET /attack/scenarios` returns 404 |
| Two judges at the same time on the demo shop | **Fails / unsafe** | SAUDA-002 |
| Revoke mid-negotiation | Works (checked before each round) | `loop.py:151` |
| Cancel during cooling-off | Partially: the payment mandate stays live | SAUDA-006 |
| Delivery / fulfilment tracking | Not built | No code path |
| Voice, Hindi or Telugu end to end | Not at baseline (voice in progress in WT) | n/a |
| Shelf photo, purchase history | Not built (Plan B) | README |

## 11. Limitations (prototype)

- Suppliers are simulated, with published strategies. QuickStock is hostile by design.
- Savings are measured against the suppliers' own opening quotes. They are not a market price and are inflated by SAUDA-011.
- Payment is a real UPI link for a demo amount (Rs 1, from `DEMO_PAY_AMOUNT_PAISE=100`). The UTR is owner-entered and never bank-verified.
- Mandates are signed by the server's KMS key on behalf of the authenticated owner. This is not an owner-held key (SAUDA-027).
- There is one buyer instance, ADK sessions live in memory, and each shop has one active negotiation.
- Reference prices come from the seed. The daily refresh is paused because of the 403 from cloud IPs.

## 12. Baseline evidence (commands actually run, 18 Oct 2026 12:17–12:25 IST)

```
$ git archive 56927f7 | tar -x -C <scratch>/base && cd <scratch>/base && uv run pytest -q
34 passed in 3.49s
  (test_policy_gate 13, test_gate_extras 7, test_mandates 5, test_price_refresh 5, test_ledger 4; no API tests)

GET /health             200 0.14s  {"status":"ok","auth_mode":"firebase","agent_mode":"adk","model":"gemini-3.5-flash","suppliers":[metro,sharma,quickstock]}
GET /pubkey             200 0.12s  -----BEGIN PUBLIC KEY----- (P-256)
GET /metrics/demo       200 1.63s  rupees_saved=361860 (paise), savings_pct=3.29, ceiling_compliance=1.0,
                                   time_saved_min=876.0, attacks_blocked=68, orders=16, last_negotiation_id=neg_326c40363a4c
GET /verify/neg_326c40363a4c 200 0.18s chain_ok=true first_broken_seq=null events=48
GET /verify/neg_doesnotexist 404 "only the demo shop is public"
GET /verify/attack-demo 200 0.22s chain_ok=true events=29
GET /attack/scenarios   404 {"detail":"Not Found"}
gcloud scheduler jobs list -> price-refresh-daily PAUSED
gcloud run services describe buyer-agent -> AUTH_MODE=firebase, AGENT_MODE=adk, DEMO_PAY_AMOUNT_PAISE=100,
   DEMO_OWNER_TOKEN and DATA_GOV_IN_API_KEY from Secret Manager; min=max=1
Secret-history scan (git log -p --all | grep -c, values not printed): no Google API keys, no private keys, no
   OAuth tokens; DEMO_OWNER_TOKEN only as a secretKeyRef plus a default literal in code (SAUDA-019); real payee
   VPA present in an internal build note and suppliers/sharma.json at baseline (SAUDA-020, since fixed).
```

No POST was made to the live API, and no demo-shop state was touched.
