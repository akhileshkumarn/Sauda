# Verification sources (India): research notes for the Trust Network

Researched 18 Oct 2026. Scope: India only. Each claim is tagged **VERIFIED** with a URL, or **UNVERIFIED**. "VERIFIED (probe)" means we confirmed it by calling the endpoint ourselves on 18 Oct 2026. "VERIFIED (secondary)" means a reputable non-government page states it, but we could not open the official page, usually because it is a JavaScript single-page app or blocks bots.

Product rules that apply throughout:

- No CAPTCHA bypass.
- No scraping of restricted portals.
- No impersonation.
- Where no authorised API exists, the check is a guided **manual** check with a source link, reviewer fields, an evidence attachment and an audit entry.
- A valid GSTIN format or checksum is `preliminary_validation` only. It never makes a business "legitimate".

---

## 1. Summary table

Column key:

- **Src kind**: the `source_kind` emitted by the adapter.
- **Decision**: **NOW** = integrate now; **ADAPTER** = build an adapter behind a feature flag for a later contract; **MANUAL** = guided manual fallback.

| Source | Purpose | Coverage | Access method | Authentication | Cost | Freshness | Limitations | Decision |
|---|---|---|---|---|---|---|---|---|
| GSTIN format + mod-36 checksum (local) | Catch typos and fabricated GSTINs before any lookup | Regular-taxpayer GSTINs (14th char `Z`) | Local code | None | Free | n/a | Proves nothing about registration, status or ownership | **NOW** (`preliminary_validation`) |
| GST Portal "Search Taxpayer" (services.gst.gov.in/services/searchtp) | Human lookup of legal name, trade name, status, address, filing table | All GST registrants | Web UI only | CAPTCHA before login | Free | Live | CAPTCHA, so it must not be automated. No public API on this page | **MANUAL** (reviewer opens link, records fields and a screenshot) |
| GSTN Public API "Search Taxpayer" (via a GSP) | Machine lookup of the same public fields | All GSTINs | REST `GET /commonapi/v1.3/search?action=TP&gstin=` through a GSP | GSP client id/secret + ASP token/signature | Per-call GSP pricing on contract. Sandbox free (secondary) | Live (`lstupdt` field) | Only GSPs, plus large taxpayers going direct, can call GSTN. Commercial contract needed | **ADAPTER** (via authorised provider) |
| E-invoice IRP "Get GSTIN Details" | Name, address, status, blocked status of a GSTIN | All GSTINs | IRP API | IRP credentials (e-invoice-enabled taxpayer or GSP) | Free to eligible users | Live | Only for e-invoice-enabled taxpayers above the turnover threshold, or GSPs. A kirana buyer is unlikely to qualify | **ADAPTER** (later; only via GSP) |
| Authorised providers: Cashfree, Setu, Signzy, IDfy, Perfios/Karza, Razorpay | GSTIN, PAN, MCA, Udyam, FSSAI, bank account | Pan-India | REST | client id/secret | Contract / per call | Live (proxy to GSTN/registries) | KYC/commercial onboarding. Sandbox data is synthetic | **ADAPTER** (Cashfree or Setu first) |
| MCA "View Company/LLP Master Data" (MCA21 V3) | Company/LLP name, status, address, directors | All companies/LLPs | Web UI | CAPTCHA | Free | Live | CAPTCHA. No official public API found | **MANUAL** |
| data.gov.in "Registrars of Companies (RoC)-wise Company Master Data" | Machine lookup of company name/status/address by CIN | Companies (LLP coverage unverified) | `api.data.gov.in` REST | data.gov.in API key | Free | Updated 13 Oct 2026 (probe) | No directors. No LLPs confirmed. Lag of weeks. Only covers companies, which few kiranas are | **NOW** (`official_registry` open data, labelled with dataset date) |
| Udyam verification (udyamregistration.gov.in) | Confirm MSME registration | Udyam-registered MSMEs | Web UI | CAPTCHA (secondary) | Free | Live | No official public API found | **MANUAL** + certificate upload (Gemini extraction) |
| FSSAI FoSCoS FBO search | Confirm food licence or registration | FSSAI licensees/registrants | Web UI (SPA) | CAPTCHA presence UNVERIFIED | Free | Live | No official public API found | **MANUAL** + licence upload; local format check NOW |
| GeM seller | Government-procurement seller status | GeM sellers | Logged-in portal only | GeM login | n/a | n/a | No public seller lookup found | **Not used** (optional self-declared) |
| data.gov.in All India Pincode Directory | Validate PIN ↔ state/district; rough centroid | All Indian PINs | `api.data.gov.in` REST | data.gov.in API key | Free | Resource updated 3 Oct 2025 | Lat/lng quality varies by office; PIN centroid only | **NOW** (`official_registry`) |
| Google Geocoding API | Address → lat/lng for the location check | India covered | REST | API key | India: 70k free/month, then $1.50 per 1000 | Live | Approximate for informal addresses | **NOW** (if key present; else skip → `inconclusive`) |
| Google Address Validation API | Address normalisation | India is in **preview** | REST | API key | India Pro: 35k free, $5.10 per 1000 | Live | Preview (pre-GA) | **ADAPTER** (not now) |
| Phone/email OTP (own SMS/email provider) | Control of contact channel | Any | Provider API | Provider key | Per message | Live | Proves control, not business identity. DPDP notice/consent | **ADAPTER** (email link now if mail exists, else MANUAL) |
| Bank account penny drop (Cashfree BAV / RazorpayX FAV / Setu) | Account exists + name on account | Indian bank accounts/VPAs | REST | client id/secret | Per call, contract | Live | KYC'd merchant account needed. Never store credentials | **ADAPTER** |
| ONDC registry | Network-participant (app) lookup | ONDC NPs (apps), not merchants | Signed `/v2.0/lookup` | NP signing keys | n/a | Live | Holds apps, not individual sellers | **Not relevant** |
| Telangana Shops & Establishments | Trade licence/registration check | Telangana | Web UI `labour.telangana.gov.in/VerifyApplicationStatus.do` | CAPTCHA (probe) | Free | Live | CAPTCHA, no API | **MANUAL** |
| Karnataka (eKarmika) | Shops & commercial establishment registration | Karnataka | Web portal | Login/unknown | Free | Live | Portal unreachable from probe. No API found | **MANUAL** |
| Maharashtra (Shops & Establishments Act 2017) | Registration (10+ workers) or Form F intimation / Form G receipt (<10) | Maharashtra | Labour Commissioner / Aaple Sarkar portal | Login | Free | Live | No public verify API found. Most kiranas have fewer than 10 workers, so they hold only an intimation receipt | **MANUAL** (upload Form G/certificate) |

---

## 2. GSTIN

### 2.1 Structure

The structure below is **VERIFIED (secondary)**: https://arthurdejong.org/python-stdnum/doc/stdnum.in_.gstin and https://taxguru.in/goods-and-service-tax/gstin-goods-and-service-tax-identification-number-structure.html. The GST user manuals also describe the 15th character as a system-generated check digit.

| Positions | Meaning |
|---|---|
| 1–2 | State code (e.g. 27 Maharashtra, 29 Karnataka, 36 Telangana, 07 Delhi) |
| 3–12 | PAN of the holder (5 letters, 4 digits, 1 letter) |
| 13 | Registration count for that PAN in that state: `1`–`9`, then `A`–`Z` |
| 14 | `Z` by default for regular taxpayers |
| 15 | Check character (Luhn mod 36) |

Regex for regular taxpayers: `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$`

Valid state codes are 01–38, plus 97 (Other Territory) and 99 (Centre Jurisdiction). This list is **UNVERIFIED** against an official GSTN list.

UIN, TDS, TCS, non-resident and OIDAR registrations use other patterns (**UNVERIFIED**). If an input matches no known pattern, mark it `inconclusive`, never `failed`.

### 2.2 Checksum algorithm (Luhn mod 36)

GSTN does not publish an official specification document for the algorithm. That gap is **UNVERIFIED**: we searched and found none.

The algorithm below is the one stated by python-stdnum ("Luhn mod 36") and by multiple sources. We verified it against six real public GSTINs (see 2.3).

1. Alphabet `C = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"`. The value of a character is its index (0–35).
2. Take the first 14 characters, in upper case.
3. For position `i` = 0..13 from the left, the factor is `1` if `i` is even and `2` if `i` is odd. This is the same as alternating ×2 starting from the rightmost of the 14 characters.
4. `p = value × factor`. Reduce `p` to `p // 36 + p % 36`, which is the sum of its base-36 digits.
5. `S` = sum of the 14 reduced values.
6. `check = (36 − S % 36) % 36`. The 15th character must be `C[check]`.

```python
C = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
def gstin_check_char(first14: str) -> str:
    s = 0
    for i, ch in enumerate(first14.upper()):
        p = C.index(ch) * (2 if i % 2 else 1)
        s += p // 36 + p % 36
    return C[(36 - s % 36) % 36]
```

### 2.3 Test vectors

Every checksum below was computed by us. The GSTIN-to-company mapping comes from public aggregator sites (**VERIFIED (secondary)**). It was **not** re-confirmed on the GST portal, so use these only as checksum fixtures.

| GSTIN | Entity (public web) | Source | Expected |
|---|---|---|---|
| `27AAACR5055K1Z7` | Reliance Industries Ltd, Maharashtra | https://www.credlix.com/gst-number-search/27AAACR5055K1Z7 | valid (`7`) |
| `27AAACT2727Q1ZW` | Tata Motors Ltd, Maharashtra | https://knowyourgst.com/gst-number-search/tata-motors-limited-27AAACT2727Q1ZW | valid (`W`) |
| `29AAACI4798L1ZU` | Infosys Ltd, Karnataka | https://www.knowyourgst.com/gst-number-search/infosys-limited-29AAACI4798L1ZU/ | valid (`U`) |
| `36AAACI4798L3ZX` | Infosys Ltd, Telangana | https://www.knowyourgst.com/gst-number-search/infosys-limited-36AAACI4798L3ZX/ | valid (`X`) |
| `29AAACI4798L2ZT` | Infosys Ltd, Karnataka (2nd) | same site | valid (`T`) |
| `27AAPFU0939F1ZV` | python-stdnum doc example | stdnum link above | valid (`V`) |
| `27AAPFU0939F1ZO` | python-stdnum doc example | stdnum link above | **invalid** (expected `V`) |

Worked example 1: `27AAACR5055K1Z7`. Reduced values: 2,14,10,20,10,24,27,10,0,10,5,(K=20×2=40→1+4=)5,1,(Z=35×2=70→1+34=)35. S = 173, and 173 % 36 = 29, so the check is (36−29) = 7, giving **`7`**. ✔

Worked example 2: `29AAACI4798L1ZU`. Reduced values: 2,18,10,20,10,24,18,8,7,18,8,(L=21×2=42→1+6=)7,1,35. S = 186, and 186 % 36 = 6, so the check is 30, giving **`U`**. ✔

Worked example 3: `36AAACI4798L3ZX`. Reduced values: 3,12,10,20,10,24,18,8,7,18,8,7,3,35. S = 183, and 183 % 36 = 3, so the check is 33, giving **`X`**. ✔

**Caution for the providers agent.** The Setu sandbox sample GSTINs `27AAICB3918J1CT` and `27AAICA3919J1CT` (https://docs.setu.co/data/gst) **fail** this checksum: the expected check character is `S`. In sandbox mode, the local checksum pre-check must not block calls to the provider, or those fixtures will be rejected.

### 2.4 GST Portal taxpayer search

**CAPTCHA required** for the pre-login "Search Taxpayer". This is **VERIFIED (secondary)**: the GST user manual text is quoted at https://www.taxheal.com/can-search-taxpayer-registered-gst-india.html and the page lives at https://services.gst.gov.in/services/searchtp. That page is an SPA and returns a "Loading" shell to non-browsers, so we could not read it directly. **Never automate it.**

### 2.5 GSTN public API through GSPs

- GSTN exposes "Public APIs" with no taxpayer consent needed, through GSPs only. They include Search Taxpayer: `GET <gsp_base>/commonapi/v1.3/search?gstin={gstin}&action=TP` (the version varies by GSP).
  - VERIFIED (GSP doc): https://docs.gsp.vayana.com/GSTN/searchTaxpayer-get-api/
  - The official portal lists Public APIs, Taxpayer APIs and IRP APIs: https://developer.gst.gov.in/apiportal/ (VERIFIED, page index only).
- Response fields: `gstin, lgnm` (legal name), `tradeNam, sts` (status), `rgdt` (registration date), `cxdt` (cancellation date), `ctb` (constitution), `dty` (taxpayer type), `nba[]` (nature of business), `pradr{addr,ntr}` (principal address), `adadr[], stj/stjCd, ctj/ctjCd` (jurisdictions), `lstupdt, einvoiceStatus`. VERIFIED at the Vayana URL above.
- Who may call:
  - GSTN-approved GSPs. Eligibility includes IT/ITES/BFSI firms with at least ₹2 crore capital and at least ₹5 crore average turnover (VERIFIED (secondary): https://www.knowyourgst.com/article/procedure-to-apply-and-become-a-gstn-suvidha-providers-gsp-for-gst-returns-and-invoice-filings-and-list-of-gsp-6/).
  - Anyone else goes through a GSP or ASP under contract.
- Sandbox: GSPs offer a GSTN sandbox with no API charges, while production is chargeable. VERIFIED (secondary): https://docs.enriched-api.vayana.com/1s0-getting-started/
- Pricing is not published. It is per-call and set by contract (UNVERIFIED amount).
- Private taxpayer APIs (returns and ledgers) need an OTP-enabled API session from the taxpayer. They are out of scope.

### 2.6 E-invoice / IRP "Get GSTIN Details"

The IRP API returns name, address, state, PIN, taxpayer type, status and blocked status. Direct API access is limited to e-invoice taxpayers above a turnover threshold, and to GSPs. VERIFIED (GSP doc): https://docs.enriched-api.vayana.com/routes/basic/einv/apis/Get-GSTIN-Details/0-get-gstin-details-vthree-oh/

The exact threshold has changed over time and is **UNVERIFIED** today. **Not usable by Sauda directly.**

---

## 3. MCA

- **MCA21 V3 "View Company/LLP Master Data"**: search by CIN/LLPIN or name. **CAPTCHA required.** No login is needed. VERIFIED (secondary): https://surepass.io/faq/how-to-find-mca-master-data and https://legalwiz.in/?p=22126. No official public API was found (UNVERIFIED that none exists). Decision: **MANUAL**.
- **data.gov.in "Registrars of Companies (RoC)-wise Company Master Data"**:
  - Resource id **`4dbe5667-7b6b-41d7-82af-211562424d9a`**, Ministry of Corporate Affairs.
  - **VERIFIED (probe)**: `https://api.data.gov.in/resource/4dbe5667-7b6b-41d7-82af-211562424d9a?api-key=KEY&format=json&filters[CIN]=L17110MH1973PLC019786` returned Reliance Industries Ltd, Active, ROC Mumbai.
  - `updated_date` = **2026-10-13** (current).
  - Fields: `CIN, CompanyName, CompanyROCcode, CompanyCategory, CompanySubCategory, CompanyClass, AuthorizedCapital, PaidupCapital, CompanyRegistrationdate_date, Registered_Office_Address, Listingstatus, CompanyStatus, CompanyStateCode, CompanyIndian/Foreign Company, nic_code, CompanyIndustrialClassification`.
  - No directors or charges. LLP coverage is UNVERIFIED.
  - An older catalog-level "Company Master Data" (`ec58dab7-d891-4abb-936e-d5d274a6ce9b`) was last updated 2024-12-13. **Do not use it.**
  - Decision: **NOW** for companies with a CIN. Label the result with the dataset `updated_date`. A miss means `inconclusive`, not `failed`.

---

## 4. Udyam (MSME)

- The verification page sits under "Print/Verify → Verify Udyam Registration Number" at https://udyamregistration.gov.in/. Inputs are the 19-character URN plus a **CAPTCHA**. VERIFIED (secondary): https://themunim.com/blog/udyam-registration-verification/
- No official public verification API was found (UNVERIFIED that none exists). Third parties such as Perfios advertise Udyam verification: https://www.perfios.ai/in/products/kyc-kyb
- URN format is `UDYAM-XX-00-0000000`, which is "UDYAM", a 2-letter state code, a 2-digit district and a 7-digit serial. Regex: `^UDYAM-[A-Z]{2}-\d{2}-\d{7}$`. UNVERIFIED against an official specification; it is widely documented.
- Decision: **MANUAL** + certificate upload. Local format check as `preliminary_validation`.

## 5. FSSAI FoSCoS

- FBO search is available without login at https://foscos.fssai.gov.in/ ("FBO Search": search by licence/registration number or name). VERIFIED (secondary): https://blog.petpooja.com/finance-compliance/fssai-licence-check-guide-ways-verify-food-business/
- The portal is an Angular SPA, so CAPTCHA on FBO search is **UNVERIFIED**. Track Application does use a CAPTCHA (secondary).
- No official public API was found.
- Number format is 14 digits. Digit 1 is the type: `1` = licence (State/Central), `2` = registration. Digits 2–3 are the state (00 = Central), 4–5 the year, 6–8 the officer code, and 9–14 the FBO number. VERIFIED (secondary): https://www.registerkaro.in/tools-calculators/fssai-license-number-check. Regex: `^[12]\d{13}$`. The first-digit rule is UNVERIFIED on an official FSSAI page.
- Decision: **MANUAL** + licence upload. Format check NOW.

## 6. GeM

Seller registration validates PAN/Aadhaar and GSTIN inside the logged-in portal. VERIFIED: https://assets-bg.gem.gov.in/resources/pdf/seller-registration-pre-requisites-v1.2.pdf

**No public seller lookup or API was found.** Decision: not a source. Allow it as a `self_declared` claim only.

---

## 7. All India Pincode Directory (data.gov.in)

- **Use resource id `5c2f62fe-5afa-4119-a499-fec9d604d5bd`**: "All India Pincode Directory till last month", Department of Posts. Its catalog is `709e9d78-bf11-487d-93fd-d547d24cc0ef`.
- **VERIFIED (probe)**: `GET https://api.data.gov.in/resource/5c2f62fe-5afa-4119-a499-fec9d604d5bd?api-key=KEY&format=json&limit=50&filters[pincode]=500001`
- Fields: `circlename, regionname, divisionname, officename, pincode, officetype` (HO/PO/BO), `delivery` (Delivery/Non Delivery), `district, statename, latitude, longitude`. Values are strings, and `statename`/`district` are upper case.
- Sample result for 500001: Hyderabad G.P.O., HYDERABAD, TELANGANA, 17.387993, 78.47652. The query returned 3 offices.
- `updated_date` is **2025-10-03**, despite the "till last month" title. Treat it as about a year old and cache the response.
- Some office coordinates are wrong. For example, Moazzampura S.O. for 500001 is at 17.6556, 78.7520, which is about 40 km off. Use the `officetype=HO` row or the median of the rows as the centroid, and never rely on it for proximity alone.
- The public sample key `579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b` exists but was **rate-limited** in testing. Use the project key from env `DATA_GOV_IN_API_KEY`.
- The legacy resource `6176ee09-3d56-4a3b-8115-21841576b2f6` ("All India Pincode Directory") still answers but is `active: 0`, last updated 2022-12-12, and has different fields (`taluk, districtname, deliverystatus`). **Do not use it.**
- Decision: **NOW**. Check that the declared state/district matches the PIN's `statename`/`district`.

## 8. Google Maps Platform

- **Geocoding API**: India pricing for India-billed accounts with majority-India usage is a **70,000 free events/month**, then **$1.50 per 1000** up to 5M, then $0.38. The global list price is $5 per 1000 with 10k free. VERIFIED: https://developers.google.com/maps/billing-and-pricing/pricing-india and https://developers.google.com/maps/billing-and-pricing/pricing
- **Address Validation API**: **India is supported in preview (pre-GA)**, and Google recommends sending `regionCode`. VERIFIED: https://developers.google.com/maps/documentation/address-validation/coverage. India Pro pricing is 35k free, then $5.10 per 1000 (same pricing-india URL).
- Decision: Geocoding **NOW** if a key is configured, else `inconclusive`. Address Validation is an **ADAPTER** only.

## 9. Authorised providers (GST / KYB / penny drop)

| Provider | Offers (relevant) | Access model | Evidence |
|---|---|---|---|
| **Cashfree Verification Suite** | GSTIN (`POST /verification/gstin`, body `{GSTIN, business_name}`), PAN, bank account (penny and reverse penny), UPI | Merchant account. Sandbox `https://sandbox.cashfree.com/verification`, prod `https://api.cashfree.com/verification`. Headers `x-client-id`, `x-client-secret` (+ optional `x-cf-signature`) | VERIFIED: https://www.cashfree.com/docs/api-reference/vrs/v2/gstin/verify-gstin.md |
| **Setu** | GSTIN verification | **Contract only.** KYC with Sales, then credentials. Sandbox `https://dg-sandbox.setu.co`, prod `https://dg.setu.co`. Headers `x-client-id, x-client-secret, x-product-instance-id` | VERIFIED: https://docs.setu.co/data/gst |
| **RazorpayX** | Fund Account Validation (penny drop to bank/VPA, reverse penny drop). **No GSTIN API found** | RazorpayX account. Reverse penny drop is live mode only | VERIFIED: https://razorpay.com/docs/x/fund-account-validation/api |
| **Perfios (Karza)** | GST, MCA signatories, Udyam, FSSAI, HSN and more | Enterprise contract | VERIFIED (vendor page): https://www.perfios.ai/in/products/kyc-kyb |
| **Signzy / IDfy** | KYC/KYB suites including GST and MCA | Enterprise contract (UNVERIFIED specifics) | UNVERIFIED (vendor marketing only) |

Cashfree GSTIN response fields: `reference_id, GSTIN, legal_name_of_business, trade_name_of_business, center_jurisdiction, state_jurisdiction, date_of_registration, constitution_of_business, taxpayer_type, gst_in_status, last_update_date, nature_of_business_activities[], principal_place_address, principal_place_split_address{building_name, street, location, district, state, city, pincode, latitude, longitude, flat_number, building_number}, additional_address_array[], valid, message`.

Decision: build one `gst_registry.py` adapter with a pluggable backend:

- Cashfree first, Setu second.
- It is disabled unless credentials exist in env.
- With no credentials, return a MANUAL task and **never** fabricate a result.
- Treat the trade-name comparison as fuzzy: "Sri Laxmi General Store" vs "Sri Lakshmi General Stores" gives `partially_verified` plus a review task.

## 10. Phone, email and DPDP

- Phone or email OTP proves **control of the channel**, not business identity or authority.
  - Use an SMS provider registered on DLT for the OTP (the TRAI DLT requirement is UNVERIFIED detail).
  - Store only a hash and a masked value.
  - Never store the OTP.
- **DPDP Act 2023 and the DPDP Rules 2025** were notified 14 Nov 2025. Phase 2 (Consent Managers) starts **13 Nov 2026**. Phase 3 (notice, verifiable consent, security safeguards, breach reporting, Data Principal rights) starts **13 May 2027**. VERIFIED: https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf and https://www.azbpartners.com/bank/update-indias-digital-personal-data-protection-framework-comes-into-effect/
- Design to the Phase 3 rules now:
  - Show a specific itemised notice and collect consent per purpose (the existing `consents:{gst:true,...}`).
  - Minimise data and keep `retention_until`.
  - Give the owner deletion and correction paths.
  - Share only redacted summaries with counterparties.
  - Proprietor names, phones and home-cum-shop addresses are personal data.

## 11. ONDC

The ONDC registry holds **network participants**, meaning buyer and seller *apps*, not individual merchants. `/v2.0/lookup` needs signed Authorization headers from a registered NP. VERIFIED: https://github.com/ONDC-Official/developer-docs/blob/main/registry/Onboarding%20of%20Participants.md

Decision: **not relevant** for verifying a kirana or a distributor.

## 12. Shops & Establishments (state)

- **Telangana**: the certificate verify page is https://labour.telangana.gov.in/VerifyApplicationStatus.do. It takes a licence number plus a **CAPTCHA**: VERIFIED (probe), the page contains CAPTCHA inputs. No API. Decision: **MANUAL**.
- **Karnataka**: registration and renewal run on eKarmika (https://ekarmika.karnataka.gov.in/) under the Karnataka Shops & Commercial Establishments Act 1961. VERIFIED (secondary): https://www.kanakkupillai.com/learn/ekarmika-new-mandatory-karnataka-shops-and-establishment-act-1962/. The site was unreachable from our probe, and no public verify API was found. Decision: **MANUAL**.
- **Maharashtra**: under the Maharashtra Shops & Establishments Act 2017, establishments with 10 or more workers register. Those with fewer than 10 file an online **Form F intimation** and receive a **Form G** receipt. VERIFIED (secondary): https://mondaq.com/india/employee-benefits-compensation/661244/maharashtra-shops-and-establishments-regulation-of-employment-and-conditions-of-service-act-2017. The portal is the Labour Commissioner site (https://mahakamgar.maharashtra.gov.in/). No public verify API was found. Decision: **MANUAL**: upload the certificate or Form G and extract it with Gemini.

---

## 13. Implementation notes for adapters

- **Statuses**:
  - A local GSTIN, FSSAI or Udyam format pass gives `preliminary_validation` with check status `self_declared`. It is never `verified`.
  - A format fail gives `failed` with the summary "format/checksum invalid; likely typo".
- **No credentials**: every registry adapter without credentials returns a MANUAL task. The task carries the source URL, the fields to record, an evidence slot and a `pending` status.
- **Fixtures**: demo fixtures use `source_kind = simulated_fixture` and must never be shown as `official_registry`.
- **data.gov.in errors**: on `Rate limit exceeded` or `Key not authorised`, return `inconclusive`, never `failed`.
- **Caching**: cache pincode responses by PIN, because the dataset is about a year old.
