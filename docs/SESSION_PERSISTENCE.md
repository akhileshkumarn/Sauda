# Persistent restock sessions

Backend: `apps/buyer-agent/buyer_agent/services/sessions.py` (model, turns, derivation) and
`apps/buyer-agent/buyer_agent/session_routes.py` (routes). Tests: `tests/test_sessions.py`.

## Why

The root cause was verified at HEAD 55f18d3. `ChatStream.tsx` kept the conversation and negotiation in React `useState`
only, so leaving `/restock` threw it away. ADK sessions are `InMemorySessionService()` (`agent/root.py:31`), so they are
lost on every Cloud Run restart and are not shared between instances. Nothing persisted a restock until a negotiation
existed. A restock session is now a Firestore document that the owner can leave and come back to on any device.

## Data model: `restock_sessions/{sid}`

| field | notes |
|---|---|
| `sid` | `rs_<12 hex>`; anything else is 404 without a read |
| `shop_id`, `owner_uid` | set at creation from the authenticated owner |
| `title` | ≤ 80 chars; default "Restock 18 Oct, 14:05" |
| `status` | `draft` · `awaiting_review` · `negotiating` · `awaiting_approval` · `ordered` · `completed` · `cancelled` · `failed` |
| `version` | int, +1 on every owner write (turn, PATCH, prepare, cancel) |
| `created_at`, `updated_at` | ISO 8601 UTC |
| `turns[]` | `{turn_id, client_turn_id, role: owner\|sauda, text, source: voice\|text, ts, lang?}`; Sauda turns add `ops`, `clarification`, `latency_ms`, `fast_path` |
| `turns_trimmed` | number of oldest turns dropped by the cap |
| `draft` | the same shape as the `/chat` draft: `lines[]` (DraftLine with `qty_source`, `requested_qty`, `suggested_qty`, `confidence`, `alternatives`, ceilings), `stated_budget_paise`, `budget_estimate_paise`, `suggested_budget_paise`, `clarifications[]`, `unmatched[]`, `suggested_mandate`, `budget_notes` |
| `pending` | an open clarification: `{op, options, question}`, applied when the owner names an option |
| `negotiation_id`, `intent_mandate_id`, `confirmation_id`, `order_ids[]` | links into the existing flow |
| `error` | `{code, message}` or null: `mandate_expired`, `mandate_revoked`, `mandate_missing`, `negotiation_failed`, `confirmation_expired` |
| `resumable` | whether purchasing can continue from here |

Responses also carry a computed `needs_attention`. It is true when the session has clarifications, a pending question
or an error, or is awaiting approval.

All money is integer paise. Every line, ceiling and estimate is recomputed by `demand.draft_line` /
`demand.finalize_draft`, which are the same helpers that `/chat`'s `build_draft` now uses. Client-sent ceilings are
ignored.

## Lifecycle

```
draft ──prepare──▶ awaiting_review ──POST /mandates──▶ negotiating ──cart + confirmation──▶ awaiting_approval
  │                    │  (edits still allowed; re-prepare            │                         │ /confirm approve
  │                    │   updates the same unsigned negotiation)     │                         ▼
  └──cancel──▶ cancelled ◀──cancel / mandate revoked──────────────────┘                      ordered ──all orders claimed──▶ completed
                                       negotiation failed / gate denied ──▶ failed
```

- Status is derived from the authoritative records on every GET, list and write (`sessions.derive`). The negotiation
  status maps as follows: `created` gives `awaiting_review`, or `negotiating` once a mandate is attached;
  `rfq_sent`, `quoting` and `cart_ready` give `negotiating`; `awaiting_confirmation` and `confirmed` give
  `awaiting_approval`; `ordered` gives `ordered`; `cancelled` and `failed` map to themselves. Any orders found mean
  `ordered`, and `completed` follows when every live order's payment is `claimed`. A session-level `cancelled` holds
  unless orders exist. A derived status never contradicts the negotiation or orders.
- Edits (turns, PATCH lines or budget) are allowed only in `draft` and `awaiting_review`. Otherwise the response is
  409 `{code:"session_locked", message, session}`. Only the title can be renamed in any status.
- `POST /prepare` creates the negotiation exactly like `draft_order` does (`store.create_negotiation(shop, uid,
  draft=...)`), sets `shops/{shop}.active_negotiation_id`, and takes the per-shop owner lock first (`claim_shop`, 409
  while another owner negotiates). It reuses the session's negotiation while that is still `created` and unsigned.
  After that the existing flow is unchanged: `POST /mandates {negotiation_id}`, then `POST /chat {mandate_id}` (SSE),
  then `/confirm`, then `/pay`.
- Links stay in sync. `POST /mandates` calls `sessions.on_mandate_signed` inside a try/except, so it can never block
  signing; it also relinks the session if /mandates had to start a fresh negotiation. The confirmation and order links
  are derived on GET from the negotiation (`confirmation_id`, `order_ids`, `orders_for`).
- `POST /cancel` is refused (409) once the session is ordered. It closes an unsigned `created` negotiation shell and
  releases the shop lock. It revokes nothing that is signed; mandate revocation stays with `POST /mandates/{id}/revoke`.

## Routes (owner auth on all)

| route | result |
|---|---|
| `POST /restock/sessions {title?, shop_id?}` | session (draft, empty draft) |
| `GET /restock/sessions?status=&limit=20&shop_id=` | `{"sessions":[{sid,title,status,updated_at,line_count,budget_paise,total_paise,needs_attention,resumable}]}`, newest first |
| `GET /restock/sessions/{sid}` | full session, derived status refreshed |
| `PATCH /restock/sessions/{sid} {version, title?, lines?, stated_budget_paise?}` | session; 409 `version_conflict` (with the current session); 409 `session_locked`; 422 on invalid lines |
| `POST /restock/sessions/{sid}/turns {client_turn_id, text, source, lang?}` | `{session, reply, ops, clarification, latency_ms:{extract,apply,total,load}, fast_path, dedup}` |
| `POST /restock/sessions/{sid}/prepare` | `{session, negotiation_id, suggested_mandate}`; 422 `empty_draft`; 409 shop busy |
| `POST /restock/sessions/{sid}/cancel` | session |
| `POST /telemetry/voice {sid, marks:[{name, t\|t_ms, utt?}]}` | `{ok, durations_ms}` (median per mark pair); logged, nothing stored |

Deviations from CONTRACT2:
- `shop_id` is an optional extra on create and list. It defaults to `DEMO_SHOP_ID`, because the contract body has no
  shop.
- Turn responses carry the extra fields `fast_path`, `dedup` and `latency_ms.load`.
- `total_paise` in the list is the sum of the orders once ordered; before that it is the ceiling estimate.

## Autosave and concurrency

- Every owner write is a compare-and-set on `version`: a Firestore transaction that reads the doc and writes only if
  `version` is unchanged (`sessions._cas`). Within one instance a per-sid lock serialises turns. Across instances the
  CAS makes a racing write fail with 409 `version_conflict`, and the response includes the current session so the
  client can rebase.
- PATCH must carry the `version` the client last saw; a mismatch gives 409 `version_conflict`.
- Derived fields (status and links) are written back without bumping `version`, so a background status change never
  invalidates an owner's pending edit.
- Turns are idempotent on `client_turn_id`. A repeat returns the stored reply, ops and clarification with
  `dedup: true` and applies nothing.

## Restoration rules (GET)

- The server reloads the negotiation, the intent mandate (`trust.get_mandate`), the confirmation and the orders.
  Nothing is cached on the session as truth.
- An expired, revoked or missing mandate on an unfinished session sets `resumable: false` and an `error` explaining
  that purchasing can't resume. The draft stays fully viewable and copyable. A revoke also cancels the negotiation
  (existing route), so the session shows `cancelled`.
- A confirmation that is still `requested` but past its expiry adds `error.code = confirmation_expired`.
- Tool calls are never replayed. Old turns are history only, so text like "approve" or "sign it" in a stored turn has
  no effect. Even live, those phrases only return `ops:[{op:"navigate", to:"review"|"approval"}]`. Signing and
  approval stay explicit and screen-based.

## Access control

Every route needs owner auth. A sid route returns 404, never 403, when the sid is unknown or malformed, when the
session belongs to another `owner_uid` (including another signed-in user on the shared demo shop, the same
per-owner rule as overview), or when the caller fails `check_shop_owner` for the session's shop. Creating or listing
on a shop you don't own gives 403, as for other shop routes.

## Retention and privacy

- No audio is stored. `/voice/parse` still parses in memory; sessions store only transcript text.
- Turns are capped at 200 per session, oldest dropped first (`turns_trimmed` counts them), and each turn text is
  capped at 1000 chars. Unmatched phrases keep only the last 20.
- Logs at INFO carry `{sid_hash, turn_ms_extract, turn_ms_apply, fast_path, ops (op/gtin/qty/paise), dedup}`, never
  transcript text. Telemetry logs only durations.
- There is no automatic deletion in this build. A TTL policy on `updated_at` (for example 30 days) is a Firestore
  console setting and is listed as an open item.

## Tests (`tests/test_sessions.py`, 22 tests)

- Create, get and list; a foreign or unknown sid is 404 (including another owner on the demo shop and another shop);
  401 without a token.
- PATCH: version conflict gives 409 with the session; invalid gtin, qty or duplicates give 422; client ceilings are
  ignored.
- Turns:
  - add, then budget, set_qty, "add another", remove and a total question across consecutive turns, with fast-path
    flags;
  - "the oil" with two oil lines gets one clarification and no change, and the answer "the mustard one" applies it;
  - a duplicate `client_turn_id` is not applied twice;
  - "sign it", "approve" and "place the order" never change state (no mandate or confirmation);
  - model ops are validated (unknown gtin, unnamed product, a budget never said and a non-line remove are all
    dropped) and the reply's numbers come from code;
  - the model-failure fallback uses the shared parser;
  - the turn cap trims the oldest turns;
  - number words are normalised.
- Prepare bridges to the existing flow: /mandates gives negotiating, a cart gives awaiting_approval, /confirm gives
  ordered with order_ids and the list total, and turns and PATCH are locked. Also covered: empty draft gives 422, a
  busy shop gives 409, and cancel works.
- Resume with an expired mandate plus an old "approve" turn: `resumable:false`, `error mandate_expired`, the
  confirmation is still requested and no orders exist. A revoked mandate gives cancelled.
- The voice segment limit is 30 s; telemetry logs durations only and returns 404 for a foreign sid.

Live check on shop `dev` (local :8091, Vertex, real suppliers): session, two turns, prepare (`awaiting_review`),
`POST /mandates` (`negotiating`), `POST /chat {mandate_id}` (SSE, 102 s, confirmation.request,
`awaiting_approval`), then `POST /confirm` approve (one Sharma order). GET then showed `ordered`, `resumable:false`
and 1 order_id, and a further turn returned 409.
