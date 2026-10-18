'use client';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { searchProducts } from '@/lib/api';
import { cap1, ceilingSource, istDate, rupees } from '@/lib/format';
import type { Clarification, Draft, DraftLine, Product, ProductRef } from '@/lib/types';
import { MandateForm } from './MandateForm';
import { ProductSearch } from './ProductSearch';
import { Callout, Icon, Money } from './ui';
import { InfoTip } from './ui-client';

export const QTY_MIN = 1;
export const QTY_MAX = 5000;
const clampQty = (n: number) => Math.max(QTY_MIN, Math.min(QTY_MAX, Math.round(n) || QTY_MIN));

type EditLine = DraftLine & { applied?: boolean; added?: boolean };

function fromProduct(p: Product, qty = 1, extra: Partial<EditLine> = {}): EditLine {
  return {
    gtin: p.gtin, name: p.name, brand: p.brand, pack_size: p.pack_size, category: p.category || undefined,
    qty, qty_source: 'owner', requested_qty: qty, suggested_qty: null, suggestion_reason: null, confidence: 'high',
    last_paid_paise: null, ceiling_paise: p.ceiling_paise, ceiling_source: p.ceiling_source, ceiling_as_of: p.ceiling_as_of || undefined,
    reason: 'Added by you', added: true, ...extra,
  };
}

/** "Dodla · Ghee · 1 L": brand first when the catalogue name lacks it. */
function refLabel(r: ProductRef): string {
  const name = r.name ? r.name[0].toUpperCase() + r.name.slice(1) : r.name;
  const brand = r.brand && !r.name.toLowerCase().includes(r.brand.toLowerCase()) ? r.brand : null;
  const pack = r.pack_size && !r.name.toLowerCase().includes(r.pack_size.toLowerCase()) ? r.pack_size : null;
  return [brand, name, pack].filter(Boolean).join(' · ');
}

async function resolveProduct(ref: ProductRef): Promise<Product | null> {
  const hits = await searchProducts(ref.name, 20);
  return hits.find((h) => h.gtin === ref.gtin) || null;
}

/** Legacy chat draft (local state) + mandate form. */
export function DraftCard({ draft }: { draft: Draft }) {
  const [lines, setLines] = useState<EditLine[]>(() => draft.lines.map((l) => ({ ...l, qty: clampQty(l.qty) })));
  return (
    <div className="stack lg" style={{ alignSelf: 'stretch' }}>
      <DraftEditor draft={draft} lines={lines} setLines={setLines} />
      <MandateForm draft={draft} lines={lines} />
    </div>
  );
}

export type { EditLine };
type SetLines = (f: (ls: EditLine[]) => EditLine[]) => void;

/** Draft review: the owner's numbers stay the owner's. Suggestions are opt-in per line.
 *  Controlled: the session page owns `lines` and autosaves them. */
export function DraftEditor({ draft, lines, setLines, readOnly, highlight, title = 'Check your restock', onClarify, footer, hideHead }: {
  draft: Draft; lines: EditLine[]; setLines: SetLines; readOnly?: boolean; highlight?: Set<string>; title?: string;
  /** Session mode: answer a draft clarification by sending a turn instead of editing locally. */
  onClarify?: (c: Clarification, opt: ProductRef) => void;
  footer?: ReactNode;
  /** Session mode shows the count and total in its own summary bar. */
  hideHead?: boolean;
}) {
  const [replacing, setReplacing] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [answered, setAnswered] = useState<Record<string, string>>({});
  const [note, setNote] = useState<string | null>(null);
  const [lookupErr, setLookupErr] = useState<string | null>(null);

  const atCeiling = useMemo(() => lines.reduce((s, l) => s + l.qty * l.ceiling_paise, 0), [lines]);
  const totalUnits = lines.reduce((s, l) => s + l.qty, 0);
  const suggestions = lines.filter((l) => l.suggested_qty && l.suggested_qty !== l.qty && !l.applied);

  const update = (gtin: string, f: (l: EditLine) => EditLine) => setLines((ls) => ls.map((l) => (l.gtin === gtin ? f(l) : l)));
  const setQty = (gtin: string, q: number) => update(gtin, (l) => ({ ...l, qty: clampQty(q) }));
  const remove = (gtin: string) => {
    const l = lines.find((x) => x.gtin === gtin);
    setLines((ls) => ls.filter((x) => x.gtin !== gtin));
    setNote(l ? `Removed ${l.name}.` : null);
  };
  const replaceWith = (gtin: string, p: Product) => {
    if (lines.some((l) => l.gtin === p.gtin && l.gtin !== gtin)) { setNote(`${p.name} is already in the list.`); setReplacing(null); return; }
    update(gtin, (l) => ({ ...fromProduct(p, l.qty), owner_words: l.owner_words, requested_qty: l.requested_qty, qty_source: l.qty_source, reason: `Replaced “${l.name}”`, added: false }));
    setReplacing(null);
    setNote(`Replaced with ${p.name}.`);
  };
  const add = (p: Product) => {
    if (lines.some((l) => l.gtin === p.gtin)) { setNote(`${p.name} is already in the list.`); setAdding(false); return; }
    setLines((ls) => [...ls, fromProduct(p, 1)]);
    setAdding(false);
    setNote(`Added ${p.name}. Set the quantity.`);
  };
  async function pickAlternative(line: EditLine, alt: ProductRef) {
    setLookupErr(null);
    if (alt.gtin === line.gtin) { update(line.gtin, (l) => ({ ...l, confidence: 'high' })); setNote(`Kept ${line.name}.`); return; }
    try {
      const p = await resolveProduct(alt);
      if (!p) { setLookupErr(`Could not find ${alt.name} in the catalogue.`); return; }
      replaceWith(line.gtin, p);
    } catch (e) { setLookupErr(e instanceof Error ? e.message : String(e)); }
  }
  async function answer(c: Clarification, opt: ProductRef) {
    setLookupErr(null);
    if (onClarify) { setAnswered((a) => ({ ...a, [c.owner_words]: opt.name })); onClarify(c, opt); return; }
    try {
      const p = await resolveProduct(opt);
      if (!p) { setLookupErr(`Could not find ${opt.name} in the catalogue.`); return; }
      const cur = c.gtin ? lines.find((l) => l.gtin === c.gtin) : undefined;
      if (cur) {
        if (cur.gtin !== p.gtin) replaceWith(cur.gtin, p); else setNote(`Kept ${p.name}.`);
      } else {
        if (!lines.some((l) => l.gtin === p.gtin)) setLines((ls) => [...ls, fromProduct(p, 1, { owner_words: c.owner_words, reason: `You said “${c.owner_words}”` })]);
        setNote(`Added ${p.name}. Set the quantity.`);
      }
      setAnswered((a) => ({ ...a, [c.owner_words]: p.name }));
    } catch (e) { setLookupErr(e instanceof Error ? e.message : String(e)); }
  }

  const clarFor = (gtin: string) => (draft.clarifications || []).find((c) => c.gtin === gtin && !answered[c.owner_words]);
  const lineGtins = new Set(lines.map((l) => l.gtin));
  const looseClar = (draft.clarifications || []).filter((c) => !answered[c.owner_words] && !(c.gtin && lineGtins.has(c.gtin)));
  const unmatched = (draft.unmatched || []).map((u) => (typeof u === 'string' ? u : u.owner_words || u.text || '')).filter(Boolean);
  const pcts = suggestions.map((l) => Math.round(((l.suggested_qty! - l.qty) / Math.max(1, l.qty)) * 100)).filter((x) => x > 0);
  const pctText = pcts.length ? (Math.min(...pcts) === Math.max(...pcts) ? `+${pcts[0]}%` : `+${Math.min(...pcts)}–${Math.max(...pcts)}%`) : '';
  const fest = draft.festival ? `${draft.festival[0].toUpperCase()}${draft.festival.slice(1)} suggestion` : 'Suggestion';

  return (
    <section className="stack" aria-label={title}>
      {!hideHead && (
        <div className="section-h">
          <h2>{title}</h2>
          <span className="small muted num">{lines.length} {lines.length === 1 ? 'item' : 'items'} · up to <Money paise={atCeiling} whole className="strong" /></span>
        </div>
      )}
      {draft.budget_notes?.map((n) => <Callout key={n} tone="warn">{n}</Callout>)}
      {!readOnly && suggestions.length > 0 && (
        <div className="inline-banner">
          <span className="grow"><b>{fest}</b> · {pctText} on {suggestions.length} {suggestions.length === 1 ? 'item' : 'items'}</span>
          <InfoTip label="About this suggestion">An assumption, not your sales history.{draft.assumptions?.length ? ` ${draft.assumptions.join('; ')}.` : ''} Nothing changes unless you apply it.</InfoTip>
          <button type="button" className="linkbtn" style={{ minHeight: 36 }} onClick={() => setLines((ls) => ls.map((l) => (l.suggested_qty && !l.applied && l.suggested_qty !== l.qty ? { ...l, qty: clampQty(l.suggested_qty), applied: true } : l)))}>Apply</button>
        </div>
      )}
      {!readOnly && looseClar.map((c) => (
        <ChoiceRow key={c.owner_words} q={`${c.question}`} options={c.options} current={c.gtin} onPick={(o) => answer(c, o)} onSkip={() => setAnswered((a) => ({ ...a, [c.owner_words]: 'skip' }))} />
      ))}
      {unmatched.length > 0 && <span className="small muted">Not in the catalogue: {unmatched.join(', ')}.</span>}

      <ul className="list rf-lines" style={{ listStyle: 'none', padding: 0, margin: 0 }} aria-label="Restock items">
        {lines.map((l) => {
          const said = l.requested_qty;
          const inferred = l.qty_source === 'inferred' && !l.applied;
          const clar = clarFor(l.gtin);
          const open = expanded === l.gtin;
          const pack = l.pack_size && !l.name.toLowerCase().includes(l.pack_size.toLowerCase()) ? l.pack_size : null;
          const sug = !readOnly && !!l.suggested_qty && l.suggested_qty !== l.qty && !l.applied ? l.suggested_qty - l.qty : 0;
          return (
            <li key={l.gtin} data-line className={`li ${highlight?.has(l.gtin) ? 'changed' : ''}`}>
              <div className={`line-row ${readOnly ? 'ro' : ''}`}>
                <button type="button" className="line-name" style={{ gridArea: 'name' }} aria-expanded={open} title={cap1(l.name)} onClick={() => setExpanded(open ? null : l.gtin)}>
                  <span className="nm">{cap1(l.name)}</span>
                  {(pack || inferred) && <span className="meta">{[pack, inferred ? 'default qty' : null].filter(Boolean).join(' · ')}</span>}
                </button>
                <div className="line-ctrl" style={{ gridArea: 'ctrl' }}>
                  {readOnly ? <span className="num muted">{l.qty} ×</span> : <QtyStepper value={l.qty} name={l.name} onChange={(q) => update(l.gtin, (x) => ({ ...x, qty: clampQty(q), applied: x.applied && clampQty(q) === x.suggested_qty }))} />}
                  {sug !== 0 && (
                    <button type="button" className="linkbtn" style={{ fontSize: 12.5 }}
                      onClick={() => update(l.gtin, (x) => ({ ...x, qty: clampQty(x.suggested_qty!), applied: true }))}
                      aria-label={`Apply suggested ${l.suggested_qty} for ${l.name}${l.suggestion_reason ? `: ${l.suggestion_reason}` : ''}`} title={l.suggestion_reason || undefined}>
                      {sug > 0 ? '+' : ''}{sug} suggested
                    </button>
                  )}
                  {!readOnly && l.applied && said != null && <button type="button" className="linkbtn muted" style={{ fontSize: 12.5 }} onClick={() => update(l.gtin, (x) => ({ ...x, qty: clampQty(said), applied: false }))}>Back to {said}</button>}
                </div>
                <span className="line-amt" style={{ gridArea: 'amt' }} aria-label={`Up to ${rupees(l.qty * l.ceiling_paise)}`}><Money paise={l.qty * l.ceiling_paise} /></span>
                {!readOnly ? (
                  <LineMenu name={l.name} onReplace={() => setReplacing(replacing === l.gtin ? null : l.gtin)} onRemove={() => remove(l.gtin)} />
                ) : <span style={{ gridArea: 'more' }} />}
              </div>
              {open && (
                <div className="line-detail">
                  <span title={l.ceiling_as_of ? `as of ${istDate(l.ceiling_as_of)}` : undefined}>Ceiling <b className="num" style={{ color: 'var(--ink)', fontWeight: 500 }}>{rupees(l.ceiling_paise)}</b>/unit · {ceilingSource(l.ceiling_source)}{l.ceiling_as_of ? `, ${istDate(l.ceiling_as_of)}` : ''}</span>
                  {said != null && <span>You said {said}{l.applied ? ' · suggestion applied' : ''}</span>}
                  {inferred && <span>No number given, so Sauda used its usual quantity.</span>}
                  {l.suggestion_reason && sug !== 0 && <span>{l.suggestion_reason}</span>}
                </div>
              )}
              {readOnly ? null : clar ? (
                <ChoiceRow q={shortQ(clar.question)} options={clar.options} current={clar.gtin} onPick={(o) => answer(clar, o)} onSkip={() => setAnswered((a) => ({ ...a, [clar.owner_words]: 'skip' }))} />
              ) : l.confidence === 'low' && l.alternatives && l.alternatives.length > 0 ? (
                <ChoiceRow q="Right item?" options={l.alternatives} current={l.gtin} onPick={(a) => pickAlternative(l, a)} onSkip={() => update(l.gtin, (x) => ({ ...x, confidence: 'high' }))} skipLabel="Yes, keep" />
              ) : null}
              {replacing === l.gtin && (
                <div style={{ paddingTop: 10 }}><ProductSearch label={`Replace ${l.name} with`} initial={l.category || ''} exclude={[l.gtin]} onPick={(p) => replaceWith(l.gtin, p)} onCancel={() => setReplacing(null)} /></div>
              )}
            </li>
          );
        })}
      </ul>

      {lines.length === 0 && !readOnly && (
        <div className="rf-empty-list">
          <span className="ico" aria-hidden><Icon name="cart" size={20} /></span>
          <b>No items yet</b>
          <span className="small">Say or type your list below, like “10 atta, 20 oil, budget 8000”.</span>
        </div>
      )}

      {readOnly ? null : adding ? (
        <ProductSearch label="Add an item" onPick={add} onCancel={() => setAdding(false)} exclude={lines.map((l) => l.gtin)} />
      ) : (
        <div className="row between wrap sm">
          <button type="button" className="linkbtn row sm" style={{ minHeight: 44, display: 'inline-flex', gap: 6 }} onClick={() => setAdding(true)}><Icon name="plus" size={16} />Add item</button>
          <span className="xs muted row sm" style={{ gap: 0 }}>Ceiling = most Sauda may pay
            <InfoTip label="About ceilings">Ceilings are the most Sauda may pay per unit, not market prices. Tap an item to see its ceiling. Suggestions apply only when you tap them.{draft.stated_budget_paise ? ` Your budget: ${rupees(draft.stated_budget_paise, true)}.` : ''}</InfoTip>
          </span>
        </div>
      )}
      <span className="xs muted" role="status" aria-live="polite">{note || ''}</span>
      {lookupErr && <Callout tone="bad">{lookupErr}</Callout>}
      {footer}
    </section>
  );
}

function LineMenu({ name, onReplace, onRemove }: { name: string; onReplace: () => void; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: PointerEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', off); document.addEventListener('keydown', k);
    return () => { document.removeEventListener('pointerdown', off); document.removeEventListener('keydown', k); };
  }, [open]);
  return (
    <div className="line-more" ref={ref} style={{ gridArea: 'more' }}>
      <button type="button" className="btn ghost icon sm" aria-haspopup="menu" aria-expanded={open} aria-label={`More for ${name}`} onClick={() => setOpen((x) => !x)}><Icon name="more" size={18} stroke={2} /></button>
      {open && (
        <div className="menu" role="menu">
          <button type="button" role="menuitem" aria-label={`Replace ${name}`} onClick={() => { setOpen(false); onReplace(); }}><Icon name="swap" size={16} />Replace</button>
          <button type="button" role="menuitem" className="bad" aria-label={`Remove ${name}`} onClick={() => { setOpen(false); onRemove(); }}><Icon name="trash" size={16} />Remove</button>
        </div>
      )}
    </div>
  );
}

function shortQ(q: string): string { const i = q.indexOf(':'); return i > 0 && i < 40 ? q.slice(0, i) + '?' : q; }

/** One compact row: question + option chips. Collapses once answered (the parent drops it). */
function ChoiceRow({ q, options, current, onPick, onSkip, skipLabel = 'Skip' }: { q: string; options: ProductRef[]; current?: string; onPick: (o: ProductRef) => void; onSkip: () => void; skipLabel?: string }) {
  return (
    <div className="ask" role="group" aria-label={q}>
      <span className="ask-q">{q}</span>
      <div className="chips rf-chips">
        {options.slice(0, 4).map((o) => (
          <button type="button" key={o.gtin} className="chip-btn" aria-pressed={o.gtin === current} onClick={() => onPick(o)}>
            {o.gtin === current ? <Icon name="check" size={14} /> : null}{refLabel(o)}
          </button>
        ))}
        <button type="button" className="chip-btn rf-skip" onClick={onSkip}>{skipLabel}</button>
      </div>
    </div>
  );
}

export function QtyStepper({ value, onChange, name }: { value: number; onChange: (n: number) => void; name: string }) {
  const [text, setText] = useState<string | null>(null);
  return (
    <div className="stepper" role="group" aria-label={`Quantity for ${name}`}>
      <button type="button" onClick={() => onChange(value - 1)} disabled={value <= QTY_MIN} aria-label={`One less ${name}`}>−</button>
      <input inputMode="numeric" pattern="[0-9]*" value={text ?? String(value)} aria-label={`Quantity for ${name}`}
        onChange={(e) => setText(e.target.value.replace(/\D/g, '').slice(0, 4))}
        onBlur={() => { if (text !== null) { onChange(parseInt(text || '1', 10)); setText(null); } }}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }} />
      <button type="button" onClick={() => onChange(value + 1)} disabled={value >= QTY_MAX} aria-label={`One more ${name}`}>+</button>
    </div>
  );
}
