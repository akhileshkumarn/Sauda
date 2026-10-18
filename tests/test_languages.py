"""Supported owner languages: code / locale validation, onboarding prompts present for every language, and the
small deterministic pieces (Indic digits, yes / no words) the voice paths rely on."""
import re

import pytest

from buyer_agent import languages, onboarding_agent as ob
from buyer_agent.services import sessions, voice

NEW = ["ta", "kn", "ml", "mr", "bn", "gu", "pa", "or", "ur", "bho"]
ALL = ["en", "hi", "te", *NEW]
SCRIPT = {  # a character range each language's prompts must use (Latin acronyms like PIN / GST are allowed too)
    "hi": "ऀ-ॿ", "te": "ఀ-౿", "ta": "஀-௿", "kn": "ಀ-೿", "ml": "ഀ-ൿ",
    "mr": "ऀ-ॿ", "bn": "ঀ-৿", "gu": "઀-૿", "pa": "਀-੿", "or": "଀-୿",
    "ur": "؀-ۿ", "bho": "ऀ-ॿ",
}


def test_supported_codes():
    assert list(languages.CODES) == ALL
    assert languages.BETA == {"bho"}


@pytest.mark.parametrize("raw,code", [
    ("ta", "ta"), ("ta-IN", "ta"), ("KN-in", "kn"), ("ml_IN", "ml"), ("mr", "mr"), ("bn-IN", "bn"), ("gu", "gu"),
    ("pa-IN", "pa"), ("or-IN", "or"), ("ur", "ur"), ("bho", "bho"), ("bho-IN", "bho"), ("hi-IN", "hi"), ("te", "te"),
    (None, "en"), ("", "en"), ("xx", "en"), ("fr-FR", "en"), ("zz-IN", "en"),
])
def test_lang_validation(raw, code):
    assert languages.norm_code(raw) == code
    assert ob.lang_of(raw) == code


def test_voice_lang_hints():
    for loc in ["en-IN", "hi-IN", "te-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN", "bn-IN", "gu-IN", "pa-IN", "or-IN", "ur-IN", "bho-IN"]:
        assert loc in voice.LANG_HINTS
    assert "fr-FR" not in voice.LANG_HINTS
    assert voice._norm_lang("ta") == "ta" and voice._norm_lang("bho") == "bho" and voice._norm_lang("xx") == "other"
    for code in ALL:
        assert code in voice.LANG_NAMES


def test_transcribe_prompt_formats():
    p = voice.TRANSCRIBE_PROMPT.format(hint="", scripts=languages.script_rules(), codes=voice._CODES)
    assert "Tamil: Tamil script" in p and "Punjabi: Gurmukhi script" in p and "bho" in p and "{" not in p


@pytest.mark.parametrize("lang", ALL)
@pytest.mark.parametrize("role", ["buyer", "seller"])
def test_opening_and_key_prompts_exist(lang, role):
    keys = ["opening", "display_name", "constitution", "gst_registered", "gstin", "pin", "address_line", "rep_name",
            "rep_role", "products", "service_area", "brand_claims", "fssai", "consent"]
    for k in keys:
        v = ob.Q[k][role] if role in ob.Q[k] else ob.Q[k]
        assert v.get(lang), (k, lang)
        if lang in SCRIPT:
            assert re.search(f"[{SCRIPT[lang]}]", v[lang]), (k, lang)
    for table in (ob.CONFIRM_Q, ob.HAVE, ob.GOT, ob.SKIPPED, ob.MISSED, ob.AADHAAR_MSG, ob.BLOCKED_MSG):
        assert lang in table and table[lang].strip()
    for k, tmpl in ob.MSG.items():
        assert set(re.findall(r"\{\w+\}", tmpl[lang])) == set(re.findall(r"\{\w+\}", tmpl["en"])), (k, lang)


def test_unknown_lang_falls_back_to_english():
    assert ob.SKIPPED["xx"] == ob.SKIPPED["en"]
    assert ob.question_for("pin", "buyer", "en", None) == ob.Q["pin"]["en"]


def test_city_confirm_and_problem_texts_render_in_every_language():
    pend = {"pin": "600017", "district": "Chennai", "state": "Tamil Nadu", "city": "Madras"}
    for lang in ALL:
        q = ob.question_for("city_confirm", "buyer", lang, pend)
        assert "600017" in q and "Chennai" in q
        assert "500" in ob._problem_text("pin_unknown:500999", lang)
        assert ob._problem_text("pin_invalid", lang)


def test_start_uses_language(monkeypatch):
    made = {}
    monkeypatch.setattr(ob.tn, "create", lambda coll, oid, s: made.update(s=s))
    s = ob.start("fx-user-t", "buyer", "ta-IN", True)
    assert s["lang"] == "ta" and s["question"] == ob.Q["opening"]["buyer"]["ta"]


@pytest.mark.parametrize("word", ["ஆமாம்", "ಹೌದು", "അതെ", "होय", "হ্যাঁ", "હા", "ਹਾਂ", "ہاں", "हँ"])
def test_yes_words(word):
    assert ob.YES.match(word)


@pytest.mark.parametrize("word", ["இல்லை", "ಇಲ್ಲ", "ഇല്ല", "नाही", "না", "ના", "ਨਹੀਂ", "نہیں"])
def test_no_words(word):
    assert ob.NO.match(word)


def test_indic_digits_become_ascii():
    assert languages.ascii_digits("১০ প্যাকেট, ௨௦ உப்பு, ੧੨ ਤੇਲ, ۱۲ تیل, १०") == "10 প্যাকেট, 20 உப்பு, 12 ਤੇਲ, 12 تیل, 10"
    assert languages.ascii_digits("10 packets") == "10 packets"
    assert sessions.words_to_digits("১০ প্যাকেট আটা").startswith("10 ")


def test_restock_reply_in_owner_language():
    from buyer_agent.reply_i18n import T
    from buyer_agent.services.sessions import build_reply
    from buyer_agent.languages import CODES
    assert set(CODES) <= set(T)
    keys = set(T["en"])
    for code, row in T.items():
        assert set(row) == keys, code
    d = {"lines": [{"gtin": "1"}, {"gtin": "2"}], "budget_estimate_paise": 250000}
    applied = [{"op": "add_line", "qty": 10, "name": "Aashirvaad Atta"}, {"op": "set_qty", "qty": 8, "name": "Oil"}]
    en = build_reply(applied, d, None, [])
    assert en.startswith("Added 10 Aashirvaad Atta") and "Total up to" in en
    ta = build_reply(applied, d, None, [], "ta-IN")
    assert "சேர்த்தேன்" in ta and "Aashirvaad Atta" in ta and "Added" not in ta
    assert "जोड़ दिए" in build_reply(applied, d, None, [], "hi")
    assert build_reply(applied, d, None, [], "xx") == en
