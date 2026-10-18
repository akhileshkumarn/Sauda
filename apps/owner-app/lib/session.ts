'use client';
// Per-device conveniences only (the server is the source of truth).
const K = 'sauda.last_negotiation_id';
const P = 'sauda.product_names';
export function lastNegotiationId(): string | null {
  try { return localStorage.getItem(K); } catch { return null; }
}
export function rememberNegotiation(id: string) {
  try { localStorage.setItem(K, id); } catch { /* ignore */ }
}
/** Product names by GTIN, so signed-mandate screens can show names (mandate bodies only carry GTINs). */
export function rememberProducts(lines: { gtin: string; name: string }[]) {
  try {
    const cur = JSON.parse(localStorage.getItem(P) || '{}') as Record<string, string>;
    for (const l of lines) cur[l.gtin] = l.name;
    localStorage.setItem(P, JSON.stringify(cur));
  } catch { /* ignore */ }
}
export function productNames(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(P) || '{}'); } catch { return {}; }
}
