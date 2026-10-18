# Sauda owner app: UX redesign

Scope: `apps/owner-app` (Next.js 15). The voice capture component (`components/voice/**`, `lib/voice.ts`) belongs to the voice work and is only placed in the composer. `lib/chain.ts` canonicalisation is unchanged, so it still matches the server byte for byte.

## Audience and principles

- The primary user is a busy kirana owner on a phone. Judges are the secondary audience.
- The primary job is to **create or continue a restock**. Every screen points back to that job.
- The app must show five things clearly:
  1. Sauda understood the restock.
  2. It compares and negotiates.
  3. It respects the owner's signed limits and only uses registered suppliers.
  4. The owner approves before anything consequential happens.
  5. It leaves a trail anyone can audit.
- Plain shop-owner language. Rule IDs (R1–R12), reason codes, hashes, mandate IDs and raw JSON live only inside collapsible **Technical evidence** sections.
- Honesty is part of the design:
  - Simulated distributors are labelled "Simulated distributor".
  - The ₹1 demo payment is disclosed.
  - A UTR is "claimed", never "settled" or "verified".
  - Delivery is shown as "Not tracked in this build".
  - Savings are scoped to the demo shop and measured against opening quotes.
- Payee UPI IDs are never printed in full. They show as `79••••357@ybl` (first 2 and last 3 characters of the local part), preferring the backend's `payout_vpa_masked`. The raw VPA exists only inside the `upi://` link and QR. Evidence text, transcripts and the tamper editor mask any VPA-looking token; the tamper editor restores masked values before hashing, so an untouched field does not count as a change.

## Information architecture

Navigation only lists sections that are backed by working features. On phones it is a bottom tab bar (6 tabs, icon plus label); on screens 900px and wider it is a top bar.

| Tab | Route | Backed by | Auth |
|---|---|---|---|
| Home | `/` | `GET /shops/{shop}/overview` | owner |
| Restock | `/restock` (history), `/restock/[sid]` (working session), `/restock?run=<mandate>` (live negotiation), `/mandate/[id]`, `/confirm/[id]` | `/restock/sessions*`, `/negotiations/{id}`, `/chat` SSE (negotiation only), `/products`, `/mandates`, `/confirm` | owner |
| Orders | `/orders`, `/pay/[orderId]` | overview `recent_orders`, `/orders/{id}`, `/payments/{id}/proof` | owner |
| Trust | `/trust/[negotiationId]` (`latest` resolves to the last one) | `/verify`, `/events` | public |
| Attack | `/attack` | `/attack/scenarios`, `/attack/scenarios/{id}`, `/attack` | public |
| Savings | `/savings/[shopId]` | `/metrics/{shop}` | public |

Old links to `/?run=<mandate>` redirect to `/restock?run=<mandate>`.

The restock flow is a numbered four-step journey:
1. Draft (a persistent restock session, `/restock/[sid]`).
2. Signed limits (`/mandate`).
3. Approve the cart (`/confirm`).
4. Order and payment (`/pay`).

## Design system (`app/globals.css`, `components/ui.tsx`)

**Tokens**
- **Colour.** Slate neutrals (`--ink` 17.8:1, `--ink-2` 7.6:1, `--ink-3` 4.8:1 on white), with the indigo brand `--accent #4338ca`.
- **Status colours.** Each comes as a soft background, a line and an ink colour, all at least 4.5:1:
  - ok (green)
  - bad (red)
  - warn (amber)
  - info (blue)
  - quar (purple, used only for quarantined suppliers)
  - neutral
- **Type scale.** 12 / 13 / 15 / 17 / 20 / 24 / 30 px. Body text is 15px. Money uses tabular numerals.
- **Spacing, radius, elevation.** Spacing on a 4px grid (`--s1`…`--s10`). Radius 8 / 12 / 16 / pill. Two shadow levels. A visible focus ring (`--focus`) on every interactive element.
- **Not used:** AI gradients, glassmorphism, giant heroes.

**Components (`components/ui.tsx`)**
- `Button` and `ButtonLink`: variants primary, secondary, ghost, danger, danger-solid and success. Buttons have a `busy` state with a spinner and label, and are disabled while busy.
- `Card` and `PageHead`.
- `StatusPill`: always icon plus text, never colour alone.
- `Money`: integer paise to ₹ with Indian digit grouping (₹1,23,456.78) and tabular numerals.
- `Callout`.
- `Evidence`: a collapsible "Technical evidence" section.
- `EmptyState`.
- `ErrorState`: maps HTTP status to plain words and offers "Try again".
- `Skeleton`.
- `Timeline`: each step is done, current, failed, needs attention, not yet, or not tracked. The dot has an icon and an aria label.
- `Meter` (role="meter").
- `Icon`: an inline SVG set with no dependency.

**Shared helpers**
- `components/status.tsx`: honest order and negotiation status labels.
- `components/Permissions.tsx`: the MAY / MAY NOT summary.
- `components/ProductSearch.tsx`: debounced, abortable `/products` search.
- `components/Negotiation.tsx`: a reducer from SSE events to supplier cards.
- `lib/format.ts`:
  - `reasonText(code, ctx)` turns every gate, guard and proof code into a plain sentence with numbers when known, e.g. "QuickStock asked for 50% advance; your limit is 20%".
  - `maskVpa` and `maskVpasIn` mask UPI IDs.
  - `paymentState` reads legacy `settled` and `payment_claimed` as `claimed`.

**States on every screen.** Loading (skeletons), empty, error with retry, disabled, success. Double-submit protection uses a ref guard plus busy buttons. There is a skip link, `aria-current` on tabs, `aria-live` on streaming areas and labelled inputs. Layout holds at 360px: long names wrap with `overflow-wrap:anywhere`, and money and pills never overflow.

## Screen-by-screen decisions

**Sign-in (AuthGate).**
- A short value statement and two reassurance lines (limits are signed with your identity; nothing is bought without approval).
- "Continue with Google" has a busy state.
- A note tells judges that Trust, Attack and Savings need no sign-in.

**Home (`/`).**
- Shop name, a one-line value statement ("Restock in minutes, inside limits you sign.") and the primary **New restock** button.
- A **Continue** card:
  - "Your approval is needed", linking to `/confirm`, when `pending_confirmation_id` is set;
  - otherwise the active negotiation's status in plain words, linking to the mandate and to the record.
- Recent orders show honest pills: Waiting for your payment, Payment claimed (not bank-verified), Payment did not match, Supplier accepted, Supplier accepted part of the order, Order sent and awaiting supplier, Cancelled.
- First-run empty state with an example request.
- A four-step "How Sauda works".
- **Emergency stop**: "Pause Sauda" (`POST /shops/{shop}/kill-switch`) with an inline confirmation and "Resume Sauda". A 403 on the shared demo shop is explained.

**Restock: chat and draft (`/restock`).**
- The chat-driven flow is kept, with example chips and a composer. The textarea auto-grows; Enter sends and Shift+Enter adds a new line.
- The voice agent's `VoiceCapture` sits in the composer (dynamic import from `@/components/voice`, client-only). Its transcript is sent as the chat message.
- The draft card, "Check your restock":
  - Each line is at most about 3 rows: name and pack with small Replace and Remove icon buttons; stepper with "(you said)", "(default)" or "(suggested)" and the line total; ceiling with source and date, plus a small "Suggested 11 · apply" chip.
  - One festival banner sits at the top ("Diwali suggestion: +10–33% on 5 items (an assumption, not your history) [Apply all]"). Clarifications and low-confidence checks are one compact inline row of chips, which collapses once answered. The assumption note appears once, in the footer.
  - Stepper range is 1–5000. Replace and Add use product search.
  - Add item uses `/products` search.
  - "You said 10 · '10 atta 5 kg'" is shown separately from a dashed amber chip, "Suggested 11 (Diwali week +10% for staples, an assumption) [Tap to apply]". There is also "Apply all" and "Back to your 10".
  - With no number given, the line reads "You gave no number; Sauda used 10".
  - Low-confidence lines ask "Is this the right item?" with alternative chips.
  - Clarifications appear as a question with option chips; the current pick is ticked and choosing an option replaces that line.
  - Unmatched words are listed.
  - The stated budget ("You said: keep it under ₹24,000") and backend `budget_notes` are shown.
  - Each line shows its ceiling with its source and as-of date. Ceilings are explained as limits, not market prices.
- An HTTP 409 (another session is negotiating for this shop) shows as a friendly amber state with Try again, not as an error.

**Mandate review (in the draft, then `/mandate/[id]`).**
- Inputs: budget, up to 3 suppliers, maximum advance, deliver-by date and expiry.
- A live **Sauda MAY / MAY NOT** summary:
  - MAY: negotiate with these N suppliers, spend up to ₹X, pay at most each item's ceiling (table), ask for delivery by a date.
  - MAY NOT: pay an advance over Y%, pay anyone not registered or a payout account not on record, order or pay without approval, act after expiry.
- **Sign limits · ₹X** is guarded against double submit. Problems are listed before signing; a 422 `detail` is shown inline; a 409 gets a friendly message.
- The signed view repeats the summary and adds a status pill and **Start negotiating**.
- **Switch off these limits** (revoke) needs an inline confirmation.
- The KMS hash, signature and body are under Technical evidence.

**Live negotiation (`/restock?run=<mandate>`).**
- A "Comparing and negotiating" panel built from the SSE events (`offer`, `guard.verdict`, `gate.report`, `agent.tool`).
- A three-round stepper; rounds that were not needed are marked so.
- One card per supplier:
  - Name and the "Simulated distributor" label.
  - "Registered · verified" once rule R2 passes.
  - Opening and latest quote, advance asked and delivery days.
- Five distinct states, each with an icon, a label and a left border:
  - **Offer allowed** (green)
  - **Offer blocked** (red, with plain reasons)
  - **Quarantined** (purple, after two blocked messages: "Sauda stopped talking to QuickStock for this restock")
  - **Needs your approval** (amber)
  - **Not responding** (grey, with recovery text: "Sauda carried on with the others; you do not need to do anything")
- Rule codes and Model Armor filters are under evidence.

**Cart and approval (`/confirm/[id]`).**
- On desktop: lines on the left, a sticky summary on the right. On mobile: a single column with a sticky action bar.
- One block per winning supplier:
  - Lines with qty × unit price (opening price struck through).
  - "Under ceiling ₹X" pill.
  - **Why <supplier>** (from `cart.why`).
  - Ceiling source and date.
  - Delivery, advance and **Pays to** the masked payout account on record.
- Blocked suppliers and dropped lines are explained in plain words.
- Policy checks are grouped into **Failed**, **Needs your approval** and **Passed**, with rule IDs under evidence.
- Summary: total, budget used vs cap meter, savings below opening quotes, decide-by time, settlement caption.
- Approve and Decline are guarded against double submit. Approve is disabled if any check failed.
- HTTP 409 handling:
  - `cart_changed`: reload, then "The offer changed; review again".
  - `already_answered`: "You already answered this cart".
  - `negotiation_*`: "This restock is no longer waiting for approval".
  - 410: "This cart expired".
- A 200 response with `status:"denied"` shows the reasons.

**Order and payment (`/pay/[orderId]`).**
- An honest timeline:
  1. Purchase order sent.
  2. Supplier accepted (`po_status`/`po_ack`).
  3. Payment link issued.
  4. You reported payment ("Claimed by you with UTR …, Sauda has not verified this payment with the bank").
  5. Delivery: "Not tracked in this build".
- If the supplier has not accepted, the screen says "Supplier hasn't accepted the order; no payment requested" and shows no QR.
- UPI button and QR, with the masked payee and the payee name only.
- Test-payment disclosure: **"Test payment capped at ₹1.00"** (a token amount to a team member's UPI account on record, not the full order total) and "Test payment capped at ₹1.00 · order total ₹X".
- The owner types the amount actually paid (empty by default) and the UTR, so the check is not circular.
- Results:
  - `claimed`: recorded as a claim.
  - `invalid`: a form error.
  - `mismatch`: final, with problems such as `utr_reused` in plain words; the form is hidden.
- A legacy stored "settled" reads as "claimed".

**Orders (`/orders`).**
- The overview's `recent_orders` with the same honest pills.
- Empty state.
- A note that delivery is not tracked.

**Trust Console (`/trust/[id]`).**
- A big verification result:
  - "Verified: nothing in this record was changed", or
  - "This record does not verify (from event N)", or
  - "Could not verify right now" with retry.
- Event count and a signature status pill ("All signatures valid (Cloud KMS)").
- Signed-head status from `/verify`:
  - `head_ok` true: "Signed head matches (no events missing)".
  - `head_ok` false: the chain is shown as broken even when `first_broken_seq` is null, with plain text such as "Events are missing from the end of this record".
  - `head_ok` null: "No signed head (older record)".
- The per-event signature scope (v2 full event, or legacy) is shown in the evidence table.
- "What happened, step by step": one plain sentence per event (e.g. "QuickStock's message was blocked by safety screening") plus amounts and reasons. Failing events say why ("Changed: fingerprint does not match", "After the break: untrusted").
- **Test: change a value and watch the chain break**: a one-tap "Change one value (₹0.01)". The raw JSON editor is tucked under evidence. Results are explained in plain words, and the stored record is never touched.
- Messages with suppliers; blocked messages are marked "the AI never read it".
- The hash and link table is under evidence.

**Attack box (`/attack`).**
- "Passing these tests does not prove complete security." appears at the top.
- A scenario gallery from `GET /attack/scenarios`. Each card shows the attempt, the expected outcome and **Run this test**. The result shows:
  - the outcome ("Attack stopped", "Allowed (legitimate)", "Sent to owner for approval");
  - three separate layers: Model Armor, Policy checks, Signed record;
  - a plain explanation built from the first failing check (e.g. "Stopped by Policy checks: the supplier asked for 50% advance; your limit is 20%"). The server's own explanation, the raw checks and the ledger seq are under evidence.
- A 429 response shows a plain "wait" message.
- The free-text box is kept and shown in the same layered format.

**Savings (`/savings/[shop]`).**
- Saved against opening quotes.
- **How this is calculated**: opening quotes − negotiated price = difference (%), the baseline label from the backend, and realised savings (placed orders not cancelled).
- Tiles: ceiling compliance; unsafe messages blocked (split into supplier messages and security tests); phone time saved, with its assumption stated; scope ("This demo shop").
- Simulation disclosure and an explicit "not a market-wide or return-on-investment claim".
- Empty state.

**Other.**
- A not-found page.
- Security headers in `next.config.mjs` (SAUDA-029): CSP `frame-ancestors 'none'`, X-Frame-Options DENY, Referrer-Policy, nosniff, and Permissions-Policy (microphone for self only).

## Mock mode

`NEXT_PUBLIC_MOCK=1` serves fixtures from `lib/mock.ts` for every endpoint, including the new contract endpoints:
- overview
- products
- attack scenarios and runs
- the draft with suggestions, low confidence and clarifications
- a full negotiation with a quarantined supplier

Append `?mock=` to any URL to show other states:

| Value | State shown |
|---|---|
| `empty` | first run |
| `idle` | no active restock |
| `error` | overview fails |
| `busy` | chat returns 409 |
| `conflict` | confirm returns 409 `cart_changed` |

## Screenshots

All screenshots are in the session scratchpad under `pptr/ux/`, prefixed `m-` (390×844) or `d-` (1280×800).

- **Before:** `before/`, taken from the live https://saudaai.web.app: `signin`, `attack`, `savings`, `trust`.
- **After, mock mode:** `after/mock/`: `home`, `home-firstrun`, `home-error`, `restock-empty`, `restock-draft`, `restock-busy`, `negotiation`, `mandate`, `confirm`, `pay`, `orders`, `trust`, `trust-tamper`, `attack`, `attack-run`, `savings`.
- **After, local backend (shop `dev`, port 8082):** `after/live/`. A real end-to-end run: `home`, `restock-draft` (plus `restock-draft-bottom-viewport`, a viewport check that the Sign button clears the composer and tab bar), `mandate`, `negotiation`, `confirm`, `pay`, `pay-mismatch`. Also `orders`, `trust`, `trust-tamper`, `attack`, `attack-run`, `savings`, and `n360-mandate` (360px width). The 360px horizontal-scroll check passed on 7 routes.


## Pass 2 (18 Oct): persistent restock sessions, continuous voice, terminology

**Why.** A restock lived only in React state (`ChatStream`). Leaving `/restock`, refreshing, or signing in again
lost it. Voice stopped at 60 s and needed a second "Use this" confirmation. See `VOICE_CONVERSATION.md`.

**Routes**
- `/restock` is the history list: newest first, with title, status pill, item count, "up to" budget or total,
  updated time and "Needs a look". It has a **New restock** button, which always `POST`s a new session and never
  reuses or overwrites one, and is guarded against double taps.
- `/restock/[sid]` is the working session. It loads `GET /restock/sessions/{sid}`, so it survives refresh, back and
  forward, closing the browser and a new sign-in. An unknown or foreign sid shows "This restock was not found" with
  a link to all restocks (the backend returns 404).
- `/restock?run=<mandate>&sid=` keeps the existing live negotiation view (`ChatStream`) unchanged, plus a "Back to
  this restock" link.

**Working session (`components/restock/SessionView.tsx`)**
- **Header.**
  - The name is editable inline: blur or Enter saves it, Escape reverts.
  - The status pill.
  - The save indicator: **Saving…**, **Saved**, or **Couldn't save · Retry**. "Saved" appears only after a 2xx
    response.
  - "Started … · saved N min ago".
- **The list.** `DraftEditor` is the old `DraftCard`, made controlled. `DraftCard` remains as a thin wrapper for
  the chat.
  - Stepper, Replace, Remove, Add item, suggestions and clarifications are unchanged visually.
  - Every edit autosaves with `PATCH {version, lines}`, debounced by 600 ms.
  - Edits and turns go through one queue, so versions never race.
  - On 409 `version_conflict`, the page adopts the server copy and says so: "This restock was changed in another
    tab or device. Showing the latest saved version; check your last change."
  - Unsaved edits are flushed on unmount and before a turn, and `beforeunload` warns while a save is pending.
- **Conversation.**
  - A collapsible "Conversation (N)" holds the turns; spoken turns carry a mic icon.
  - The sticky composer holds Sauda's one-line reply (two lines at most), a clarification question with
    horizontally scrolling option chips, the "Did you say…?" box for low-confidence speech, a "Not applied yet ·
    Retry / Edit" box, `VoiceControl`, and the text box.
  - Changed lines are highlighted for about 2.5 s.
- **Review limits.**
  1. Saves, then calls `POST /restock/sessions/{sid}/prepare`.
  2. Shows the existing `MandateForm` (MAY / MAY NOT, Sign) with the suggested mandate and the `negotiation_id`
     from prepare.
  3. While the form is open, the list is read-only; "Edit the list" returns to editing.
  4. Signing goes to `/mandate/[id]?sid=`, then Start negotiating, `/restock?run=`, `/confirm` and `/pay`, all as
     before.
- **Read-only states** (negotiating, awaiting approval, ordered, completed, cancelled, failed):
  - The list is shown without controls.
  - A status card is read from `GET /negotiations/{nid}`: "Limits signed: ready to negotiate" (Start negotiating),
    "Sauda is negotiating" (Refresh status; the SSE is not replayed), "Your approval is needed" (Review and approve
    → `/confirm/{id}`), or "Ordered" (orders with honest payment pills → `/pay`).
  - Links to the signed limits and the signed record.
  - "Copy into a new restock".
- **Cancel** needs an inline confirmation and only appears while the session is editable.

**Home.**
- **New restock** creates a session.
- **Continue your restock** is the most recent resumable session (title, item count, money, status, Continue or
  Review and approve). When the overview has a pending confirmation, that card is shown first.
- **Recent restocks** lists the top 4, with See all.
- Then recent orders, how it works, and Emergency stop.

**Terminology.**
- "Demo" wording was removed from the ordinary product UI:
  - the Demo shop banners on Home and sign-in;
  - "Demo owner" (now "Shop owner");
  - "demo payment" (now "Test payment capped at ₹1 · order total ₹X");
  - "this demo shop" on Savings and Attack (now "this shop" / "a fixed test mandate").
- Kept on purpose: "Simulated distributor(s)" on supplier cards and in disclosures, "Payment claimed (not
  bank-verified)", "Delivery: not tracked in this build", and the "Sample data" pill shown only in mock mode.

**Mock mode additions** (`lib/mock.ts`):
- The session store is persisted to `localStorage`, so refresh-restore works in mock mode too.
- A small deterministic turn parser handles lists, set/remove/add-another, budget, sign/approve and ambiguity
  (clarification).
- Extra `?mock=` values: `slow` (PATCH takes 1.5 s, to show Saving…), `saveerr` (PATCH fails, for Couldn't save),
  `vconflict` (first PATCH gets a 409 with a changed server copy).
- `?voice=recorder` forces the recorder fallback.
- `?debug=1` shows the latency panel.

**Checked widths.** 360, 390, 768 and 1280 px on `/`, `/restock`, `/restock/[sid]`, a read-only session and
`/orders`, in mock mode. There was no horizontal scroll. Browser back and refresh restore were checked; see
TEST_PLAN §10.

**Screenshots** are in `scratchpad/pptr/ux2/`:
- `mock/` (390 px unless prefixed `n-` 360, `t-` 768 or `d-` 1280):
  - `m-home`, `m-home-sessions`, `m-history`, `m-session-empty`;
  - `m-session-clarification`, `m-session-mid-conversation`;
  - `m-save-saving`, `m-save-saved`, `m-save-error`, `m-save-conflict`, `m-refresh-restore`;
  - `m-review-limits`, `m-readonly-completed`, `m-awaiting-approval`, `m-not-found`;
  - `{n,m,t,d}-session` and `{n,m,t,d}-history`.
- `live/` (local backend :8092, shop `dev`):
  - `m-history`, `m-session-first-turn`, `m-clarification`, `m-session-mid-conversation`;
  - `m-save-saving`, `m-save-saved`, `m-save-conflict`, `m-refresh-restore`;
  - `m-review-limits`, `m-readonly-ordered`, `m-home`;
  - the bridge sequence `b1-draft`, `b2-limits`, `b3-mandate`, `b4-session-after-sign`, `b5-negotiation` and
    `b6-session-awaiting-approval`;
  - voice: `m-voice-partial`, `m-voice-low-confidence`, `m-voice-network-error`, `m-voice-denied`,
    `m-voice-recorder-listening` and `m-voice-recorder-after`.
