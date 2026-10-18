// Owner languages for voice restock and voice onboarding. One list, shared by both screens.
// `speech` is the Web Speech `lang` (browser recognition); `hint` is the `lang_hint` sent with recorder segments.
// Bhojpuri has no browser speech locale, so it listens as Hindi (hi-IN) and is marked beta.

export type LangCode = 'en' | 'hi' | 'te' | 'ta' | 'kn' | 'ml' | 'mr' | 'bn' | 'gu' | 'pa' | 'or' | 'ur' | 'bho';

export interface LangInfo {
  code: LangCode;
  native: string;
  english: string;
  speech: string;
  hint: string;
  beta?: string;
  rtl?: boolean;
}

export const LANGS: LangInfo[] = [
  { code: 'en', native: 'English', english: 'English', speech: 'en-IN', hint: 'en-IN' },
  { code: 'hi', native: 'हिन्दी', english: 'Hindi', speech: 'hi-IN', hint: 'hi-IN' },
  { code: 'te', native: 'తెలుగు', english: 'Telugu', speech: 'te-IN', hint: 'te-IN' },
  { code: 'ta', native: 'தமிழ்', english: 'Tamil', speech: 'ta-IN', hint: 'ta-IN' },
  { code: 'kn', native: 'ಕನ್ನಡ', english: 'Kannada', speech: 'kn-IN', hint: 'kn-IN' },
  { code: 'ml', native: 'മലയാളം', english: 'Malayalam', speech: 'ml-IN', hint: 'ml-IN' },
  { code: 'mr', native: 'मराठी', english: 'Marathi', speech: 'mr-IN', hint: 'mr-IN' },
  { code: 'bn', native: 'বাংলা', english: 'Bengali', speech: 'bn-IN', hint: 'bn-IN' },
  { code: 'gu', native: 'ગુજરાતી', english: 'Gujarati', speech: 'gu-IN', hint: 'gu-IN' },
  { code: 'pa', native: 'ਪੰਜਾਬੀ', english: 'Punjabi', speech: 'pa-IN', hint: 'pa-IN' },
  { code: 'or', native: 'ଓଡ଼ିଆ', english: 'Odia', speech: 'or-IN', hint: 'or-IN' },
  { code: 'ur', native: 'اردو', english: 'Urdu', speech: 'ur-IN', hint: 'ur-IN', rtl: true },
  { code: 'bho', native: 'भोजपुरी', english: 'Bhojpuri', speech: 'hi-IN', hint: 'bho-IN', beta: 'beta, listens as Hindi' },
];

export const LANG_KEY = 'sauda.voice.lang';

export function langInfo(code: string | null | undefined): LangInfo {
  return LANGS.find((l) => l.code === code) || LANGS[0];
}

/** The owner's saved choice. Older builds stored a locale ("hi-IN"); both forms are read. */
export function loadLang(): LangCode {
  try {
    const v = localStorage.getItem(LANG_KEY);
    if (!v) return 'en';
    const m = LANGS.find((l) => l.code === v) || LANGS.find((l) => l.code !== 'bho' && l.speech === v);
    return m ? m.code : 'en';
  } catch { return 'en'; }
}

export function saveLang(code: LangCode) {
  try { localStorage.setItem(LANG_KEY, code); } catch { /* ignore */ }
  try { window.dispatchEvent(new CustomEvent('sauda:lang', { detail: code })); } catch { /* ignore */ }
}
