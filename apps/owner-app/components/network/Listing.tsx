'use client';
import './network.css';
import './discover.css';
import { useEffect, useMemo, useState } from 'react';
import { ApiError } from '@/lib/api';
import { LISTING_CATEGORIES, areaLabel, emptyListing, errorDetail, titleCase, tnAreas, tnPutListing } from '@/lib/network';
import type { TnAreaKind, TnAreas, TnBusiness, TnDiscoverCard, TnListing, TnSummary } from '@/lib/types';
import { Button, Callout, SectionHead } from '../ui';
import { SupplierCard } from './Discover';

const PREVIEW_DIMS = ['identity', 'registration', 'address', 'operational', 'representative', 'distribution_authority'];

/** Seller-only settings: an opt-in listing in Find suppliers, with a live preview of the buyer-facing card. */
export function ListingSettings({ business, summary, onSaved }: { business: TnBusiness; summary?: TnSummary | null; onSaved?: () => void }) {
  const [l, setL] = useState<TnListing>(() => ({ ...emptyListing(), ...(business.listing || {}) }));
  const [version, setVersion] = useState(business.version);
  const [areas, setAreas] = useState<TnAreas | null>(null);
  const [areasErr, setAreasErr] = useState(false);
  const [stateSel, setStateSel] = useState<string>(() => (business.listing?.service_area?.states?.[0] || (business.address?.state || '').toUpperCase()));
  const [minRupees, setMinRupees] = useState(() => (business.listing?.min_order_paise ? String(Math.round(business.listing.min_order_paise / 100)) : ''));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad' | 'warn'; text: string } | null>(null);
  const [card, setCard] = useState<TnDiscoverCard | null>(null);

  useEffect(() => { tnAreas().then(setAreas).catch(() => setAreasErr(true)); }, []);
  const districts = useMemo(() => areas?.states.find((s) => s.state === stateSel)?.districts || [], [areas, stateSel]);
  const sa = l.service_area;
  const setArea = (patch: Partial<TnListing['service_area']>) => setL((x) => ({ ...x, service_area: { ...x.service_area, ...patch } }));
  const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const notesOver = (l.notes || '').length > 200;

  const preview: TnDiscoverCard = card || {
    bid: business.bid, display_name: business.display_name, city: business.address?.city, state: business.address?.state?.toUpperCase(), district: null,
    categories: l.categories, service_area: { ...sa, basis: 'self_declared', label: `${areaLabel(sa)} (self-declared)` },
    min_order_paise: minRupees ? Math.round(Number(minRupees) * 100) : null, notes: l.notes || null,
    trust: {
      category: summary?.category || 'additional_review_required', category_text: (summary?.category_label || 'Verification pending') + (business.sandbox ? '' : business.is_fixture ? ' (showcase business)' : ''),
      dims: (summary?.dimensions || []).filter((d) => PREVIEW_DIMS.includes(d.dim)).map((d) => ({ dim: d.dim, status: d.status, source_kind: d.source_kind })),
    },
    last_checked_at: summary?.dimensions?.map((d) => d.checked_at).filter(Boolean).sort().pop() || null,
    is_fixture: !!business.is_fixture, fixture_label: business.is_fixture ? 'Showcase business' : null, connection: 'none', rid: null,
  };
  useEffect(() => { setCard(null); }, [l, minRupees]);

  async function save() {
    setBusy(true); setMsg(null);
    const mo = minRupees.trim() ? Math.round(Number(minRupees) * 100) : null;
    if (mo !== null && (!Number.isFinite(mo) || mo < 0)) { setMsg({ tone: 'bad', text: 'Minimum order must be a number of rupees.' }); setBusy(false); return; }
    try {
      const r = await tnPutListing(business.bid, {
        version, listed: l.listed, categories: l.categories,
        service_area: { kind: sa.kind, districts: sa.kind === 'district' ? sa.districts : [], states: sa.kind === 'pan_india' ? [] : sa.states },
        min_order_paise: mo, notes: (l.notes || '').trim() || null,
      });
      setVersion(r.business.version);
      if (r.card) setTimeout(() => setCard(r.card || null), 0);
      setMsg({ tone: 'ok', text: l.listed ? 'Saved. Buyers in your delivery area can now find you.' : 'Saved. Your business is not listed.' });
      onSaved?.();
    } catch (e) {
      const d = errorDetail(e);
      const body = e instanceof ApiError ? ((e.body as { detail?: { invalid?: string[] } })?.detail?.invalid || []) : [];
      setMsg({ tone: 'bad', text: d.code === 'version_conflict' ? 'Your business changed elsewhere. Reload the page and try again.'
        : d.code === 'seller_role_required' ? 'Only supplier businesses can be listed.'
          : d.code === 'invalid_area' ? `${e instanceof Error ? e.message : 'Check the delivery area.'}${body.length ? ` (${body.map(titleCase).join(', ')})` : ''}`
            : e instanceof Error ? e.message : String(e) });
    } finally { setBusy(false); }
  }

  const kinds: { v: TnAreaKind; t: string; d: string }[] = [
    { v: 'district', t: 'Specific districts', d: 'Pick the districts you deliver to.' },
    { v: 'state', t: 'Whole state', d: 'Every district in the states you pick.' },
    { v: 'pan_india', t: 'All India', d: 'You deliver anywhere in India.' },
  ];

  return (
    <section className="stack sm" aria-labelledby="lst-h">
      <SectionHead title={<span id="lst-h">Listing in Find suppliers</span>} />
      <div className="lst">
        <label className="switch">
          <input type="checkbox" role="switch" checked={l.listed} onChange={(e) => setL({ ...l, listed: e.target.checked })} />
          <span className="strong">List my business in Find suppliers</span>
        </label>
        <p className="small muted">Buyers on Sauda in your delivery area see the card shown here: your name, city, the categories and area below, and your verification status. Never your GSTIN, contacts, street address or documents.</p>
        <div className="lst-grid">
          <div className="stack">
            <fieldset className="stack sm" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="small strong" style={{ marginBottom: 6 }}>Categories you supply</legend>
              <div className="pick-list">
                {LISTING_CATEGORIES.map((t) => <button key={t} type="button" className="chip-btn" aria-pressed={l.categories.includes(t)} onClick={() => setL({ ...l, categories: toggle(l.categories, t) })}>{t}</button>)}
              </div>
            </fieldset>
            <fieldset className="stack sm" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="small strong" style={{ marginBottom: 6 }}>Where you deliver (self-declared)</legend>
              <div className="radio-cards">
                {kinds.map((k) => (
                  <label key={k.v} className="radio-card">
                    <input type="radio" name="lst-kind" checked={sa.kind === k.v} onChange={() => setArea({ kind: k.v })} />
                    <span><b>{k.t}</b><span className="d">{k.d}</span></span>
                  </label>
                ))}
              </div>
              {sa.kind !== 'pan_india' && (
                areasErr ? <Callout tone="warn">The list of districts could not be loaded. Try again later.</Callout> : (
                  <div className="stack sm">
                    <label className="field">
                      <span>State</span>
                      <select className="input" value={stateSel} onChange={(e) => setStateSel(e.target.value)} disabled={!areas}>
                        <option value="">Choose a state</option>
                        {(areas?.states || []).map((s) => <option key={s.state} value={s.state}>{titleCase(s.state)}</option>)}
                      </select>
                    </label>
                    {sa.kind === 'state' && stateSel && (
                      <div><Button size="sm" variant="secondary" onClick={() => setArea({ states: toggle(sa.states, stateSel) })}>{sa.states.includes(stateSel) ? `Remove ${titleCase(stateSel)}` : `Add ${titleCase(stateSel)}`}</Button></div>
                    )}
                    {sa.kind === 'district' && districts.length > 0 && (
                      <div className="pick-list" role="group" aria-label={`Districts in ${titleCase(stateSel)}`}>
                        {districts.map((d) => (
                          <button key={d} type="button" className="chip-btn" aria-pressed={sa.districts.includes(d)}
                            onClick={() => {
                              const nd = toggle(sa.districts, d);
                              setArea({ districts: nd, states: nd.length ? [...new Set([...sa.states, stateSel])] : sa.states });
                            }}>{titleCase(d)}</button>
                        ))}
                      </div>
                    )}
                    <p className="xs muted">
                      {sa.kind === 'district' ? (sa.districts.length ? `Selected: ${sa.districts.map(titleCase).join(', ')}.` : 'No districts selected yet.')
                        : (sa.states.length ? `Selected: ${sa.states.map(titleCase).join(', ')}.` : 'No states selected yet.')}
                      {' '}Names come from the {areas?.source || 'India Post PIN directory'}.
                    </p>
                  </div>
                )
              )}
            </fieldset>
            <label className="field">
              <span>Minimum order (optional)</span>
              <div className="input-affix"><span>₹</span><input className="input" inputMode="numeric" value={minRupees} onChange={(e) => setMinRupees(e.target.value.replace(/[^\d]/g, ''))} placeholder="5000" /></div>
            </label>
            <label className="field">
              <span>Note for buyers (optional)</span>
              <textarea className="input" rows={2} value={l.notes || ''} aria-invalid={notesOver || undefined} aria-describedby="lst-count" onChange={(e) => setL({ ...l, notes: e.target.value })}
                placeholder="For example: next-day delivery within the city." />
              <span id="lst-count" className={`counter ${notesOver ? 'over' : ''}`}>{(l.notes || '').length}/200</span>
            </label>
            {msg && <Callout tone={msg.tone}>{msg.text}</Callout>}
            <div><Button onClick={save} busy={busy} busyLabel="Saving…" disabled={notesOver || (l.listed && !l.categories.length)}>Save listing</Button></div>
            {l.listed && !l.categories.length && <p className="xs muted">Pick at least one category to list your business.</p>}
          </div>
          <div className="lst-preview" aria-label="Preview of the card buyers see">
            <span className="k">What buyers will see{l.listed ? '' : ' (not listed now)'}</span>
            <SupplierCard c={preview} preview />
          </div>
        </div>
      </div>
    </section>
  );
}
