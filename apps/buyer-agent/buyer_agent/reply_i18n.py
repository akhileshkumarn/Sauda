"""Short restock confirmations in the owner's language. Product names stay as printed on the pack;
amounts use 0-9 digits and the rupee sign. Missing languages fall back to English."""
from __future__ import annotations

T: dict[str, dict[str, str]] = {
    "en": {"added": "Added {items}", "set": "{name} now {qty}", "remove": "Removed {name}", "keep": "Keeping {name}",
           "switch": "Switched to {name}", "budget": "Budget set to {amt}", "total": "Total up to {amt} for {n} {items_word}",
           "item": "item", "items": "items", "nomatch": "I could not match: {items}", "dq": "(default qty, edit it)", "and": " and "},
    "hi": {"added": "{items} जोड़ दिए", "set": "{name} अब {qty}", "remove": "{name} हटा दिया", "keep": "{name} रखा",
           "switch": "{name} पर बदल दिया", "budget": "बजट {amt} रखा", "total": "कुल {amt} तक, {n} {items_word}",
           "item": "आइटम", "items": "आइटम", "nomatch": "ये नहीं मिले: {items}", "dq": "(अंदाज़न मात्रा, बदल सकते हैं)", "and": " और "},
    "bho": {"added": "{items} जोड़ दिहल गइल", "set": "{name} अब {qty}", "remove": "{name} हटा दिहल गइल", "keep": "{name} रख लिहल गइल",
            "switch": "{name} पर बदल दिहल गइल", "budget": "बजट {amt} रखल गइल", "total": "कुल {amt} ले, {n} {items_word}",
            "item": "गो सामान", "items": "गो सामान", "nomatch": "ई ना मिलल: {items}", "dq": "(अंदाजा मात्रा, बदल सकीलें)", "and": " आ "},
    "te": {"added": "{items} జోడించాను", "set": "{name} ఇప్పుడు {qty}", "remove": "{name} తీసేశాను", "keep": "{name} ఉంచాను",
           "switch": "{name} కి మార్చాను", "budget": "బడ్జెట్ {amt}", "total": "మొత్తం {amt} వరకు, {n} {items_word}",
           "item": "వస్తువు", "items": "వస్తువులు", "nomatch": "ఇవి దొరకలేదు: {items}", "dq": "(అంచనా పరిమాణం, మార్చవచ్చు)", "and": " మరియు "},
    "ta": {"added": "{items} சேர்த்தேன்", "set": "{name} இப்போது {qty}", "remove": "{name} நீக்கினேன்", "keep": "{name} வைத்துள்ளேன்",
           "switch": "{name} ஆக மாற்றினேன்", "budget": "பட்ஜெட் {amt}", "total": "மொத்தம் {amt} வரை, {n} {items_word}",
           "item": "பொருள்", "items": "பொருட்கள்", "nomatch": "இவை கிடைக்கவில்லை: {items}", "dq": "(தோராய அளவு, மாற்றலாம்)", "and": " மற்றும் "},
    "kn": {"added": "{items} ಸೇರಿಸಿದೆ", "set": "{name} ಈಗ {qty}", "remove": "{name} ತೆಗೆದೆ", "keep": "{name} ಇಟ್ಟುಕೊಂಡೆ",
           "switch": "{name} ಗೆ ಬದಲಾಯಿಸಿದೆ", "budget": "ಬಜೆಟ್ {amt}", "total": "ಒಟ್ಟು {amt} ವರೆಗೆ, {n} {items_word}",
           "item": "ವಸ್ತು", "items": "ವಸ್ತುಗಳು", "nomatch": "ಇವು ಸಿಗಲಿಲ್ಲ: {items}", "dq": "(ಅಂದಾಜು ಪ್ರಮಾಣ, ಬದಲಿಸಬಹುದು)", "and": " ಮತ್ತು "},
    "ml": {"added": "{items} ചേർത്തു", "set": "{name} ഇപ്പോൾ {qty}", "remove": "{name} നീക്കി", "keep": "{name} നിലനിർത്തി",
           "switch": "{name} ആക്കി മാറ്റി", "budget": "ബജറ്റ് {amt}", "total": "ആകെ {amt} വരെ, {n} {items_word}",
           "item": "സാധനം", "items": "സാധനങ്ങൾ", "nomatch": "ഇവ കണ്ടെത്താനായില്ല: {items}", "dq": "(ഏകദേശ അളവ്, മാറ്റാം)", "and": ", "},
    "mr": {"added": "{items} जोडले", "set": "{name} आता {qty}", "remove": "{name} काढले", "keep": "{name} ठेवले",
           "switch": "{name} वर बदलले", "budget": "बजेट {amt}", "total": "एकूण {amt} पर्यंत, {n} {items_word}",
           "item": "वस्तू", "items": "वस्तू", "nomatch": "हे सापडले नाही: {items}", "dq": "(अंदाजे प्रमाण, बदलू शकता)", "and": " आणि "},
    "bn": {"added": "{items} যোগ করেছি", "set": "{name} এখন {qty}", "remove": "{name} বাদ দিয়েছি", "keep": "{name} রেখেছি",
           "switch": "{name}-এ বদলেছি", "budget": "বাজেট {amt}", "total": "মোট {amt} পর্যন্ত, {n} {items_word}",
           "item": "টি পণ্য", "items": "টি পণ্য", "nomatch": "এগুলো মেলেনি: {items}", "dq": "(আনুমানিক পরিমাণ, বদলাতে পারেন)", "and": " এবং "},
    "gu": {"added": "{items} ઉમેર્યા", "set": "{name} હવે {qty}", "remove": "{name} કાઢી નાખ્યું", "keep": "{name} રાખ્યું",
           "switch": "{name} માં બદલ્યું", "budget": "બજેટ {amt}", "total": "કુલ {amt} સુધી, {n} {items_word}",
           "item": "વસ્તુ", "items": "વસ્તુઓ", "nomatch": "આ મળ્યું નહીં: {items}", "dq": "(અંદાજિત જથ્થો, બદલી શકો)", "and": " અને "},
    "pa": {"added": "{items} ਜੋੜ ਦਿੱਤੇ", "set": "{name} ਹੁਣ {qty}", "remove": "{name} ਹਟਾ ਦਿੱਤਾ", "keep": "{name} ਰੱਖਿਆ",
           "switch": "{name} ਵਿੱਚ ਬਦਲਿਆ", "budget": "ਬਜਟ {amt}", "total": "ਕੁੱਲ {amt} ਤੱਕ, {n} {items_word}",
           "item": "ਚੀਜ਼", "items": "ਚੀਜ਼ਾਂ", "nomatch": "ਇਹ ਨਹੀਂ ਮਿਲੇ: {items}", "dq": "(ਅੰਦਾਜ਼ਨ ਮਾਤਰਾ, ਬਦਲ ਸਕਦੇ ਹੋ)", "and": " ਅਤੇ "},
    "or": {"added": "{items} ଯୋଡ଼ିଲି", "set": "{name} ଏବେ {qty}", "remove": "{name} ବାହାର କଲି", "keep": "{name} ରଖିଲି",
           "switch": "{name} କୁ ବଦଳାଇଲି", "budget": "ବଜେଟ୍ {amt}", "total": "ମୋଟ {amt} ପର୍ଯ୍ୟନ୍ତ, {n} {items_word}",
           "item": "ଟି ଜିନିଷ", "items": "ଟି ଜିନିଷ", "nomatch": "ଏଗୁଡ଼ିକ ମିଳିଲା ନାହିଁ: {items}", "dq": "(ଆନୁମାନିକ ପରିମାଣ, ବଦଳାଇପାରିବେ)", "and": " ଓ "},
    "ur": {"added": "{items} شامل کر دیے", "set": "{name} اب {qty}", "remove": "{name} ہٹا دیا", "keep": "{name} رکھ لیا",
           "switch": "{name} میں بدل دیا", "budget": "بجٹ {amt}", "total": "کل {amt} تک، {n} {items_word}",
           "item": "چیز", "items": "اشیاء", "nomatch": "یہ نہیں ملے: {items}", "dq": "(اندازاً مقدار، بدل سکتے ہیں)", "and": " اور "},
}


def t(lang: str | None) -> dict[str, str]:
    from .languages import norm_code
    return T.get(norm_code(lang), T["en"])
