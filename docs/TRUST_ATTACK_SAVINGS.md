# Trust area: Record, Security tests, Savings (plus Orders and Pay)

How the three Trust pages, Orders and Pay are organised, and the rules that keep them honest.
Built on the "Ledger" design system (`docs/DESIGN_SYSTEM.md`); screen styles are in the
`/* trust-network-orders screens */` block at the end of `app/globals.css`.

## One frame for every Trust page

Each Trust page opens with `TrustIntro` (`components/TrustIntro.tsx`):

1. `PageHead` title and a two-sentence description: **what this is** and **why it matters to the shop**.
2. A closed disclosure, "How to read this page", answering **what am I looking at**, **how was it
   obtained**, **what can I do** and **what if I ignore it**.
3. The value-first summary, then the evidence (progressive disclosure: raw data stays in `Evidence`).
4. `TrustLinks` at the bottom connects Record, Security tests, Savings and Network verification.

## Record (`/trust/[negotiationId]`, `components/TrustConsole.tsx`)

- Title "What Sauda did for you". If a cart is waiting, the one boxed decision on the page is a
  warn `Panel` with "Review cart" (links to `/confirm/{confirmation_id}` taken from the
  `confirmation.requested` event).
- Figures are `Stat`s with a basis line. The saving tile reads **Projected saving** until an order
  exists in the record, then **Saved**; it links to Savings.
- A blocked supplier lists the security test that exercises the same check
  (`GUARD_BLOCKED` → Hidden instructions, `ADVANCE_TOO_HIGH` → 50% advance demand,
  `PAYEE_MISMATCH` → Changed bank account, `SUPPLIER_UNKNOWN`, `OVER_BUDGET`, `GUARD_TIMEOUT`),
  linking to `/attack#sc-{id}`, which scrolls to and marks that row.
- "Is this record intact?" holds the verification badge for the **stored** record. The tamper
  test is titled "Try to break the record" with a "Test only" pill and says it changes a browser
  copy only.
- States: loading (intro plus skeleton), error with retry, an empty record, and the
  "which restock?" picker.

## Security tests (`/attack`, `components/AttackBox.tsx`)

- The description says these are **controlled tests on fixed input, not real incidents**.
- "Three layers" explains each layer and its nature: Model Armor is **probabilistic** (can miss or
  over-flag); the 12 policy rules are **deterministic**; the signed record detects edits.
- "Run all" plus a four-number tally (run, stopped, allowed, not as expected) announced through a
  live region.
- Each row has: title, an **impact-if-missed** label (High, Medium or Control), what was attempted,
  then after a run the outcome ("Stopped in this test"), **which layer and rule stopped it**, and an
  Evidence disclosure with every check and the test-record event number.
- The impact label is Sauda's own rating of what could go wrong if the trick got through. It is
  a design label, not a measured risk score, and is only shown for scenario ids we know.

## Savings (`/savings/[shopId]`, `components/MetricCards.tsx`)

- The main figure is **realised** savings (orders placed, not cancelled) when the server reports
  `realised_savings_paise`. Otherwise it is "Negotiated savings" with a note that realised and
  projected are not separated and the figure may include carts never ordered.
- Realised vs projected: projected = negotiated total minus realised, labelled "Not money saved yet".
- The calculation reads: opening quotes − negotiated price = difference. Baseline: each supplier's
  round-1 quote for the lines it won. Approximate (≈) values say how they were derived.
- **By restock**: recent orders grouped by negotiation. The saving comes from that negotiation's own
  signed `cart.assembled` event. If the record has none, the row says "No saving in its record".
  Each row links to its orders and its signed record. Without an owner session the row list
  asks the user to sign in.
- No ROI claims. Phone time saved is labelled as an estimate with its assumption.

## Orders (`/orders`, `components/OrdersView.tsx`) and Pay (`/pay/[orderId]`)

The status model has seven stages: **Draft → Proposed → Approved → PO sent → Payment link →
Payment reported (not bank-verified) → Delivery (not tracked)**.
`ORDER_STAGES` defines them; the "How an order moves" disclosure explains each one.

- A waiting cart (Proposed) or a draft restock appears above the list with its next action.
- Desktop and tablet (from 760px): a table with supplier, status pill, progress ("4/7 · Payment
  link"), amount, date and a 44px action ("Pay" when a link is waiting). Phone: a compact list.
- Pay: crumbs back to Orders, a "Simulated supplier" label in the reserved violet dashed style,
  the UPI button and QR, the UTR claim form, and a timeline that starts at "You approved the cart"
  and ends at "Delivery: not tracked".

## Network (`components/network/**`)

- Onboarding uses the shared `Steps` primitive. Every sensitive field has a "Why we ask" line
  (legal name, GSTIN, CIN or LLPIN, FSSAI, Udyam, address, representative).
- The business page puts "What you can do next" (the outstanding checks) first, as the one boxed
  decision, ahead of "What was checked".
- Source badges are unchanged. "Simulated (demo data)" stays violet and dashed with a flask icon.

## Demo-mode states

With `NEXT_PUBLIC_MOCK=1`, `?mock=error` and `?mock=empty` now also drive metrics, scenarios and
the record (`lib/api.ts`, mock branch only), so every screen's error and empty states can be reviewed.
