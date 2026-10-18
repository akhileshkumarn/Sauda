'use client';
// Interactive primitives (need hooks). Static primitives live in ./ui.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Icon } from './ui';

/** Small "i" button with a popover tip (hover, focus or tap). */
export function InfoTip({ children, label = 'More info', align }: { children: ReactNode; label?: string; align?: 'left' }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: PointerEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', off);
    return () => document.removeEventListener('pointerdown', off);
  }, [open]);
  return (
    <span ref={ref} className={`info-tip ${align || ''} ${open ? 'open' : ''}`}>
      <button type="button" aria-label={label} aria-expanded={open} onClick={() => setOpen((x) => !x)}><Icon name="info" size={16} /></button>
      <span className="tip" role="tooltip">{children}</span>
    </span>
  );
}

/** Segmented control: small text toggle. */
export function SegmentedControl<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => <button key={o.value} type="button" aria-pressed={o.value === value} title={o.title} onClick={() => onChange(o.value)}>{o.label}</button>)}
    </div>
  );
}

/** Bottom sheet on mobile, centred popover on desktop. */
export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title?: ReactNode; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="sheet-backdrop" onClick={onClose} aria-hidden />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}>
        {title && <div className="row between"><h2 style={{ fontSize: 17 }}>{title}</h2><button type="button" className="btn ghost icon sm" aria-label="Close" onClick={onClose}><Icon name="x" /></button></div>}
        {children}
      </div>
    </>
  );
}

