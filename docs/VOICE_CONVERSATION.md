# Continuous voice and restock conversations

Scope: the owner app (`apps/owner-app`). The backend section at the end, "Backend: turns, extraction, latency", is
written by the backend agent. Contract: CONTRACT2 (restock sessions, turns, telemetry).

## Why it stopped at one minute (root cause, verified at 55f18d3)

- `lib/voice.ts:15` set `VOICE_MAX_SECONDS = 60`. `components/voice/VoiceCapture.tsx:213` stopped the recorder when
  the timer reached it ("Reached the 60 second limit; stopping.").
- The backend had the same limit: `services/voice.py` `MAX_SECONDS = 60`, `MAX_BYTES = 3 MB`.
- The flow was record, stop, upload the whole clip, show the transcript, wait for "Use this" (a second
  confirmation), send it to `/chat`, and re-parse the whole request. Nothing streamed and nothing was incremental.
- The conversation itself was not persisted. `ChatStream.tsx` held items and the draft in React `useState`, so
  leaving `/restock` lost everything. ADK sessions used `InMemorySessionService` (`agent/root.py:31`).

## Architecture now

```
 mic ──► Web Speech (continuous, interim) ──final──┐
   └──► fallback: MediaRecorder + VAD segments ──► POST /voice/parse ──transcript──┤
 keyboard ──────────────────────────────────────────────────────────────────────────┤
                                                                                    ▼
                         POST /restock/sessions/{sid}/turns {client_turn_id, text, source}
                                                                                    ▼
                         {session, reply, ops, clarification, latency_ms} ─► draft re-rendered, changed lines highlighted
```

- `lib/voice.ts` holds two listeners behind one interface (`start / pause / stop`). Only one can be active in the
  whole app (`claim()` stops the previous one).
  - `WebSpeechListener` (Chrome, Edge, Android Chrome) uses `continuous = true` and `interimResults = true`, with
    `lang` set from the language menu (en-IN, hi-IN, te-IN, ta-IN, kn-IN, ml-IN, mr-IN, bn-IN, gu-IN, pa-IN,
    or-IN, ur-IN; Bhojpuri listens as hi-IN). Interim text is shown live. Each `isFinal` result is emitted at once as one
    utterance.
  - `RecorderListener` is the fallback: `getUserMedia`, then a WebAudio RMS VAD with an adaptive noise floor sampled
    every 50 ms. A segment ends after 900 ms of silence or 25 s. A new `MediaRecorder` starts per segment, so each
    upload is a complete WebM/MP4 file. Segments without speech are dropped and never uploaded. Uploads are
    serialised, so turns arrive in spoken order.
- `components/voice/VoiceCapture.tsx` exports `VoiceControl`, the UI: Listen / Pause / Stop, a red "Mic on" pill
  with a live level bar, live partial text, the language picker, error panels and the processing disclosure. The
  legacy `VoiceCapture` export now adapts it for `ChatStream`.
- `components/restock/SessionView.tsx` turns every final into a turn. A typed message uses the same `POST /turns`
  with `source: "text"`, so the owner can switch between speaking and typing in the middle of a list.

## Interaction patterns

- **No transcript confirmation.** A final utterance is applied directly. Sauda's one-line reply appears above the
  composer, and the lines that changed get a short highlight (`.li.changed`, a static tint under
  reduced-motion).
- **Clarification.** When something is ambiguous, Sauda asks one question with option chips (for example "Which dal
  would you like to add?" with four products). Tapping a chip, or saying "the first one", sends a new turn that
  names the option; the server applies the pending edit.
- **Low ASR confidence.** When the browser reports a confidence between 0 and 0.6, nothing is applied. Instead a
  "Did you say…?" box appears with an editable text field and Send / Discard.
- **Sign / approve by voice.** These only navigate. "Sign it" opens the limits review (the existing MandateForm with
  the MAY / MAY NOT summary). "Approve" opens `/confirm/{id}` if a cart is waiting, and otherwise explains that
  there is nothing to approve yet. Signing and approving still need the explicit button on those screens.
- **Fixing things by voice.** Examples: "remove the salt", "make oil 8", "add another 6 maggi", "budget 9000".
  Typing works the same way.

## Duration handling

- There is no overall limit. Chrome ends a recognition session after about 60 s or after silence, so on `end`,
  while listening is still on, the listener flushes any unfinished interim text as a final and starts a new
  recogniser (50 ms later, or 300 ms after a session that lasted under 1 s). If the service ends six times in a
  row within a second, listening stops with an error, so it cannot loop forever.
- The fallback has no overall limit either. Each segment is capped at 25 s, below the backend's 30 s cap per
  segment.
- Listening stops automatically after 2 minutes without speech, with a note that says so.
- The microphone is released on Pause, Stop, unmount (route change), `pagehide`, and when the session becomes
  read-only.
- Duplicate finals are ignored, by result index per recogniser generation and by identical text within 5 s. Every
  turn carries a `client_turn_id` (a UUID), and a Retry after a network error reuses it, so the server never
  applies a turn twice.

## Languages

Supported: English, हिन्दी, తెలుగు, தமிழ், ಕನ್ನಡ, മലയാളം, मराठी, বাংলা, ગુજરાતી, ਪੰਜਾਬੀ, ଓଡ଼ିଆ, اردو, and
भोजपुरी (beta, listens as Hindi).

- One table for both voice screens: `apps/owner-app/lib/languages.ts` (frontend) and
  `apps/buyer-agent/buyer_agent/languages.py` (backend). The menu (`components/voice/LangSelect.tsx`) is a compact
  native `<select>` with native names, used in voice restock and voice onboarding. The choice is remembered on the
  device (`localStorage["sauda.voice.lang"]`, which now holds the code, e.g. `ta`; old locale values such as `hi-IN`
  are still read).
- Web Speech gets the browser locale (`ta-IN` and so on). The recorder fallback sends `lang_hint` with each segment;
  `POST /voice/parse` accepts every locale above plus `bho-IN`. Unknown hints are ignored, not rejected.
- Onboarding (`POST /tn/onboarding {lang}`, and `lang` on each turn) accepts a code or a locale (`ta`, `ta-IN`,
  `bho`); anything unknown becomes `en`. The opening question, every field question, the read-back frame, the
  skip / missed / Aadhaar / screening notes and the PIN / GSTIN / FSSAI / Udyam problem texts exist for every
  language (`onboarding_i18n.py`, merged into the tables in `onboarding_agent.py`; a missing string falls back to
  English). Yes / no words for the consent and confirm steps were added for each language; anything else goes to
  Gemini.
- Indic digits (১০, ௨௦, ੧੨, ۱۲, …) are normalised to 0-9 in transcripts and before the restock fast path and the
  onboarding PIN / GSTIN checks. No new number words were added to the fast path: number words in the new
  languages are left to Gemini, which handled all of them in the tests below.
- Not translated yet (same as for Hindi and Telugu before this change): the restock turn reply ("Added 10 …",
  "Salt LITE now 25") is built in code in English, and the onboarding acknowledgement fragments and read-back
  values ("sole proprietorship", "not GST registered", "buying rice, edible oil") are English inside a sentence in
  the owner's language. Clarification questions written by Gemini are asked to be in the owner's language.
- If the browser reports `language-not-supported`, the panel offers "Use recorder mode", which uses the Gemini
  transcription route instead.

### Verification (18 Oct 2026, local backend :8131, real Vertex Gemini, shop `dev`)

Sentence: "10 packets of Aashirvaad atta, 20 Tata salt, 12 one-litre sunflower oil", written in each language and
script with brand names in Latin. Expected lines: Aashirvaad Superior MP Atta x10, Salt LITE (TATA) x20, Refined
Sunflower Oil 1 L x12. Restock also had a second turn "make salt 25" in the language (expected Salt LITE 25, the
rest unchanged). Onboarding: buyer, typed answers in the language for name + proprietorship, not GST registered,
PIN, street, "I am Ravi, the owner", "rice, oil, snacks", skip FSSAI, consent yes; expected every question in the
language and the read-back with the right fields. Audio: macOS `say` voices converted to 16 kHz mono WAV with
`afconvert`, sent to `POST /voice/parse`.

| Language | Browser STT locale | Gemini audio transcription | Restock text parse | Onboarding conversation | Status |
|---|---|---|---|---|---|
| English | en-IN, configured | Pass (Rishi) | Pass | Pass (existing) | Supported |
| Hindi | hi-IN, configured | Pass (Lekha): digits, brands kept | Pass | Pass (existing) | Supported |
| Telugu | te-IN, configured | Pass (Geeta): digits kept; "Tata" written in Telugu script | Pass | Pass (existing) | Supported |
| Tamil | ta-IN, configured, needs a real mic test | Pass (Vani, 2 runs): digits, Aashirvaad, Tata kept | Pass, edit pass | Pass, 8 turns | Supported |
| Kannada | kn-IN, configured, needs a real mic test | Pass (Soumya, 2 runs): digits, brands kept | Pass, edit pass | Pass, 8 turns | Supported |
| Malayalam | ml-IN, configured, needs a real mic test | Not tested (no test voice) | Pass, edit pass | Pass, 8 turns | Supported (typed verified) |
| Marathi | mr-IN, configured, needs a real mic test | Not tested (no test voice) | Pass, edit pass | Pass, 8 turns | Supported (typed verified) |
| Bengali | bn-IN, configured, needs a real mic test | Pass with caveats (Piya, 6 runs, 4 fully right): numbers right; brands written in Bengali script; "এক লিটার" heard as "ঐকো লিটার" (flagged unclear) with the synthetic voice; one run invented "Saffola" and the oil line dropped (that prompt wording was reverted); one run returned no preview lines (Vertex 429s were occurring then; not confirmed as the cause) | Pass, edit pass (Bengali digits) | Pass, 8 turns | Supported; check the transcript |
| Gujarati | gu-IN, configured, needs a real mic test | Not tested (no test voice) | Pass, edit pass | Pass, 8 turns | Supported (typed verified) |
| Punjabi (Gurmukhi) | pa-IN, configured, needs a real mic test | Not tested (no test voice) | Pass, edit pass | Pass, 8 turns | Supported (typed verified) |
| Odia | or-IN, configured, needs a real mic test | Not tested (no test voice) | Pass, edit pass | Pass, 8 turns | Supported (typed verified) |
| Urdu | ur-IN, configured, needs a real mic test | Not tested (no test voice) | Pass, edit pass | Pass, 8 turns (questions right to left) | Supported (typed verified) |
| Bhojpuri | none in Chrome; listens as hi-IN | Pass with caveat (Lekha, a Hindi voice reading Bhojpuri; hints hi-IN and bho-IN): numbers and brands right, language detected as bho, but the transcript drifts to Hindi ("नून" -> "नमक", "चाहीं" -> "चाहिए") | Pass, edit pass ("नून 25 गो कर दीं") | Pass, 8 turns (Bhojpuri questions) | Beta (understood via Hindi recognition) |

Honest notes:

- **Browser recognition for every new language needs a real microphone test.** Chrome's Web Speech service lists
  these locales, but it cannot be exercised headless; only the configuration is verified.
- Malayalam, Marathi, Gujarati, Punjabi, Odia and Urdu have no macOS test voice on this machine, so Gemini audio
  transcription is untested for them; typed restock and onboarding passed.
- All audio tests used synthetic voices, not a real shopkeeper in a noisy shop.
- Bhojpuri: no browser locale exists. Recognition is Hindi's, so a real speaker's Bhojpuri words may come back as
  Hindi; the meaning (items and numbers) survived in the tests. The menu labels it "beta, listens as Hindi".
- Some calls hit Vertex `429 RESOURCE_EXHAUSTED` during the runs (shared project quota) and were retried; the user
  sees "Could not transcribe the recording right now" in that case.

## Failure recovery

| Failure | What the owner sees | Recovery |
|---|---|---|
| Permission denied (`not-allowed`, `NotAllowedError`) | "Microphone is blocked for this site", plus steps for Chrome/Android and iPhone Safari | Type instead, or allow the mic and tap Listen |
| Network (`network`) | "Could not reach the speech service", and the words heard so far are kept | Retry, "Send what we heard", or "Use recorder mode" |
| No speech (`no-speech`) | Nothing; the recogniser restarts | After 2 minutes of silence, listening stops with a note |
| No microphone (`audio-capture`, `NotFoundError`) | "No microphone found" | Type instead |
| Unsupported browser | "Voice is not available in this browser. Type your list below." | Typing uses the same turns |
| Insecure page | "Voice needs a secure (https) page." | — |
| Turn failed (network or 5xx) | "Not applied yet", with the text | Retry (same `client_turn_id`) or Edit |
| Session locked (409) | "This restock is locked now" | The page reloads the server copy |

## Privacy

- Web Speech: the browser's speech service processes the audio (Google's service in Chrome). The UI says so under
  the mic ("Your browser's speech service (Google in Chrome) processes the audio; Sauda gets the text."). Sauda
  receives text only.
- Fallback: each speech segment is uploaded once to `/voice/parse`. It is never stored by the app or the server,
  and silent segments are never uploaded.
- Telemetry (`POST /telemetry/voice`) sends mark names, timestamps and an utterance id only, never text. The
  `?debug=1` panel also shows no text.

## Measured latency (18 Oct 2026, laptop to local backend :8092 to Vertex/Firestore asia-south1, shop `dev`)

Client marks come from `lib/latency.ts`: speech_start, first_partial, utterance_end, final_transcript, turn_sent,
turn_applied and draft_rendered. Raw data: `scratchpad/pptr/ux2/live/latency-*.json`, plus the backend telemetry
log lines.

**Typed turns** (headless Chrome, 10-turn script). Times are in ms.
- "sent→applied" is the client round trip.
- "applied→rendered" is from the response to the next animation frame after the DOM commits.

| turn | path | sent→applied | applied→rendered | server total (extract) |
|---|---|---|---|---|
| "10 atta 5 kg, 20 sunflower oil, 24 Maggi, keep it under 8000" | model | 3236 | 41 | 3227 (2849) |
| "make oil 8" | model* | 2430 | 29 | 2418 (2090) |
| "add another 6 maggi" | fast | 325 | 13 | 317 (0) |
| "remove the atta" | fast | 358 | 23 | 349 (0) |
| "budget 9000" | fast | 307 | 28 | 300 (0) |
| "add 5 tata salt" | model | 1614 | 31 | 1605 (1296) |
| "change salt to 7" | fast | 302 | 19 | 298 (0) |
| "add 3 sugar and 2 toor dal" | model | 1774 | 32 | 1763 (1443) |
| "remove the sugar" | fast | 344 | 14 | 337 (1) |
| "how much is the total?" | fast | 321 | 9 | 311 (0) |

\* "make oil 8" went to the model on this run; the backend's fast path matches "make it 8" and "reduce the oil to
8". This is reported to the backend.

Reading the numbers:
- Fast-path edits appear about 0.31–0.37 s after Send.
- Model turns take 1.6–3.2 s.
- Client rendering adds 10–40 ms.

**Voice, recorder fallback** (headless Chrome, a recorded English phrase played into a WebAudio stream that stands
in for the mic, with real VAD, MediaRecorder, `/voice/parse` and turns). The phrase was "Add ten packets of Tata
salt." then 1.5 s of silence, then "Make it twelve." It produced two segments and two turns.

| pair | utterance 1 | utterance 2 |
|---|---|---|
| utterance_end→final_transcript (VAD 900 ms + upload + Gemini transcription) | 4143 | 4288 |
| final_transcript→turn_sent | 0 | 189 (queued behind turn 1) |
| turn_sent→turn_applied | 3084 | 2070 |
| turn_applied→draft_rendered | 36 | 13 |
| **utterance_end→draft_rendered** | **7263** | **6560** |

**Voice, Web Speech:** not measured. Headless Chrome has no Web Speech engine and this pass had no headed run with
a real microphone. With Web Speech the transcription step is local to the browser service: the final arrives
roughly when the speaker pauses, and final→turn_sent measured 0 ms with a scripted recogniser. So the expected
end-to-end time is the speech service's finalisation time plus the turn time above (about 0.35 s fast path, about
2–3 s model). This should be measured on a phone before the demo; the `?debug=1` panel shows these numbers live.

## How this was tested

- **Scripted Web Speech** (`scratchpad/pptr/ws.mjs`). A stand-in `SpeechRecognition` drives the real
  `WebSpeechListener` against the local backend. It checked:
  - partial text shown;
  - a final applied directly as a turn;
  - a duplicate final ignored;
  - auto-restart on `end` while listening stays on;
  - the low-confidence "Did you say" prompt;
  - a network error that keeps the text;
  - permission-denied help;
  - the recogniser aborted on route change.
- **Recorder fallback** (`scratchpad/pptr/lat.mjs voice`): real VAD, segmenting and `/voice/parse`, using the
  injected audio stream. Chrome's `--use-file-for-fake-audio-capture` delivered silence in headless mode here, so
  it was not used.
- **Not tested:**
  - real microphone and Web Speech on a phone;
  - Hindi or Telugu speech;
  - Safari (MP4 recorder path).

## Backend: turns, extraction, latency

*Section owned by the backend agent; the rest of this file is the frontend's.*

**Root causes (verified at 55f18d3).** `lib/voice.ts:15` `VOICE_MAX_SECONDS = 60` and `VoiceCapture.tsx:213`
auto-stops the recording. `services/voice.py` had `MAX_SECONDS = 60` and `MAX_BYTES = 3 MB`. The whole clip was
uploaded, then confirmed, then re-parsed through `/chat`. Sessions lived in `InMemorySessionService` (`agent/root.py:31`).

**Segments.** `/voice/parse` now takes one utterance per request: `MAX_SECONDS = 30`, `MAX_BYTES = 2 MB` (30 s of
Opus or AAC is about 0.1 to 0.5 MB; 16 kHz mono WAV is about 1 MB). All the existing checks are kept: type sniffing,
duration from the container header or audio tokens, silence detection, the in-memory multipart parse, and no audio
stored. The per-owner rate is raised from 12 to 30 per minute, because continuous voice sends one request per
segment. The conversation itself has no limit; each segment or final Web Speech result becomes a turn.

**Turn pipeline** (`POST /restock/sessions/{sid}/turns`, `services/sessions.py`):
1. Load the session (owner-scoped) and refresh its derived status. A repeated `client_turn_id` returns the stored
   response (`dedup: true`). A locked status returns 409 `session_locked`.
2. **Deterministic fast path**, run before any model call. Number words are normalised first ("twenty-four" becomes
   24, "eight thousand" becomes 8000, "one-litre" becomes "1 litre"). The fast path handles:
   - remove ("remove the salt"), set ("reduce the oil to 8", "make it 6"), "add another 12 [ref]" and budget-only
     sentences;
   - total, items and budget questions;
   - "sign" / "approve" / "place the order", which navigate only;
   - answers to an open clarification ("the mustard one", "the first one").

   References resolve against the current lines with the shared `demand._score`. If 2 or more lines match, the turn
   returns one clarification and changes nothing.
3. Otherwise **one Gemini structured call** (`deps.gemini_json`, thinking_level low, 4k output budget, schema
   `TurnExtract`) receives the current lines, the budget, the last 6 turns and the catalogue. It returns only
   intent and ops (`add_line`, `set_qty` qty|delta, `remove`, `set_budget`, `replace_product`).
4. Model output is validated in code:
   - gtins must be in the catalogue, and edits must target current lines;
   - `demand.names_product` (the `_drop_unnamed` check) rejects lines the owner did not name;
   - quantities must be 1..5000;
   - a budget must be a number the owner actually said (`parse_budget_paise` first).

   Phrases the model leaves unmatched go through `demand._fallback_parse`. If the call fails, the whole utterance uses
   that deterministic parser.
5. Ops are applied in code (`apply_ops`). Ceilings, estimate and suggested mandate come from
   `demand.draft_line`/`finalize_draft`. The reply sentence is built from the applied ops and the computed draft;
   the model never supplies reply text or numbers.

The catalogue comes from `store.products()`, cached for 300 s; mandi reference prices are cached for 1800 s
(`demand.REFS_TTL_S`).

**Observability.** Every turn logs one INFO line:
`{"evt":"restock.turn","sid_hash","turn_ms_extract","turn_ms_apply","fast_path","dedup","ops":[{op,gtin,qty|delta|paise}]}`.
It never includes transcript text. Responses carry `latency_ms: {load, extract, apply, total}`: `apply` includes the
versioned Firestore save and `total` is the server wall time. `POST /telemetry/voice` takes the client marks
(`{name, t|t_ms, utt?}`), groups them per utterance, and logs the median duration per mark pair. Nothing is stored.

**Measured** on 18 Oct 2026, local backend on a laptop to Vertex `gemini-3.5-flash` and Firestore in asia-south1,
shop `dev`, with the six-turn script from the brief. Times are server `latency_ms`, in ms, from two runs:

| # | utterance | path | extract | apply+save | total (run 1 / run 2) |
|---|---|---|---|---|---|
| 1 | "Prepare a restock … ten packets of one-kilogram atta, twenty packets of salt and twelve one-litre sunflower oils." | model | 3345 / 3207 | 600 / 610 | 4382 / 4193 |
| 2 | "Add twenty-four packets of Maggi noodles and twelve packets of biscuits." | model | 2142 / 2365 | 209 / 425 | 2466 / 3250 |
| 3 | "Keep the budget below eight thousand rupees." | fast | 2 / 2 | 227 / 445 | 372 / 715 |
| 4 | "Reduce the oil to eight bottles." | fast | 1 / 0 | 205 / 596 | 312 / 828 |
| 5 | "What's my current total?" | fast | 1 / 2 | 210 / 488 | 347 / 718 |
| 6 | "Remove the salt." | fast | 0 / 1 | 224 / 451 | 331 / 931 |

What the draft looked like after run 1:
- Turn 1 produced atta 10, iodized salt 20 and sunflower oil 12, with a clarification asking which salt.
- Turn 2 added Chicken Noodles (Maggi) 24 and Milk Bikis 12, with a clarification asking which noodles.
- Turn 3 set the budget to ₹8,000.
- Turn 4 changed the oil from 12 to 8.
- Turn 5 answered with the estimate, ₹2,900, and the budget.
- Turn 6 removed the salt, leaving an estimate of ₹2,340 for 4 items.

Reading the numbers:
- Model turns take 2.1 to 3.3 s of extraction.
- Fast-path decisions take under 3 ms, so a fast-path turn's latency is all Firestore: about 0.1 to 0.5 s to load
  plus about 0.2 to 0.6 s for the transactional save, measured from a laptop. On Cloud Run in asia-south1 the
  round-trips should be shorter, but that has not been measured yet.
- The first turn's apply step includes the one-time load of reference prices (about 0.4 s).
