'use client';
// Client-side latency marks per utterance/turn. Numbers only (no transcript text). Shown in the ?debug=1 panel.
import { useEffect, useState } from 'react';

export type MarkName = 'speech_start' | 'first_partial' | 'utterance_end' | 'final_transcript' | 'turn_sent' | 'turn_applied' | 'draft_rendered';
export const MARK_ORDER: MarkName[] = ['speech_start', 'first_partial', 'utterance_end', 'final_transcript', 'turn_sent', 'turn_applied', 'draft_rendered'];

export interface Utt {
  id: string;
  source: 'voice' | 'text';
  engine: 'webspeech' | 'recorder' | 'typed';
  marks: Partial<Record<MarkName, number>>;
  server?: { extract?: number; apply?: number; total?: number } | null;
  chars?: number;
}

const utts: Utt[] = [];
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
let seq = 0;

export function newUtt(source: Utt['source'], engine: Utt['engine']): string {
  const id = `u${Date.now().toString(36)}${(seq++).toString(36)}`;
  utts.unshift({ id, source, engine, marks: {} });
  if (utts.length > 30) utts.pop();
  emit();
  return id;
}
export function mark(id: string | null | undefined, name: MarkName, t = performance.now()) {
  const u = id ? utts.find((x) => x.id === id) : undefined;
  if (!u || u.marks[name] !== undefined) return;
  u.marks[name] = t;
  emit();
}
export function setServer(id: string, server: Utt['server'], chars?: number) {
  const u = utts.find((x) => x.id === id);
  if (!u) return;
  u.server = server; if (chars !== undefined) u.chars = chars;
  emit();
}
export function allUtts(): Utt[] { return utts; }

/** Milliseconds between two marks, or null. */
export function span(u: Utt, a: MarkName, b: MarkName): number | null {
  const x = u.marks[a]; const y = u.marks[b];
  return x !== undefined && y !== undefined ? Math.round(y - x) : null;
}

export function useLatency(): Utt[] {
  const [, set] = useState(0);
  useEffect(() => { const f = () => set((n) => n + 1); subs.add(f); return () => { subs.delete(f); }; }, []);
  return utts;
}

export function debugOn(): boolean {
  if (typeof window === 'undefined') return false;
  try { return new URLSearchParams(window.location.search).get('debug') === '1'; } catch { return false; }
}
