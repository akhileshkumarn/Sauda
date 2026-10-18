# Sauda: Test Plan

Baseline: commit `56927f7`. Issue IDs refer to [ISSUE_REGISTER.md](ISSUE_REGISTER.md).

## 1. Current coverage (baseline, actually run)

```
$ uv run pytest -q        (clean export of 56927f7)
34 passed in 3.49s
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_policy_gate.py` | 13 (parametrised) | All-12 clean pass; one failing case per rule R1–R12 |
| `tests/test_gate_extras.py` | 7 | Gate exception means DENY GATE_ERROR; rule subsets and unknown rule; QuickStock offer denied by R5+R8; broker allow/deny and ledger write; broker bad args and missing provider; regex guard; Model Armor error fails closed |
| `tests/test_ledger.py` | 4 | Chain verifies; payload edit breaks from that seq; reorder or delete breaks; wrong key breaks signatures |
| `tests/test_mandates.py` | 5 | Canonical JSON; sign/verify round trip; tampered body; forged hash; record/intent model |
| `tests/test_price_refresh.py` | 5 | Freshness-aware reference-price merge |

**Gaps at baseline:**
- **No API tests.** Nothing exercises the FastAPI routes, auth, `check_shop_owner`, judge bindings or SSE.
- **No negotiation-loop, cart or allocation tests.**
- **No confirm/order/payment service tests.**
- **No owner-app tests**: no `test` script in `apps/owner-app/package.json`, so `pnpm build` is the only gate.
- **No accessibility or end-to-end tests.** `apps/buyer-agent/e2e_local.py` is a manual script against live services.
- No concurrency or idempotency tests.

## 2. Test layers and conventions

- **Unit:** pure functions with `LocalSigner` (`kms.set_signer`) and an in-memory ledger. No network.
- **Integration (API):** FastAPI `TestClient` with a fake Firestore (dict-backed `store` and `sauda_ledger` stubs, or the Firestore emulator), `LocalSigner`, Guard set to `use_model_armor=False`, fake `SupplierClient` responses, and `AGENT_MODE=direct` (deterministic router, no LLM).
- **Security:** attack scenarios and authorisation matrices run against the integration harness.
- **End to end:** Playwright against local backend (port 8082) and Next (3100) with `DEMO_SHOP_ID=dev`. **Never** against shop `demo`.
- **Accessibility:** axe-core through Playwright on each screen, plus manual screen-reader passes.
- **Gate for merge:** `uv run pytest -q` green and `pnpm build` passing.

## 3. Planned unit tests

| ID | Area | Test | Issue |
|---|---|---|---|
| U1 | Gate R4/R3 | Negative, zero or huge `unit_price_paise` gives DENY. A stated subtotal below Σ lines still counts Σ. | SAUDA-001 |
| U2 | Gate R5 | NaN, -1 and 100.01 advance give DENY. Exactly the max gives ALLOW. | SAUDA-001 |
| U3 | Quote parse | `QuoteLine(unit_price_paise=-1)` raises. A text-only quote never yields an LLM price unless verbatim. | SAUDA-001, 014 |
| U4 | Cart allocate | MOQ and availability, tie-break toward preferred, small-supplier merge, savings maths in integers, dropped lines. | n/a |
| U5 | Concession schedule | Integer-only targets; never above the ceiling; round-3 midpoint. | SAUDA-017 |
| U6 | Ledger v2 | Editing `type`, `actor` or `ts` breaks `sig_ok`. Empty chain gives `chain_ok=false`. Dropping the tail fails the head check. Per-`key_version` key lookup. Old v1 events still verify. | SAUDA-010 |
| U7 | Ledger canonical parity | Python `canonical` and `lib/chain.ts` `canonical` produce identical bytes for a fixture corpus: unicode (Devanagari, Telugu, emoji/non-BMP keys), control characters, nested arrays, ints up to 2^53, booleans, null. | Regression R2 |
| U8 | `no_floats` | Integral float becomes int, non-integral becomes string. Nested pydantic objects. Floats never reach `append`. | n/a |
| U9 | Guard | Inbound timeout means blocked. Outbound timeout means withheld. Regex categories for injection, bank change and advance in en/hi transliteration. | SAUDA-015 |
| U10 | Metrics | Only ordered, non-cancelled negotiations count toward savings. Attack counters are split. | SAUDA-011 |
| U11 | Mandate validation | Each contract item 3 rule gives 422. `autonomy_tier` is forced to 2. Unknown keys are dropped. | SAUDA-009 |
| U12 | Payment proof | Cancelled order gives 409. Reused UTR gives mismatch. Status `claimed`. Legacy `settled` reads as `claimed`. | SAUDA-003, 006 |
| U13 | Request parsing | Ambiguous items ("oil", "atta 5") give `confidence:"low"` with alternatives or clarifications, never a silent pick. Explicit qty is kept. Uplift is only a suggestion. | Regression R4, SAUDA-031 |

## 4. Planned integration (API) tests: none exist at baseline

| ID | Route | Cases |
|---|---|---|
| I1 | All owner routes | No token gives 401. Bad Firebase token gives 401. Operator token on a non-demo shop gives 403. Another owner's shop gives 403 (mandate, confirm, order, proof, cancel, negotiation). |
| I2 | Judge routes | `/verify`, `/events` and `/metrics` for a non-demo shop give 404. `attack-<demo>` is allowed. |
| I3 | POST `/verify` (malformed) | `events` not a list gives 422. Items with missing fields, a non-numeric `seq`, or a non-base64 signature give 200 with `ok=false` (never 500). 501 events are truncated to 500. Deeply nested payloads are bounded. |
| I4 | POST `/mandates` | Happy path writes the `mandates` doc and ledger `mandate.signed`. KMS failure gives 4xx and no doc. Validation 422s. |
| I5 | POST `/chat` (direct mode) | Restock message gives `draft` then `done`. Start with `mandate_id` gives offer/gate/cart/`confirmation.request`/`done`. Each event appears **exactly once** with the same payload. |
| I6 | POST `/confirm` | Approve gives orders and payment mandates. Decline gives cancelled. Expired gives 410. Another uid gives 403. **10 parallel approvals give one PO per supplier.** Post-confirmation DENY gives the confirmation `denied`. |
| I7 | Orders | PO failure gives no payment mandate. Cancel within cooling-off revokes the payment mandate. Cancel after cooling-off gives an error. |
| I8 | Tool binding | A model tool call with another shop's `negotiation_id` or `shop_id` gives DENY and no writes. |
| I9 | `/attack` | 11th call per minute gives 429 even with a spoofed first XFF hop. The ledger message is truncated. |
| I10 | `/attack/scenarios` | GET lists 10 IDs. Each POST returns `checks[]` and the expected `outcome`. `guard_timeout` shows `source:"timeout"` and blocked. |
| I11 | `/products`, `/shops/{id}/overview`, `/voice/parse` | Auth, shape (contract items 2, 4, 7), limits (60 s / 3 MB / mime). Audio is never persisted. |
| I12 | Error hygiene | Forced exceptions return a code plus request id, with no stack or exception text. |

## 5. Security tests (attack scenarios)

Each scenario runs the real guard, gate and ledger code through the integration harness, plus an end-to-end variant against `dev`.

| Scenario | Assertion |
|---|---|
| `legit_offer` | outcome `needs_approval`; R10 CONFIRM; all other rules ALLOW |
| `prompt_injection` | guard blocked (regex at minimum when Model Armor is off); R9 DENY; supplier quarantined on 2nd block |
| `excessive_advance` | R5 DENY (also for NaN) |
| `payee_substitution` | R8 DENY; Payment Mandate payee equals registry even when the quote claims another |
| `unknown_supplier` | R2 DENY for not-in-mandate, unregistered, quarantined, fingerprint change |
| `expired_mandate` | R1 DENY at round start, at confirm and at payment |
| `over_budget` | R3 DENY, including the negative-line and understated-subtotal variants |
| `replayed_order` | R11 DENY; parallel replay gives one PO |
| `tampered_ledger` | verify breaks at the edited seq; v2 also catches `type`/`actor` edits and truncation |
| `guard_timeout` | inbound timeout gives blocked plus R9 DENY; outbound timeout gives withheld text |

Additional: cross-shop BOLA matrix (I1, I8); demo-shop concurrency (two uids, SAUDA-002); IAM check script (`gcloud projects get-iam-policy` shows no datastore role on `supplier@`); secret scan in CI (gitleaks over history, values never printed).

## 6. Accessibility tests

- axe-core: zero serious or critical violations on `/`, `/mandate/[id]`, `/confirm/[id]`, `/pay/[id]`, `/trust/[id]`, `/attack`, `/savings/demo`.
- Keyboard only: full journey (sign, confirm, pay); visible focus; no traps; the confirm button is reachable and labelled with the amount.
- Screen reader (VoiceOver iOS, TalkBack): the chat stream announces new events politely (`aria-live`); gate verdicts are read as text, not colour only; the UTR input has a label (present: `PayView.tsx:88`).
- Contrast at least 4.5:1 for body text and verdict chips. 360 px width layout. Text zoom at 200 %.
- Language: Hindi or Telugu strings render (fonts), and `lang` attributes are set when content language changes. Claim a language works only after an end-to-end test (CONTRACT honesty rule).

## 7. End-to-end tests (Playwright, shop `dev`)

1. Restock, draft, edit a line, sign, then the mandate page shows a valid signature.
2. Start negotiation, then offers stream: QuickStock blocked and quarantined, cart ready, confirmation link.
3. Approve, then the Pay page shows the demo amount and order total, and the QR. Enter a UTR: the page shows "claimed, not bank-verified".
4. Trust Console: `chain_ok`; tamper an event and the first broken seq is highlighted; restore.
5. Revoke mid-negotiation, then cancelled; no orders.
6. Two browser contexts with different users on the same shop: no cross-stream (SAUDA-002).
7. Voice (when built): record, transcript, edit, send; preview matches the parsed lines.

## 8. Regression list (must stay fixed)

| # | Regression | Test |
|---|---|---|
| R1 | **Duplicate stream events**: the fallback router and the tool emitter both relay the same `offer`, `gate.report` or `confirmation.request`. The client deduplicates (`ChatStream.tsx:100-105`), but the server should emit once. | I5 counts events by (type, payload hash) and every count is 1. The UI renders one card per event. |
| R2 | **Hash disagreement** between server `canonical` (Python) and client `lib/chain.ts`: floats, unicode, key order, large ints. | U7 parity corpus. End-to-end: Trust Console local recompute equals server `payload_hash` for every event of a fresh chain. |
| R3 | **Malformed /verify** input must never 500. | I3 |
| R4 | **Ambiguous parsing**: the request parser silently picks a product or inflates qty. | U13. The draft shows `confidence:"low"` plus clarifications. |
| R5 | **Misleading payment language**: "settled", "verified", "paid" or "amount and payee match" when only a UTR was entered. | U12 plus a UI text snapshot: no `settled`/`verified` strings on Pay/Trust; "not bank-verified" present. |
| R6 | Guard timeout fails closed (inbound). | `test_guard_model_armor_error_fails_closed` (exists) plus U9 |
| R7 | Gate exception means DENY. | `test_gate_error_fails_closed` (exists) |
| R8 | Payee always from the registry. | I7 plus scenario `payee_substitution` |

## 9. Non-functional

- Cold start: time from a fresh revision to the first `/health` and to the first negotiation. Target 5 s or less for buyer health, 30 s or less for a cold negotiation.
- p95 `/metrics/demo` below 300 ms (currently 1.6 s live).
- Load: 5 concurrent `/chat` sessions on separate shops; no event leakage; latency recorded.

## 10. Restock sessions: persistence (owner app, pass 2)

Status key: **automated** means a script ran on 18 Oct and the result was observed. **Manual** means a person
checked it by hand. **Not done** means it was not run. Scripts are in the session scratchpad `pptr/` (puppeteer-core
with headless Chrome). "Live" means the local backend on :8092 with shop `dev`; "mock" means `NEXT_PUBLIC_MOCK=1`.

| # | Test | How | Status |
|---|---|---|---|
| P1 | New restock creates a new session and opens `/restock/{sid}`; existing sessions untouched | `ux2live.mjs`, `bridge.mjs`, `ux2.mjs` | automated (live + mock) |
| P2 | Refresh restores the same lines and quantities | `ux2live.mjs`: `11,8,30,4 => 11,8,30,4 MATCH` | automated (live + mock) |
| P3 | Closing the browser restores the session (fresh browser context, no local storage) | `ux2live.mjs` "fresh-context restore MATCH" | automated (live) |
| P4 | Navigate away and browser Back restores the session | `ux2.mjs` "back-restore MATCH" | automated (mock) |
| P5 | Autosave: a stepper edit shows Saving… then Saved only after PATCH 2xx | `ux2live.mjs` (indicator read right after the edit: "Saving…"), `ux2.mjs ?mock=slow` | automated |
| P6 | Save failure shows "Couldn't save · Retry", never Saved | `ux2.mjs ?mock=saveerr` | automated (mock) |
| P7 | Version conflict: two contexts edit the same session; the stale one adopts the server copy and shows the notice | `ux2live.mjs` "conflict notice shown" | automated (live) |
| P8 | Completed or ordered session opens read-only with order status; "Copy into a new restock" | `ux2live.mjs` (`m-readonly-ordered`), `more.mjs` (copy gives a new sid with 2 lines) | automated (live) |
| P9 | Unknown sid shows "not found" | `ux2.mjs` (`m-not-found`) | automated (mock) |
| P10 | Bridge: draft, Review limits (prepare), Sign, mandate, Start negotiating, SSE, confirmation; returning to the session shows "Your approval is needed" and Review and approve, without replaying the SSE | `bridge.mjs` | automated (live, real suppliers, shop `dev`) |
| P11 | Approve on `/confirm`, then `/pay`; the session then shows Ordered with order pills | `more.mjs` | automated (live). UTR entry not run in this pass |
| P12 | Cancel the draft, then it shows Cancelled in history | `more.mjs` | automated (live) |
| P13 | Rename persists across refresh | `more.mjs` | automated (live) |
| P14 | New sign-in (Firebase) restores the session list for the same owner | — | not done (local runs use demo auth) |
| P15 | Layout at 360, 390, 768 and 1280: no horizontal scroll on `/`, `/restock`, `/restock/{sid}`, a read-only session, `/orders` | `ux2.mjs` | automated (mock) |

## 11. Continuous voice

| # | Test | How | Status |
|---|---|---|---|
| V1 | Partial text shown while speaking | `ws.mjs` (scripted `SpeechRecognition` driving the real listener) | automated |
| V2 | A final result is applied directly as a turn (no confirmation step) | `ws.mjs`: "Added 10 Fortune ata 5kg and 20 Refined Sunflower Oil" | automated (live) |
| V3 | A duplicate final is ignored | `ws.mjs` | automated |
| V4 | Recogniser `end` while listening auto-restarts (no 60 s limit) | `ws.mjs` | automated (scripted); real long-session check not done |
| V5 | Low confidence (< 0.6) shows "Did you say…?" and applies nothing | `ws.mjs` | automated |
| V6 | Network error keeps the heard text, with Retry and Send what we heard | `ws.mjs` | automated |
| V7 | Permission denied shows how to fix it, plus Type instead | `ws.mjs` | automated |
| V8 | Route change releases the recogniser or microphone | `ws.mjs` (abort observed) | automated |
| V9 | Recorder fallback: VAD splits two sentences into two segments, then `/voice/parse`, then two turns | `lat.mjs voice` (WebAudio-injected phrase); "Salt LITE now 12" | automated (live) |
| V10 | "sign it" by voice or text only opens the limits review; nothing is signed | `ux2live.mjs`, `ux2.mjs` | automated |
| V11 | Auto-stop after 2 minutes without speech | — | not done (logic is in `IDLE_STOP_MS`) |
| V12 | Real microphone with Web Speech on Android Chrome and desktop Chrome, a 5-minute conversation | — | manual, not done |
| V13 | Hindi and Telugu speech end to end | — | not done |
| V14 | Safari / iOS recorder path (MP4) | — | not done |
| V15 | Switching between typing and speaking in one session | `ws.mjs` and typed turns on the same page | partially automated |

## 12. Performance (client marks, `?debug=1`, `POST /telemetry/voice`)

| # | Measure | Result (18 Oct, laptop to local backend to asia-south1) | Status |
|---|---|---|---|
| L1 | Typed fast-path turn: turn_sent to draft_rendered | 0.31 to 0.37 s (7 turns) | automated (`lat.mjs typed`) |
| L2 | Typed model turn | 1.6 to 3.3 s (3 turns) | automated |
| L3 | Render after response | 9 to 41 ms | automated |
| L4 | Recorder fallback: utterance_end to draft_rendered | 6.6 s and 7.3 s (transcription 4.1 to 4.3 s) | automated |
| L5 | Web Speech: utterance_end to draft_rendered on a real phone | — | not done; measure with `?debug=1` |
| L6 | Same numbers from Cloud Run (deployed) | — | not done |
