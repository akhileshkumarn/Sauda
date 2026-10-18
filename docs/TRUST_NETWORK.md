# Sauda Trust Network

The Trust Network lets a kirana buyer and a supplier check each other before they trade. Each side builds a verified business profile, invites trading partners, shares a redacted summary and decides, with a stated reason, whether to trade. Every step is deterministic, explained in plain English and written to the signed ledger.

The Trust Network does **not** give a trust score, a credit rating or a legal opinion. It never approves credit, payment terms or large orders by itself.

## Architecture

```
owner-app (Next.js)  ──►  buyer-agent FastAPI
                           └─ buyer_agent/trust_network_routes.py   /tn/*, /review/*
                                ├─ sauda_verify.policy     deterministic rules (pure functions)
                                ├─ sauda_verify.store      Firestore tn_* collections, CAS writes
                                ├─ sauda_verify.providers  source adapters (Provider protocol)
                                ├─ sauda_trust.guard       Model Armor screening of document text
                                ├─ GCS private bucket      evidence files, tn/<bid>/<eid>
                                └─ sauda_ledger            signed hash chain biz-<bid>
```

- **`packages/sauda_verify/models.py`** holds the enums (`Dim`, `CheckStatus`, `SourceKind`, `Category`, `RelState`) and the models (`Business`, `Check`, `FieldCompare`, `Summary`, `Readiness`).
- **`providers/base.py`** defines the interface. A provider has a `name`, a list of `dims`, `applicable(biz)` and `run(biz, ctx) -> list[ProviderResult]`.
  - The API turns each result into a `Check`.
  - A provider that raises becomes an `inconclusive` check with `available: false`. An outage is not a finding about the business.
  - `ctx["mode"]` is one of three values:
    - `verify`: consents are passed.
    - `evidence`: only the `documents` and `photo` providers run, and the uploaded bytes are passed.
    - `location`: only the `geocode` provider runs, and the device fix is passed.
- **`policy.py`** has no I/O. Given checks, the declared business and evidence metadata, it returns:
  - a status for each dimension;
  - the overall category;
  - the reasons for review;
  - readiness for a relationship;
  - the summary text.
- **`trust_network_routes.py`** handles access control, idempotency, the evidence pipeline, invitations, the relationship state machine, the review queue and the fixture seed. `main.py` includes it with one `include_router` line.

## Data model (Firestore, new collections only)

| Collection | Key | Notes |
|---|---|---|
| `tn_businesses/{bid}` | `biz_*`, or `fx_*` for fixtures | `listing {listed, categories, service_area {kind, districts, states, basis: self_declared}, min_order_paise, notes, updated_at}` (opt-in, sellers only). Declared fields, `members`, `version` (for optimistic concurrency), `gstin_norm` and `name_pin_key` (duplicate detection), `contact` (masked only), `contact_hash` (HMAC), `contact_hashes {phone, email}` (HMAC per declared kind, for contact OTP matching), `requirements` (the seller's tiers) |
| `tn_checks/{check_id}` | random | One row for each source result: `dim`, `source_kind`, `status`, `fields[{field, declared, observed, match}]`, `checked_at`, `expires_at`, and `reviewer` on human-review rows |
| `tn_cases/{case_id}` | `case_<sha(bid, inputs_hash)>` | A verify run. The deterministic id makes the run idempotent |
| `tn_evidence/{eid}` | `ev_<sha256[:20]>_<bid suffix>` | `gcs_uri`, `sha256`, `mime`, `size`, `extracted` (masked), `contact_hashes` (HMACs of any phone/email the document extraction returned), `guard`, `reused_by_other_business`, `retention_until` |
| `tn_reviews/{tid}` | `rv_<bid>` | One task per business: `reasons`, `status` (open, needs_evidence, in_review, escalated, approved or rejected), and an append-only `decisions[]` |
| `tn_relationships/{rid}` | `rel_<sha(buyer, seller)>` | `state` (adds `requested`), `provenance` (adds `discovery_request`), `requirements`, `approved_tiers`, `human_review`, `history[]`, and `request {message, message_blocked, guard, categories, at}` for discovery requests |
| `tn_invitations/{iid}` | `inv_<sha(from_bid, contact_hash, role)>` | Stores `token_hash` (sha256) and `contact_masked`. Never stores the token or the raw contact |

Every state change is also appended to the existing signed ledger under the chain `biz-<bid>`. Emails and phone numbers are masked before writing, and VPAs are masked by the existing ledger adapter. `GET /tn/businesses/{bid}/ledger` returns the events with their hash, link and signature verification.

## Policy methodology

The policy is deterministic. The same checks always give the same result, and every result can be traced to a named source and a stated rule.

### Dimensions

The dimensions are identity, registration, address, operational, representative, product compliance, distribution authority, trading references, payment details and operational capability.

### Source strength

Sources rank as follows, strongest first:

1. human review
2. official registry
3. authorised provider
4. uploaded evidence
5. device signal
6. preliminary validation
7. self-declared
8. simulated fixture

### Dimension rollup

Each dimension's status comes from its checks:

1. **Staleness:** a check past its `expires_at` becomes `stale`. Negative findings do not expire.
2. **Supersession:** a newer human-review check on a dimension replaces the older automated checks on that dimension. This is how a reviewer resolves a discrepancy.
3. **Conflicts first:** among the remaining checks, `conflict` dominates everything, then `failed`.
4. **Positive results:** otherwise, the positive check (`verified` or `partially_verified`) from the strongest source wins.
5. **Fallback:** if there is no positive check, the status shown is the first present in this order: pending, inconclusive, self-declared, stale.

### What counts as evidence

- **Identity and registration** need an official registry, an authorised provider or a human reviewer. A valid GSTIN format or checksum (`preliminary_validation`) never confirms identity.
- **Other dimensions** also accept uploaded evidence and device signals.
- **Simulated fixtures never count as evidence**, whatever status they show. On a fixture business, any registry-like provider result is relabelled `simulated_fixture`.

### Overall category

The first matching rule applies:

1. A reviewer rejected identity, registration or representative: **verification_unsuccessful**.
2. Identity, registration or representative is in `conflict` or `failed`: **additional_review_required**.
3. Identity is not verified by a confirming source: **additional_review_required**.
4. Registration, address and representative are all evidenced, with no conflict and no open review reason: **ready_for_counterparty_review**.
5. Some non-identity dimension has been confirmed by a reviewer or uploaded evidence: **evidence_reviewed**.
6. Otherwise: **identity_confirmed**.

### Review routing reasons

Any of these reasons puts a business in the review queue. A reason drops out when a newer human-review check supersedes the check that raised it.

| Reason | Raised when |
|---|---|
| `conflict` | Two sources disagree on a key detail. |
| `failed` | A check did not pass. |
| `field_mismatch` | A declared detail differs from the source, for example a spelling difference in the trade name. |
| `registration_cancelled` | The source shows a registration as cancelled, suspended or inactive. |
| `representative_authority_unknown` | The person acting for the business has not shown authority to do so. |
| `location_inconclusive` | The device location could not be matched to the declared address. |
| `suspicious_document` | Model Armor blocked an upload, or the same file was used by another business. |
| `brand_authorisation_unconfirmed` | A claimed brand distributorship has not been confirmed. |
| `source_unavailable` | A source could not be reached when checked. |
| `high_value_relationship` | Credit, payment or large-order terms were requested. |

### Relationship readiness

Readiness is evaluated against the seller's requirement tiers. The defaults are:

| Tier | Requirements |
|---|---|
| `prepaid_small` | identity, registration |
| `prepaid_regular` | identity, registration, address |
| `credit` | identity, registration, address, representative, trading references, `human_review` |
| `large_order` | identity, registration, address, representative, `human_review` |

A tier containing `human_review`, or named for credit, payment, large or bulk orders, is always flagged for a person. `POST /tn/relationships/{rid}/decision` refuses to approve it (409 `human_review_required`). Approving it is the seller's commercial decision outside Sauda.

### Summary output

`GET /tn/businesses/{bid}/summary` returns:

- `category` and `category_label`;
- `dimensions`;
- `outstanding`: plain-English items still to do;
- `limitations`, which always state that there is no score and that a valid GSTIN alone proves little. They also flag demo data and device-location caveats when they apply;
- `next_step`;
- `review_reasons`.

## Access rules

| Who | Can do |
|---|---|
| Members of a business (`members[]`) | Full record, summary, checks, evidence, ledger. Edit with `version` (optimistic concurrency, 409 `version_conflict`) |
| Counterparty (a business with a non-declined relationship) | `GET /tn/businesses/{bid}/profile` only. This is the redacted profile: display name, city and state, PIN prefix, masked GSTIN, representative role and authority status, and dimension statuses without free text. It never includes documents, contacts, members or the street address |
| Reviewers (`REVIEWER_UIDS` / `REVIEWER_EMAILS`, or the operator token) | Everything, plus `/review/*` |
| Operator token | Reviewer rights and `POST /tn/fixtures/seed`. With `X-Act-As: fx-user-*` it acts as a fixture user, and loses reviewer rights while doing so. It can never act as a real uid |
| Anyone else | 404. Existence is not leaked |

## Review workflow

1. `verify`, an evidence upload or a location post re-evaluates the policy. If there are reasons, the business's task `rv_<bid>` is opened or refreshed.
2. Reviewers see `GET /review/queue`, with reasons in plain English, and `GET /review/tasks/{tid}`, which returns the business, summary, checks, evidence metadata and relationships.
3. A reviewer posts `POST /review/tasks/{tid}/decision` with `{action, scope, reason}`. A reason of at least 5 characters is required.

| Action | Scope | Effect |
|---|---|---|
| `approve_identity` | `identity` | Adds a human-review `verified` identity check |
| `approve_claim` | `claim:<check_id>` | Adds a human-review `verified` check on that check's dimension. For a representative claim, it also sets `authority_status: verified` |
| `approve_claim` | `relationship:<rid>` | Records that a person reviewed the relationship terms. It does not change the relationship state |
| `reject_claim` | `claim:<check_id>` | Adds a human-review `failed` check on that dimension |
| `reject_claim` | `relationship:<rid>` | Records that a person reviewed the relationship terms and did not approve them |
| `request_evidence` | any | Sets the task to `needs_evidence` |
| `escalate` | any | Sets the task to `escalated` |

Each decision is appended to `decisions[]` with a keyed hash of the reviewer and written to the ledger. The task status is then recomputed: `approved` when no reasons remain, `rejected` when the result is unsuccessful, otherwise `in_review`.

Approving identity never approves a relationship. A relationship is approved only by the seller, against readiness.

## Invitation and relationship flow

1. **Invite:** `POST /tn/invitations {from_bid, role_invited, contact, categories}`.
   - The contact is normalised (emails lowercased, mobile numbers reduced to 10 digits), then HMAC-hashed and masked.
   - The token is `secrets.token_urlsafe(24)`. Only its sha256 is stored.
   - The token and share link are returned **once**. Repeating the request for the same `(from_bid, contact_hash, role)` returns the existing invitation with `duplicate: true` and no token.
   - Invitations expire after 14 days, and `POST /tn/invitations/{iid}/revoke` cancels one.
2. **Public preview:** `GET /tn/invitations/{token}` returns only the inviter's display name and city, the role, categories, status and expiry.
3. **Accept:** `POST /tn/invitations/{token}/accept {bid}`. The caller must be a member of a business with the invited role. The relationship `rel_<sha(buyer, seller)>` is created with history `invited → accepted → onboarding`. Accepting again is idempotent, and another business gets 409 `invitation_used`.
4. **Decide:** `POST /tn/relationships/{rid}/decision {action, reason, tier?, version?}`.
   - `approve_for_trading` is for seller members only. It goes `onboarding → under_review → approved_for_trading` and adds the tier to `approved_tiers`. It returns 409 `requirements_not_met` with `missing`, or 409 `human_review_required`.
   - `pause`, `decline`, `start_review` and `resume` are open to either side.
   - The allowed transitions are explicit (`TRANSITIONS` in the routes module). Anything else returns 409 `invalid_transition` with the allowed targets.
5. **Readiness:** `GET /tn/relationships?bid=` returns, for the seller side, readiness for each tier.

## Demo scenario

`POST /tn/fixtures/seed`, with the operator token only, creates the scenario. Add `?reset=true` to delete fixture documents first.

- Everything is `is_fixture: true` and labelled simulated. Fixture ids start with `fx_`.
- Registry-like data is `simulated_fixture`, and its summaries end with "(simulated demo data, not a real registry result)".
- The fixture GSTINs are well formed but deliberately fake: their PAN part starts with `ZZ`.
- Running the seed twice creates nothing new, because the ids are deterministic and the writes are create-only.

| Business | Fixture user | Scenario |
|---|---|---|
| Sri Lakshmi General Stores (buyer, Hyderabad 500016) | `fx-user-srilakshmi`, also `demo-owner` | The trade name differs ("Sri Laxmi General Store"), so identity is `partially_verified` and goes to review. Representative authority is pending. A device signal is near the address |
| Annapurna Rice Traders (rice wholesaler) | `fx-user-annapurna` | Clean simulated records |
| Deccan Edible Oils (distributor) | `fx-user-deccan` | Claims Fortune brand authorisation, so `distribution_authority` is pending human review |
| Metro Distributors | `fx-user-metro` | Linked to the existing simulated supplier `metro`. The relationship is `accepted`, with provenance `self_declared` |
| Pune Dry Fruits & Spices Co. (Pune 411002, Maharashtra) | `fx-user-pune` | Clean simulated records. Listed for Pune district only |
| Bengaluru Home Care Supplies (Bengaluru 560068, Karnataka) | `fx-user-blr` | Clean simulated records. Listed for all of Karnataka |

All five fixture sellers are listed in Find suppliers with simulated, self-declared service areas: Annapurna (Hyderabad district; staples, rice), Deccan (Telangana; edible oil), Metro (all India; FMCG, staples, packaged foods, personal care), Pune Dry Fruits (Pune district; dry fruits, spices) and Bengaluru Home Care (Karnataka; cleaning, personal care). A seed over fixtures created before listings existed adds the listing once (`listings_added`); later edits are kept.

## Supplier discovery (Find suppliers)

Buyers find suppliers who chose to be listed, check how far each one is verified, and ask to connect. The routes live in `buyer_agent/trust_network_discovery.py`, registered on the same router.

### Listing (opt-in, sellers only)

`PUT /tn/businesses/{bid}/listing {version, listed, categories, service_area: {kind, districts, states}, min_order_paise?, notes?}`

- Members only, and the business must have the `seller` role (otherwise 403 `seller_role_required`). Optimistic `version`, 409 `version_conflict`.
- `service_area.kind` is `district`, `state` or `pan_india`. Districts and states are validated against the data.gov.in PIN directory (`data/pincodes`) and stored in its upper-case spelling; a district's state is filled in from the directory. Unknown names return 422 `invalid_area` with `invalid: [...]`.
- The service area is stored with `basis: "self_declared"`, and every card labels it "(self-declared)". Sauda does not check delivery coverage.
- `categories` are lower-cased (max 12, one required when listed). `notes` are at most 200 characters, with phone numbers and emails masked.
- Each change writes `tn.listing.updated` to the business's ledger chain. The response includes `card`, the exact card buyers will see.
- Helpers: `GET /tn/areas` (states and districts from the directory) and `GET /tn/listing-categories`.

### Discovery

`GET /tn/discover?bid=&q=&category=&scope=district|state|india&district=&state=&verified_only=true&limit=20&cursor=`

- **Who:** the caller must be a member of a business with the `buyer` role, otherwise 403 `buyer_profile_required` (the app sends them to onboarding). `bid` picks one of several buyer businesses.
- **Default area:** the buyer's district and state come from its declared PIN via the PIN directory (the district matching the declared city when a PIN spans two).
- **Scopes:**
  - `district`: sellers whose area covers the district: the district itself, the whole state, or all India.
  - `state`: sellers covering any district of the state, the whole state, or all India.
  - `india`: every listed seller.
- **`verified_only` (default true):** keeps sellers whose category is `identity_confirmed`, `evidence_reviewed` or `ready_for_counterparty_review`. A real business is judged by the unchanged policy. A fixture is judged only by its own simulated results (treated as registry results for this filter), its `category_text` ends "(simulated demo data)", and its card has `is_fixture: true` and `fixture_label: "Simulated (demo data)"`. Simulated results still never satisfy relationship readiness.
- **Ranking:** delivers to the buyer's district first, then the strength of the category (ready > evidence reviewed > identity confirmed), then most recently checked, then name. Never price or quality; the response carries `sort_note: "Sorted by delivery area and verification status, not by price or quality"`.
- **Card:** `bid, display_name, city, district, state, categories, service_area {kind, districts, states, basis, label}, min_order_paise, notes, delivers_to_viewer, trust {category, category_text, dims [{dim, label, status, source_kind}]}` for identity, registration, address, operational, representative and distribution authority, `last_checked_at, is_fixture, fixture_label, connection (none | requested | connected | declined), rid`.
- **Never in a card:** GSTIN (not even masked), contacts, the address line or PIN, members, documents, evidence, customers or relationships with other businesses.
- Unlisted businesses never appear. Pagination is an opaque offset `cursor`; `next_cursor` is null on the last page.
- Rate limit: 60 requests a minute per user (429 `rate_limited`).

### Request to connect

`POST /tn/connect {from_bid, to_bid, categories, message?}`

- `from_bid` must be the caller's buyer business (403 `buyer_profile_required`), and `to_bid` a listed seller (404 otherwise).
- Creates `rel_<sha(buyer, seller)>` in the new state **`requested`**, with `provenance: "discovery_request"` and `initiated_by_bid` set to the buyer. Categories are limited to those the seller lists.
- **Idempotent per (buyer, seller):** if any relationship exists for the pair (from an invitation, a request or a decline), it is returned with `duplicate: true`.
- At most 20 new requests per buyer business per day (429 `rate_limited`).
- The message (at most 300 characters) is untrusted text. It is screened with the existing Model Armor guard and the verdict is stored in `request.guard`. A blocked message is not stored (`message: null, message_blocked: true`); phones and emails in a clean message are masked.
- Writes `tn.relationship.requested` to both businesses' ledger chains.

### Seller handling

- The seller sees requests in `GET /tn/relationships?bid=` (state `requested`).
- `POST /tn/relationships/{rid}/decision`:
  - `{action: "accept_request", reason}` moves `requested → accepted → onboarding`;
  - `{action: "decline", reason}` moves `requested → declined`.
  - Only seller members may act on a `requested` relationship (403 `not_approver`).
- New transitions: `requested: {accepted, declined}`. Nothing else leaves `requested`, so a request can never jump to `approved_for_trading`.
- After acceptance the existing onboarding, review and approval flow applies unchanged: `prepaid_small` still needs identity and registration confirmed by a confirming source or reviewer, and credit and large orders still need a person (409 `human_review_required`).
- While a request is open, both sides can read each other's redacted profile (the same `GET /tn/businesses/{bid}/profile` rules), which is what "your redacted trust profile is shared" means in the app.

## Buying and selling (role switch)

A business can be a buyer, a seller or both. Members change this with `PATCH /tn/businesses/{bid} {version, roles}`.

- Members only, with the optimistic `version` (409 `version_conflict`). `roles` cannot be empty (422 `role_required`).
- Each change writes `tn.business.role_added` or `tn.business.role_removed` to the ledger, next to `tn.business.updated`.
- **Existing checks are reused.** Identity, registration, address and representative checks are not run again.
- **Only the newly applicable checks run**, through the same provider path as verify. Adding `seller` runs:
  - the payout bank check (`bank_account_validation`, pending until a penny-drop provider is enabled);
  - a `brand_authorisation_claim` row when brands are claimed and none exists yet;
  - a listing eligibility result (`role_change.listing_eligibility`): the business can list in Find suppliers, and is shown to buyers who keep "verified only" on once its identity is confirmed.
- Adding `buyer` adds no checks.
- **Idempotent:** the run has the case id `case_role_<sha(bid, role, declared inputs)>`. Adding the same role again returns the same rows.
- **Removing a role** is refused with 409 `role_in_use` (with `role` and `relationships`) while any relationship that is not declined has the business on that side. Removing `seller` also unlists the business from Find suppliers.
- The response is the business plus `role_change {added, removed, new_checks, listing_eligibility}`.
- In the app, `components/network/RoleSwitch.tsx` on the business page has the two toggles ("I buy for my shop", "I sell to other businesses"), an explanation, a confirm step and the result.

## Business contact verification (phone or email one-time code)

This shows that a member controls the business phone or email. **It does not show legal authority to act for the business.**

### Flow

1. The app (`lib/contactOtp.ts`, `components/network/ContactVerify.tsx`) creates a **second Firebase app instance** (`initializeApp(config, "sauda-contact-verify")`, in-memory persistence). The owner's Google session on the default app is never replaced.
   - **Phone:** an invisible reCAPTCHA and `signInWithPhoneNumber` on the second auth instance, then the SMS code.
   - **Email:** `sendSignInLinkToEmail` with the return URL `/network/business/{bid}/verify-contact`, then `signInWithEmailLink` on return.
2. The app sends that session's ID token: `POST /tn/businesses/{bid}/contact/verify {kind: "phone"|"email", id_token}`. It then signs the second session out.
3. The API verifies the token with `firebase_admin` (same Firebase project) and checks that it is recent (signed in within 15 minutes).
   - Phone: reads `phone_number`. Email: reads `email` and requires `email_verified: true` (otherwise 422 `email_not_verified`).
   - The value is normalised (10-digit mobile, lower-case email). **Only a keyed hash and a masked value are stored.** The raw value never reaches Firestore or the ledger.
4. The API deletes the temporary Firebase user (`auth.delete_user`), so no stray accounts remain. It never deletes the owner's own account, or an existing account that already had the number or email with another sign-in method or was created more than an hour earlier. The outcome is in `temp_user`.

### Check recorded

- dim `representative`, check_type `business_contact_otp`, source_kind `authorised_provider`, source_name "Firebase Authentication OTP", status `partially_verified`.
- Summary: "Controls the business {phone|email} {masked}. This shows access to the business contact, not legal authority to act for the business."
- **Declared contact:** when a phone or email was declared at creation, its keyed hash is compared. A match is noted in the summary and fields. A mismatch makes the check `inconclusive` and raises `field_mismatch` for a reviewer.
- **Documents:** a phone or email extracted from an uploaded GST, Udyam or FSSAI document is compared the same way. Today's document extraction does not return contacts, so this comparison applies only when it does.
- Ledger event `tn.contact.verified` (masked value, status, match flags). Limited to 5 attempts an hour per business (429 `rate_limited`).

### Policy

- A contact code **never** makes representative verified. `business_contact_otp` rows are capped at `partially_verified`, never satisfy the representative dimension (for categories or readiness tiers), and `representative_authority_unknown` stays until a reviewer confirms authority or authority evidence is uploaded.
- Another positive representative check (an uploaded authorisation document or a reviewer's decision) always takes precedence over the contact code.
- The `contact` provider's pending row now points to this flow when Firebase is the sign-in (`AUTH_MODE=firebase` or `CONTACT_OTP=firebase`).

### When the providers are off

Until Phone and Email-link sign-in are enabled in Firebase, `auth/operation-not-allowed`, `auth/configuration-not-found` and `auth/admin-restricted-operation` show "Phone/email verification isn't switched on yet", and the check stays pending.

## GST registration providers (Cashfree, Setu)

`providers/gst_registry.py` calls an authorised provider when its credentials are present. Otherwise it creates a manual task. Cashfree is tried first.

| Provider | Env | Call |
|---|---|---|
| Cashfree Verification Suite | `CASHFREE_CLIENT_ID`, `CASHFREE_CLIENT_SECRET`, `CASHFREE_ENV=sandbox\|production` | `POST https://sandbox.cashfree.com/verification/gstin` (or `api.cashfree.com`), headers `x-client-id`/`x-client-secret`, body `{GSTIN, business_name}`. Reads `gst_in_status`, `legal_name_of_business`, `trade_name_of_business`, `principal_place_split_address.pincode`, `reference_id`, `valid` |
| Setu | `SETU_CLIENT_ID`, `SETU_CLIENT_SECRET`, `SETU_PRODUCT_INSTANCE_ID`, `SETU_ENV` | `POST https://dg-sandbox.setu.co/api/verify/gst` (or `dg.setu.co`). The response mapping is defensive and must be confirmed against Setu's docs when credentials are issued |

- **Sandbox** (the default) returns the provider's sample data. Rows are labelled e.g. "Cashfree GST verification (sandbox: sample data)" and capped at `inconclusive`, so sandbox data never counts as verified or as a conflict.
- **Production** compares the record with the declared details: Active with matching names and PIN gives `verified`; an inactive status or different names gives `conflict`; a spelling near-match gives `partially_verified` for a reviewer.
- `scripts/check_gst_provider.py [GSTIN]` loads `.env`, forces sandbox, makes one call and prints only status fields. It never prints credentials.

## DigiLocker (future)

Not built.

- Which documents DigiLocker issues **to businesses** (as opposed to individuals), and whether GST or Udyam certificates are available that way, is UNVERIFIED.
- A requester must onboard through API Setu partner registration before any pull is possible. Sauda has not done this.
- Until both are settled, DigiLocker is not used, and nothing in the Trust Network claims a DigiLocker result.

## Privacy and retention

- **Never stored:** Aadhaar numbers, OTPs, passwords and bank credentials. Contact codes are handled by Firebase Authentication; Sauda keeps only a keyed hash and a masked copy of the confirmed contact, and deletes the temporary Firebase user.
- **Contacts:** stored masked, plus an HMAC for matching. Raw invitation contacts are not stored.
- **Evidence files:** go only to the private bucket at `tn/<bid>/<eid>`. A signed link valid for 10 minutes is issued to members and reviewers. Counterparties never get documents.
  - Each evidence row has `retention_until`, set to 365 days after upload. Deletion is an operational job and is not automated yet.
  - The same file re-uploaded by the same business is deduplicated. A file already used by a different business is flagged for review.
- **Document text is untrusted data.** Model Armor screens it, and instructions inside documents are never followed.
- **Location** is stored only with explicit consent, rounded to 5 decimal places.
- **Ledger payloads** are masked when written, so the hash covers the masked data.

## Limitations

- Where no authorised API exists, a check is a guided manual review by a person, with the source link and the evidence attached. Sauda does not bypass CAPTCHAs or scrape restricted portals.
- The demo uses simulated fixtures. They are clearly labelled and can never reach a confirmed status.
- Missing public information is not treated as a sign of fraud.
- Device location shows where a phone was, not who owns the premises.
- The review task is one per business. Relationship-level reviews are recorded on the relationship (`human_review`), not as separate tasks.
- Counterparty access is read-only and redacted. Field-level sharing preferences (`shared_fields`) are stored but not yet configurable.
- Discovery loads listed sellers with one equality query on `listing.listed` and filters in memory. This is fine for the pilot; a larger directory needs per-state indexing.
- The discovery, connect and contact-verification rate limits are per process (in memory), like the existing owner limits.
- Service areas are self-declared and not checked against actual deliveries.
- Firestore array-membership queries are used for "my businesses". The other lookups are equality queries on small collections.
