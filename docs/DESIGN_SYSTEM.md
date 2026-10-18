# SAUDA design system: "Ledger"

Status: the contract for every screen in `apps/owner-app`. Tokens live in `app/globals.css`,
primitives in `components/ui.tsx` and `components/ui-client.tsx`. Variable and class names are
stable: change values, never rename. If a screen needs something new, add a token or primitive
here first and note it in the changelog at the bottom.

## 1. Design brief

**Personality.** A careful munim (the shop's accountant) with a good pen. Calm, exact, a little
formal, never salesy. SAUDA handles other people's money, so the interface should feel like a
well-kept ledger: ruled lines, clear totals, nothing decorative that could be mistaken for a fact.
It is Indian B2B commerce, not a consumer store and not generic SaaS: rupees with Indian digit
grouping, kirana product names, Hindi and Telugu next to English, UPI as the way money moves.

**Users.** (1) Kirana owners on a mid-range Android phone, often one-handed, often in a noisy
shop, speaking rather than typing. (2) Distributors and suppliers checking orders and trust.
(3) Reviewers and judges on a laptop who want to verify every claim. Design for the phone first,
then make the laptop view denser, never different.

**References and what each contributes.**

| Reference | What we take |
| --- | --- |
| Mercury (banking) | Restraint around money: one strong number per view, quiet secondary text, serif display used sparingly for warmth and trust. |
| Ramp, Stripe dashboard | Ruled tables and hairline rows instead of card grids; tabular numerals; a left sidebar that holds nested sub-areas. |
| Linear | Keyboard-grade focus states, crisp active indicators (a 3px accent bar), short purposeful motion. |
| Shopify Polaris | Page header pattern (breadcrumb, title, description, actions), empty states that tell you the next action, 44px targets. |
| Razorpay dashboard | India-specific money conventions (₹ 1,23,456), UPI and settlement language, honest status chips for payment states. |
| Published frontend-design principles | Ground the look in the subject (the ledger), spend boldness in one place (the display face and the money figure), avoid eyebrows, all-caps labels, gradients and scattered load animations. |
| UI UX Pro Max (fintech rules) | Trust over flash: no purple/pink gradients, no neon, contrast 4.5:1, visible focus, reduced motion, never colour-only meaning, test at 375/768/1024/1440. |
| Awwwards e-commerce | Mostly consumer and animation-heavy, so we take only the typography-led hierarchy and generous whitespace, not the motion. |

**Palette, with rationale.**

- *Paper* `--bg #f6f5f1` and *ink* `--ink #1a1915`: warm neutrals read as paper and pen, not a
  cold SaaS grey, while staying close enough to white that photos and QR codes stay true.
- *Neel* `--accent #2a3a96`: an indigo ink, the colour of a signature and a bank stamp. It means
  "act" (primary buttons, links, focus, active nav). Distinct from the status blue and from the
  violet reserved for "simulated".
- *Ledger green* `--money #0b6b45`: only for money that went the owner's way (savings, under
  budget). Kept separate from `--ok` so "saved ₹" never looks like a generic success tick.
- *Marigold* `--marigold`: the seal dot on the S mark. Brand flourish only, never text or status.
- Status: `--ok`, `--bad`, `--warn`, `--info`, `--neutral`, and `--quar` (violet, dashed) which
  is **reserved for "Simulated" labels**. Every status is a dot or icon *plus words*.
- Dark mode is a true warm dark (`#12110f`), with every token redefined; the accent lifts to
  `#a6b4ff` and money to `#5fd39c`. All text pairs pass WCAG AA (checked: ink-2 6.5:1 light,
  7.7:1 dark; accent on paper 9:1; button text 9.8:1 light, 8.9:1 dark).

**Type.** Fraunces (variable, optical size, soft) via `next/font` for page titles, the wordmark and
section display headings only, with an Iowan/Palatino/Georgia fallback. Geist for every UI string,
and Geist Mono for hashes and ids. Money and quantities always use tabular numerals
(`.money`, `.num`). Scale: 12.5 / 13.5 / 15 (body) / 17 / 22 / 26 (page title) / 32 (hero money) /
clamp(32-44) display. No all-caps except the SAUDA wordmark.

**Layout.** 4/8 spacing grid. Content column 660px (`.narrow`) for flows, 1040px (`.wide`) for
tables and dashboards. Hairline rows (`.list`, `.rowlink`, `.li`) carry lists; a raised `Panel`
is used for at most one decision per screen (the thing that needs the owner).

**Navigation.** Desktop (>= 900px): a left sidebar. Chosen over a top bar because SAUDA has five
task areas plus nested sub-areas (Trust: Record, Security tests, Savings; Network: My network,
Review for reviewers), plus shop, theme and profile controls; a sidebar holds all of that without
a second row of tabs and frees the top of every page for its own header. Mobile: slim top bar
(mark, sample-data tag, profile), underline sub-tabs for Trust and Network, and a five-item bottom
tab bar. Active state = accent bar + ink text + accent icon (not colour alone).

**Components.** Buttons are firm (10px radius), not pills: primary = neel, secondary = paper with a
line, ghost = text, danger = red outline, danger-solid only inside a confirm sheet. Status pills are
dot + text. Inputs are 48px. Steppers, chips and segmented controls are 44px tall in flows.

**Motion.** 120ms for hover/press, 200ms for enter/toggle, 320ms for sheets. Only state changes
animate (a changed line glows, a new price ticks, the mic pulses while listening). Everything
collapses under `prefers-reduced-motion`.

**Accessibility.** AA contrast on every text token in both themes; `--focus` ring (2px paper gap +
2px accent) on every interactive element; 44px minimum targets; skip link; status never by colour
alone; live regions for assistant replies; labels on every input; tested at 390, 768 and 1440.

## 2. Tokens (app/globals.css)

| Group | Tokens |
| --- | --- |
| Surfaces | `--bg` `--surface` `--surface-2` `--surface-3` `--fill` `--sidebar-bg` |
| Ink and lines | `--ink` `--ink-2` `--ink-3` `--line` `--line-2` |
| Action accent | `--accent` `--accent-hover` `--accent-ink` `--accent-soft` `--accent-line` |
| Money accent | `--money` `--money-soft` `--money-line` |
| Brand | `--marigold` (mark only) |
| Status | `--ok` `--bad` `--warn` `--info` `--quar` `--neutral`, each with `-soft` and `-line` |
| Type | `--display` `--sans` `--mono`, `--fs-xs` 12.5, `--fs-sm` 13.5, `--fs-md` 15, `--fs-lg` 17, `--fs-xl` 22, `--fs-2xl` 26, `--fs-3xl` 32, `--fs-display`, `--fw-display`, `--lh`, `--lh-tight` |
| Spacing | `--s1` 4 · `--s2` 8 · `--s3` 12 · `--s4` 16 · `--s5` 20 · `--s6` 24 · `--s8` 32 · `--s10` 40 · `--s12` 48 · `--s16` 64 |
| Radii | `--r-xs` 4 · `--r-sm` 6 · `--r-md` 10 · `--r-lg` 14 · `--r-xl` 20 · `--r-pill` |
| Elevation | `--shadow-1` (resting raised), `--shadow-2` (floating), `--shadow-sheet` (menus, sheets) |
| Motion | `--ease` `--ease-out` `--dur-1` .12s `--dur-2` .2s `--dur-3` .32s |
| Focus | `--focus` (use as `box-shadow`) |
| Shell | `--topbar-h` `--tabbar-h` `--sidebar-w` `--content-w` `--wide-w` |

Rules: never hard-code a colour in a component; use `color-mix(in srgb, var(--x) N%, transparent)`
for tints. Sticky bottom bars use `bottom: calc(var(--tabbar-h) + env(safe-area-inset-bottom))` on
mobile and `bottom: 0` at >= 900px (the sidebar breakpoint).

## 3. Primitives (components/ui.tsx, ui-client.tsx)

| Primitive | Use |
| --- | --- |
| `PageHead({ title, description \| children, action, crumbs, size })` | Every page. `crumbs` for deep pages, e.g. `[{href:'/restock',label:'Restock'},{label:'Diwali restock'}]`. `size="display"` only for Home and sign-in. |
| `Crumbs({ items })` | Breadcrumb on its own when the page has a custom header. |
| `Button`, `ButtonLink` | variants `primary` `secondary` `ghost` `text` `danger` `danger-solid` `success`; `size="sm"`; `busy` + `busyLabel` (keeps the double-submit guard: the button disables while busy). |
| `Money({ paise, whole, size, tone })` | All rupee amounts. `tone="save"` paints in `--money`. |
| `Stat({ label, value, basis, tone, size })` | A figure with its basis line ("from 3 approved orders"). Never show a number without its basis. |
| `Panel({ tone })` | The one boxed decision per screen. Tones `accent` `money` `warn` `bad`. |
| `Steps({ steps, current, label })` | Flow progress (Restock: List, Limits, Negotiate, Approve). |
| `StatusPill`, `StatusDot`, `VerdictChip` | Status = dot + words. |
| `Callout` | Inline note. `bad` for errors, `quar` for simulated notes. |
| `Card` | A titled section *without* a box (legacy name). Use `Panel` when you need a box. |
| `Row`, `SectionHead`, `.list`/`.li`, `.rowlink` | Hairline lists with a section title and "See all". |
| `EmptyState`, `ErrorState`, `Skeleton` | Every async view has all three. |
| `Timeline`, `Meter`, `Evidence` (details) | Progress, budget use, raw evidence. |
| `InfoTip`, `SegmentedControl`, `Sheet` | Interactive (ui-client). Confirmations live in a `Sheet`. |

Utility classes: `.stack(.xs|.sm|.lg)`, `.row(.sm|.top|.between|.wrap)`, `.grow`, `.muted`,
`.small`, `.num`, `.mono`, `.ellipsis`, `.clamp2`, `.narrow`, `.wide`, `.display`, `.h-section`,
`.panel`, `.stat`, `.steps`.

### Shell and layout classes

| Class | Use |
| --- | --- |
| `.sidebar`, `.sb-*` | Desktop shell (Nav.tsx owns it). Do not restyle per screen. |
| `.topbar`, `.tabbar`, `.subtabs` | Mobile shell. Sub-tabs are an underlined row; the active one has an accent underline. |
| `.ph`, `.ph-actions`, `.ph-primary` | Page header layout from `PageHead`. Wrap a single primary action in `.ph-primary` so it goes full width on phones. |
| `.home-*` | Home only. |
| `.rs`, `.rs-assist`, `.as-*`, `.rs-limits`, `.rs-auth` | Restock session: list + assistant console (sticky right column at >= 1100px, bottom dock on smaller screens) and the visually separate "authorise money" step. |
| `.nf` | Not-found page. |

### Restock flow pattern

1. **Your list** (understanding): the assistant console says "Understands your list. Cannot spend money."
   Voice and typing only change the draft. The summary row shows the at-most total and a
   "Review limits" button with the line "Next: set spending limits. Nothing is signed yet."
2. **Review limits** (authorising): a raised accent `Panel` headed "Now you authorise money",
   with the may / won't lists and a sticky "Sign limits · ₹X" bar. Signing still buys nothing.
3. **Negotiate**: live supplier comparison; blocked and simulated suppliers keep their labels.
4. **Approve**: the cart, budget meter, savings in ledger green, the decline path, and the
   double-submit-guarded approve button.

`Steps` with `RESTOCK_STEPS` (components/restock/steps.ts) appears on every one of these screens.

## 4. Honesty labels (must survive any restyle)

- "Simulated" / demo suppliers and data: violet `--quar`, dashed border (`.src.sim`, `.sim-note`).
- Payments: "Payment claimed (not bank-verified)"; never show a payment as verified.
- Claims from a business: "claimed" until a source verifies it.
- Approvals: nothing is bought until the owner approves; spending limits are shown before signing.
- Sample data: the "Sample data" tag stays visible in the shell in mock mode.

## 5. Ownership while two people work in parallel

- Shell, tokens, primitives, Home, Restock, Limits, Negotiation, Approve, sign-in, not-found:
  design-system owner.
- Trust, Security tests, Savings, Network, Review, Invite, Orders, Pay: screen owner, built on
  the tokens and primitives above. Ask for a new token instead of hard-coding.

## Changelog

- v2 "Ledger": warm paper and ink palette, neel action accent, ledger-green money accent, marigold
  mark; Fraunces display face; left sidebar on desktop; `PageHead` gains `crumbs`/`description`;
  new `Crumbs`, `Stat`, `Panel`, `Steps`; `Money` gains `tone`; buttons move from pills to 10px
  radius; mobile sub-tabs become underlined.
- v2.1: Home rebuilt around "what next" (Next step panel, Waiting on you, Recent orders, Savings with
  basis, Business verification with next step, Safety). Restock assistant console, `RESTOCK_STEPS`,
  `.ph-primary`, profile menu links (business, restocks, orders), mic button tinted as an action,
  coarse-pointer 44px rule for small buttons and links.
