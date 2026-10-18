// Light/dark preference. Stored per browser; 'system' follows the OS setting.
export type ThemePref = 'light' | 'dark' | 'system';
const KEY = 'sauda-theme';

export function getThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function effectiveTheme(pref: ThemePref = getThemePref()): 'light' | 'dark' {
  if (pref !== 'system') return pref;
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function setThemePref(pref: ThemePref): void {
  try {
    if (pref === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, pref);
  } catch { /* storage blocked: still apply for this page */ }
  const root = document.documentElement;
  if (pref === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', pref);
  window.dispatchEvent(new CustomEvent('sauda-theme', { detail: pref }));
}

/** Inline script for <head>: applies the saved theme before first paint (no flash). */
export const THEME_BOOT = `try{var t=localStorage.getItem('${KEY}');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t)}catch(e){}`;
