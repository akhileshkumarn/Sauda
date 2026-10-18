"""Supported owner languages (voice restock and conversational onboarding).

One table so the voice service, the onboarding agent and the routes agree. `code` is the two-letter code the
onboarding session stores; `locale` is the BCP-47 tag the browser's speech recogniser and the voice `lang_hint`
use. Bhojpuri has no browser speech locale: it is recognised as Hindi (hi-IN) and understood by the model from
the Devanagari text, so it is marked beta.
"""
from __future__ import annotations

# code -> (English name, native name, script, speech locale)
LANGS: dict[str, tuple[str, str, str, str]] = {
    "en": ("English", "English", "Latin", "en-IN"),
    "hi": ("Hindi", "हिन्दी", "Devanagari", "hi-IN"),
    "te": ("Telugu", "తెలుగు", "Telugu", "te-IN"),
    "ta": ("Tamil", "தமிழ்", "Tamil", "ta-IN"),
    "kn": ("Kannada", "ಕನ್ನಡ", "Kannada", "kn-IN"),
    "ml": ("Malayalam", "മലയാളം", "Malayalam", "ml-IN"),
    "mr": ("Marathi", "मराठी", "Devanagari", "mr-IN"),
    "bn": ("Bengali", "বাংলা", "Bengali", "bn-IN"),
    "gu": ("Gujarati", "ગુજરાતી", "Gujarati", "gu-IN"),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", "Gurmukhi", "pa-IN"),
    "or": ("Odia", "ଓଡ଼ିଆ", "Odia", "or-IN"),
    "ur": ("Urdu", "اردو", "Urdu (Nastaliq)", "ur-IN"),
    "bho": ("Bhojpuri", "भोजपुरी", "Devanagari", "hi-IN"),
}
BETA = {"bho"}
CODES = tuple(LANGS)

# lang_hint values accepted by POST /voice/parse (browser locales, plus "bho-IN" for Bhojpuri)
LOCALE_HINTS: dict[str, str] = {v[3]: v[0] if v[3] != "en-IN" else "English (India)" for k, v in LANGS.items() if k != "bho"}
LOCALE_HINTS["bho-IN"] = "Bhojpuri"


def norm_code(lang: str | None) -> str:
    """'ta-IN' / 'TA' / 'bho' -> a supported code, else 'en'."""
    l = (lang or "en").strip().lower().replace("_", "-")
    if l.startswith("bho"):
        return "bho"
    l = l.split("-")[0][:2]
    return l if l in LANGS else "en"


def name(code: str) -> str:
    return LANGS.get(code, LANGS["en"])[0]


def script_rules() -> str:
    """One line per non-Latin language for model prompts."""
    return "; ".join(f"{v[0]}: {v[2]} script" for k, v in LANGS.items() if k != "en")


def ascii_digits(text: str) -> str:
    """Indic and Arabic-Indic digits (१० ১০ ੧੦ ૧૦ ୧୦ ௧௦ ౧౦ ೧೦ ൧൦ ١٠ ۱۰) -> 10. Speech models sometimes write
    numbers in the language's own digits; PINs, quantities and the parsers expect 0-9."""
    import unicodedata

    if not text or text.isascii():
        return text or ""
    return "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() and not ch.isascii()
                   else ch for ch in text)
