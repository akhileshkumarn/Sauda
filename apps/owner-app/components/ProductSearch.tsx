'use client';
import { useEffect, useId, useRef, useState } from 'react';
import { searchProducts } from '@/lib/api';
import { rupees } from '@/lib/format';
import type { Product } from '@/lib/types';
import { Button, Icon } from './ui';

/** GET /products search, used to add a line or replace one. */
export function ProductSearch({ onPick, onCancel, label = 'Search products', initial = '', exclude = [] }:
  { onPick: (p: Product) => void; onCancel?: () => void; label?: string; initial?: string; exclude?: string[] }) {
  const [q, setQ] = useState(initial);
  const [res, setRes] = useState<Product[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const id = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => {
    const t = q.trim();
    if (t.length < 2) { setRes(null); setErr(null); return; }
    const ac = new AbortController();
    const h = setTimeout(() => {
      setBusy(true); setErr(null);
      searchProducts(t, 20, ac.signal)
        .then((r) => setRes(r))
        .catch((e) => { if (!ac.signal.aborted) setErr(e instanceof Error ? e.message : String(e)); })
        .finally(() => { if (!ac.signal.aborted) setBusy(false); });
    }, 250);
    return () => { clearTimeout(h); ac.abort(); };
  }, [q]);
  const shown = (res || []).filter((p) => !exclude.includes(p.gtin));
  return (
    <div className="stack sm" role="search">
      <label className="field" htmlFor={id}>{label}
        <div className="row sm">
          <input id={id} ref={inputRef} className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. ghee, Tata salt, Maggi"
            onKeyDown={(e) => { if (e.key === 'Escape') onCancel?.(); }} autoComplete="off" aria-describedby={`${id}-s`} />
          {onCancel && <Button variant="secondary" onClick={onCancel} aria-label="Close search">Cancel</Button>}
        </div>
      </label>
      <span id={`${id}-s`} className="xs faint" role="status" aria-live="polite">
        {busy ? 'Searching…' : err ? '' : res && q.trim().length >= 2 ? `${shown.length} ${shown.length === 1 ? 'match' : 'matches'}` : 'Type at least 2 letters'}
      </span>
      {err && <span className="xs" style={{ color: 'var(--bad)' }}>Search failed: {err}</span>}
      {shown.length > 0 && (
        <div className="search-results">
          {shown.map((p) => (
            <button key={p.gtin} type="button" onClick={() => onPick(p)}>
              <span className="stack xs" style={{ minWidth: 0 }}>
                <span className="small strong break">{p.name}</span>
                <span className="xs faint">{[p.brand, p.pack_size].filter(Boolean).join(' · ')}</span>
              </span>
              <span className="stack xs right"><span className="xs faint">ceiling</span><span className="small num strong">{rupees(p.ceiling_paise)}</span></span>
            </button>
          ))}
        </div>
      )}
      {res && q.trim().length >= 2 && !busy && shown.length === 0 && !err && (
        <span className="small muted row sm"><Icon name="info" />No product found in the catalogue. Try a brand or a shorter word.</span>
      )}
    </div>
  );
}
