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
| `tn_businesses/{bid}` | `biz_*`, or `fx_*` for fixtures | Declared fields, `members`, `version` (for optimistic concurrency), `gstin_norm` and `name_pin_key` (duplicate detection), `contact` (masked only), `contact_hash` (HMAC), `requirements` (the seller's tiers) |
| `tn_checks/{check_id}` | random | One row for each source result: `dim`, `source_kind`, `status`, `fields[{field, declared, observed, match}]`, `checked_at`, `expires_at`, and `reviewer` on human-review rows |
| `tn_cases/{case_id}` | `case_<sha(bid, inputs_hash)>` | A verify run. The deterministic id makes the run idempotent |
| `tn_evidence/{eid}` | `ev_<sha256[:20]>_<bid suffix>` | `gcs_uri`, `sha256`, `mime`, `size`, `extracted`, `guard`, `reused_by_other_business`, `retention_until` |
| `tn_reviews/{tid}` | `rv_<bid>` | One task per business: `reasons`, `status` (open, needs_evidence, in_review, escalated, approved or rejected), and an append-only `decisions[]` |
| `tn_relationships/{rid}` | `rel_<sha(buyer, seller)>` | `state`, `provenance`, `requirements`, `approved_tiers`, `human_review`, `history[]` |
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

## Privacy and retention

- **Never stored:** Aadhaar numbers, OTPs, passwords and bank credentials.
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
- Firestore array-membership queries are used for "my businesses". The other lookups are equality queries on small collections.
