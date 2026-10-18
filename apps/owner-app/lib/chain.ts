// Client-side hash-chain recomputation for the Trust Console tamper demo.
// canonical JSON = sorted keys, no whitespace, non-ASCII kept as UTF-8
// (byte-identical to sauda_trust.mandates.canonical:
//  json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)).
// Signatures are NOT checked here; the server's /verify does that with the KMS public key.
import type { LedgerEvent } from './types';

function escapeNonAscii(s: string): string {
  return s;
}

export function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    if (typeof value === 'number' && Number.isInteger(value)) return String(value);
    return escapeNonAscii(JSON.stringify(value) ?? 'null');
  }
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).filter((k) => obj[k] !== undefined).sort();
  return '{' + keys.map((k) => escapeNonAscii(JSON.stringify(k)) + ':' + canonical(obj[k])).join(',') + '}';
}

export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

export interface LocalCheck {
  seq: number;
  computed_hash: string;
  hash_ok: boolean;
  link_ok: boolean;
  /** true once any earlier event (or this one) failed: everything after a break is untrusted */
  after_break: boolean;
}

/** prev_hash(first) = sha256(negotiation_id); prev_hash(n) = payload_hash(n-1) (LLD-5). */
export async function recomputeChain(events: LedgerEvent[]): Promise<LocalCheck[]> {
  const sorted = [...events].sort((a, b) => a.seq - b.seq);
  const out: LocalCheck[] = [];
  let expectedPrev = sorted.length ? await sha256Hex(sorted[0].negotiation_id) : '';
  let broken = false;
  for (const ev of sorted) {
    const computed = await sha256Hex(canonical(ev.payload));
    const hash_ok = computed === ev.payload_hash;
    const link_ok = ev.prev_hash === expectedPrev;
    if (!hash_ok || !link_ok) broken = true;
    out.push({ seq: ev.seq, computed_hash: computed, hash_ok, link_ok, after_break: broken });
    expectedPrev = computed; // what the next event's prev_hash must equal
  }
  return out;
}
