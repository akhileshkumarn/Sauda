# Trust Network: owner-app UX

This document covers the screens in `apps/owner-app` for business verification and the supplier network. The API contract is in `docs/TRUST_NETWORK.md`, and the sources are listed in `docs/VERIFICATION_SOURCES.md`.

## Principles

- **Say what was checked, by whom, and when.** Every result shows:
  - a status (a dot plus a word, never colour alone);
  - a source badge;
  - a checked-at time;
  - a field-by-field comparison of what was declared and what was observed.
- **Never overstate.**
  - A valid GSTIN is labelled "Format check only".
  - Verification is never called "legitimate".
  - The absence of public information is never presented as a warning.
- **Simulated data is unmistakable.** When `source_kind` is `simulated_fixture`, the result is shown as **Simulated (demo data)**:
  - The badge is dashed, violet and has a flask icon.
  - Any page showing such a result also carries a dashed "Simulated (demo data)" note at the top.
  - Fixture businesses (`is_fixture`) carry the same note.
- **No credit decisions.** "Approved for trading" means only that the seller accepts orders at the chosen tier. Every decision screen states that approval never grants credit or approves large orders. Credit, large-order and payment tiers always need a Sauda reviewer, and the backend returns 409 `human_review_required` for them.
- **No sensitive identity data.**
  - We never ask for Aadhaar, OTPs, passwords or bank logins.
  - Free-text fields refuse anything shaped like an Aadhaar number (12 digits).
- **Counterparties see redacted summaries only.** Documents, contacts and customer or supplier lists are never shown to them.

## Navigation

- A new **Network** tab sits between Orders and Trust. Its icon is the link glyph. The mobile tab bar now has five columns, set inline in `Nav.tsx`.
- **Review** appears only when `GET /review/queue` returns 200. It shows up as a "My network / Review" sub-tab strip inside the Network area, plus a row on `/network`.
- Home has one entry card. It reads "Verify my business" before onboarding, or shows the business name and its category afterwards.

## Screens

| Route | Purpose |
|---|---|
| `/network` | Your business card (category, next step, simulated note), then relationships grouped as Approved for trading, In progress and Invited (open invitations), then "Invite a supplier" and "Invite a buyer". With no business yet, it shows "Verify my business" and "Verify my supplier business". |
| `/network/onboard?role=buyer\|seller[&return=]` | A five-step guided flow (see below). Nothing is sent until the last step. The draft is kept in sessionStorage. |
| `/network/business/[bid]` | Verification for owners: the category headline in plain words plus the next step, then dimensions, outstanding checks with actions, documents (preview through a signed URL, or "Preview unavailable"), limitations, the record, and an audit trail drawn from the signed ledger. |
| `/network/business/[bid]/profile[?as=myBid]` | The redacted counterparty profile: who they claim to be, what is independently checked, what came from demo records, what is self-declared or pending, what is waiting for a reviewer, and "Meets your requirements?" for each tier (from the relationship's `readiness`), followed by limitations. |
| `/network/invite?role=seller\|buyer&bid=` | Invite several businesses at once (name, category, phone or email). Each share link is shown **once**, with a copy button and the message "Sauda does not send messages". A duplicate shows "Already invited; the link was shown when it was first created". Invitations are tracked by status, and an unopened one can be revoked. |
| `/invite/[token]` and `/network/invite/[token]` | The public landing page: "X invited you to trade on Sauda", then sign in, then accept by linking an existing business or verifying a new one (onboarding returns here). The backend's share links use the `/network/invite/` form. |
| `/network/relationships/[rid]?bid=` | The relationship timeline: invited, accepted, onboarding, under review, approved for trading (or declined or paused, with the reason). It also shows the decision panel. |
| `/review`, `/review/[tid]` | The reviewer console: queue and task detail (see below). |

### Onboarding steps

1. **Role and business.** Name, legal name, kind, business type, whether the business handles food, and whether it is GST registered.
   - **Required for this business type:**
     - GSTIN, if the business is registered;
     - CIN or LLPIN, only for companies and LLPs;
     - FSSAI, only for food businesses.
   - **Optional (helps suppliers trust you):** Udyam number, and brand claims for sellers.
   - Inline checks, each labelled "Format check only":
     - GSTIN pattern, state code and checksum;
     - state mismatch against the address;
     - Udyam, FSSAI, CIN and LLPIN patterns.
2. **Address.** Includes a PIN check that suggests the usual state and flags a mismatch. Location is optional and needs consent: tick the checkbox, then "Use my current location". The page explains that the reading is one-time and that the phone is not tracked. A refusal is handled calmly.
3. **Representative.** Name and role, plus the "never Aadhaar, OTP, passwords" notice.
4. **Products and categories.**
5. **Consent.** Separate consents for registry comparisons and for address checks. Storage-and-summary-sharing is required. Then it saves, sends the location if there is one, runs verification, and redirects.
   - A 409 `possible_duplicate` shows "This looks like an existing business" and offers "It is a different business, continue" (`confirm_not_duplicate`).
   - A 409 `gstin_already_registered` shows "Ask the owner to add you".

### Decisions

- **Only the seller approves.**
  - The seller picks a tier: small prepaid, regular prepaid, credit or large order.
  - The seller sees readiness for each tier from `relationship.readiness`.
- **The buyer** sees "Only the supplier approves trading with you", plus start review, pause and decline.
- **Every decision needs a reason** of at least 3 characters.
- **Error handling:**
  - 409 `requirements_not_met` lists the missing requirements in plain words.
  - 409 `human_review_required` explains that credit, payment and large-order terms are never automatic.
  - 403 `not_approver` and `version_conflict` each get their own message.

### Reviewer console

- **Queue:**
  - waiting and decided groups;
  - business name, buyer or seller, task status;
  - escalation reasons (`reason_text`);
  - age, plus a simulated badge on fixtures.
- **Task detail:**
  - why the task is here, and the recommended next action;
  - conflicting fields side by side (the declared value against the source or demo record);
  - a manual-check card: open the official portal in a new tab and type in what it shows (Sauda never scrapes);
  - checks done, with field-by-field comparisons, and what is still outstanding;
  - the declared record;
  - the decision panel: approve identity, approve a claim, reject a claim, request evidence, or escalate. Each needs a reason of at least 5 characters; a claim needs a scope (`claim:<check_id>`);
  - the audit history.

## States and accessibility

- **Every data view has four states:**
  - loading (skeleton);
  - empty (EmptyState with an action);
  - error (ErrorState with "Try again");
  - success.
- **Mock switches** (`NEXT_PUBLIC_MOCK=1`):
  - `?mock=error` forces errors;
  - `?mock=new` gives an empty network;
  - `?mock=missing` makes approval return 409;
  - `?mock=buyer` makes approval return `not_approver`;
  - `?mock=noreview` hides the reviewer.
- **Accessibility:**
  - Statuses are always shown as text.
  - Focus moves to the step heading on each onboarding step.
  - Validation messages use `aria-live`, alerts use `role="alert"`, and choice chips use `aria-pressed` or `aria-checked`.
  - Touch targets are at least 36 to 44 px.
- **Layout:** no horizontal scroll at 360 px; the 360 px check runs on every screen in both themes. Light and dark both use the existing tokens only. New styles are in `components/network/network.css`.

## Files

- `app/network/**`, `app/review/**`, `app/invite/[token]/**`
- `components/network/*` (`shared.tsx` holds the badges, the dimension list, the comparison table and the limitations)
- `lib/network.ts`, which contains:
  - the API client with mock fallbacks;
  - the words for every enum;
  - the format validators;
  - `useIsReviewer`.
- Sections appended to `lib/types.ts` and `lib/mock.ts`.
- Small edits to `components/Nav.tsx` (the tab and the reviewer sub-tabs) and `components/HomeView.tsx` (the entry card).
- `next.config.mjs`: the Permissions-Policy changes from `geolocation=()` to `geolocation=(self)`. Without it, "Use my current location" cannot work.

## Known gaps

- "Request manual review" has no dedicated endpoint. It re-posts `/verify` with `consents.manual_review = true`, and review tasks also open automatically when the policy finds review reasons.
- Signed preview links return 503 locally; the UI shows "Preview unavailable".
