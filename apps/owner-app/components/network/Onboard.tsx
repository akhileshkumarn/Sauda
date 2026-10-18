'use client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '@/lib/api';
import {
  INDIAN_STATES, cinCheck, createBusiness, errorDetail, fssaiCheck, gstinCheck, looksLikeAadhaar, pinCheck, rememberBid, runVerification, shareLocation, udyamCheck,
} from '@/lib/network';
import type { TnRole } from '@/lib/types';
import { Button, Callout, Icon } from '../ui';
import { Field, NIcon } from './shared';

type Constitution = 'proprietorship' | 'partnership' | 'private_limited' | 'public_limited' | 'llp' | 'other';
const CONSTITUTIONS: { v: Constitution; label: string }[] = [
  { v: 'proprietorship', label: 'Sole proprietorship' },
  { v: 'partnership', label: 'Partnership firm' },
  { v: 'llp', label: 'Limited liability partnership (LLP)' },
  { v: 'private_limited', label: 'Private limited company' },
  { v: 'public_limited', label: 'Public limited company' },
  { v: 'other', label: 'Other (HUF, trust, society)' },
];
const BUYER_KINDS = [{ v: 'kirana', label: 'Kirana or general store' }, { v: 'supermarket', label: 'Supermarket' }, { v: 'medical', label: 'Medical store' }, { v: 'restaurant', label: 'Restaurant or caterer' }, { v: 'other_retail', label: 'Other shop' }];
const SELLER_KINDS = [{ v: 'distributor', label: 'Distributor' }, { v: 'wholesaler', label: 'Wholesaler' }, { v: 'manufacturer', label: 'Manufacturer or brand' }, { v: 'stockist', label: 'Stockist or C&F agent' }];
const PRODUCT_CHOICES = ['Staples', 'Rice', 'Pulses', 'Edible oil', 'Packaged food', 'Snacks', 'Beverages', 'Dairy', 'Personal care', 'Home care', 'Stationery'];
const FOOD = new Set(['Staples', 'Rice', 'Pulses', 'Edible oil', 'Packaged food', 'Snacks', 'Beverages', 'Dairy']);
const REP_ROLES = ['Proprietor', 'Partner', 'Director', 'Manager', 'Employee authorised to act'];

interface Draft {
  role: TnRole; display_name: string; legal_name: string; constitution: Constitution; kind: string; gst_registered: 'yes' | 'no' | '';
  gstin: string; udyam: string; fssai: string; cin_llpin: string; handles_food: boolean;
  line: string; city: string; state: string; pin: string;
  rep_name: string; rep_role: string; products: string[]; brands: string;
}
const empty = (role: TnRole): Draft => ({
  role, display_name: '', legal_name: '', constitution: 'proprietorship', kind: role === 'seller' ? 'distributor' : 'kirana', gst_registered: '',
  gstin: '', udyam: '', fssai: '', cin_llpin: '', handles_food: true, line: '', city: '', state: '', pin: '', rep_name: '', rep_role: 'Proprietor', products: [], brands: '',
});
const DRAFT_KEY = 'sauda-tn-onboard';
const STEPS = ['Business', 'Address', 'Representative', 'Products', 'Checks'];

export function Onboard() {
  const sp = useSearchParams();
  const router = useRouter();
  const role: TnRole = sp.get('role') === 'seller' ? 'seller' : 'buyer';
  const returnTo = sp.get('return') || '';
  const [d, setD] = useState<Draft>(() => empty(role));
  const [step, setStep] = useState(0);
  const [touched, setTouched] = useState(false);
  const [geo, setGeo] = useState<{ lat: number; lng: number; accuracy_m: number } | null>(null);
  const [geoConsent, setGeoConsent] = useState(false);
  const [geoState, setGeoState] = useState<'idle' | 'asking' | 'done' | 'denied' | 'unavailable'>('idle');
  const [consent, setConsent] = useState<Record<string, boolean>>({ registry: false, address: false, store: false });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [dups, setDups] = useState<{ bid?: string; display_name?: string; city?: string }[] | null>(null);
  const [gstTaken, setGstTaken] = useState(false);
  const head = useRef<HTMLHeadingElement>(null);

  // Resume an unfinished draft (this browser only; nothing personal is sent until the last step).
  useEffect(() => {
    try { const raw = sessionStorage.getItem(DRAFT_KEY); if (raw) { const x = JSON.parse(raw) as Draft; if (x.role === role) setD({ ...empty(role), ...x }); } } catch { /* ignore */ }
  }, [role]);
  useEffect(() => { try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch { /* ignore */ } }, [d]);
  useEffect(() => { head.current?.focus(); }, [step]);

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }));
  const isCompany = d.constitution === 'private_limited' || d.constitution === 'public_limited';
  const isLlp = d.constitution === 'llp';
  const food = d.handles_food || d.products.some((p) => FOOD.has(p));
  const gst = gstinCheck(d.gstin);
  const pin = pinCheck(d.pin);
  const pinMismatch = pin.state && d.state && pin.state !== d.state;
  const gstStateMismatch = gst.state && (d.state || pin.state) && gst.state !== (d.state || pin.state);
  const aadhaar = useMemo(() => [d.display_name, d.legal_name, d.line, d.rep_name, d.brands, d.udyam, d.cin_llpin].some(looksLikeAadhaar), [d]);

  const problems: string[] = [];
  if (step === 0) {
    if (!d.display_name.trim()) problems.push('Enter the business name');
    if (!d.gst_registered) problems.push('Say whether the business is GST registered');
    if (d.gst_registered === 'yes' && !gst.ok) problems.push('Enter a well-formed GSTIN');
    if ((isCompany || isLlp) && !cinCheck(d.cin_llpin, isLlp ? 'llp' : 'company').ok) problems.push(isLlp ? 'Enter the LLPIN' : 'Enter the CIN');
    if (food && d.fssai && !fssaiCheck(d.fssai).ok) problems.push('Check the FSSAI number');
    if (d.udyam && !udyamCheck(d.udyam).ok) problems.push('Check the Udyam number');
  }
  if (step === 1) {
    if (!d.line.trim()) problems.push('Enter the street address');
    if (!d.city.trim()) problems.push('Enter the city or town');
    if (!pin.ok) problems.push('Enter a 6-digit PIN code');
    if (!d.state) problems.push('Choose the state');
  }
  if (step === 2) {
    if (!d.rep_name.trim()) problems.push('Enter your name');
  }
  if (step === 3 && !d.products.length) problems.push('Choose at least one product category');
  if (aadhaar) problems.push('Remove the 12-digit number. Sauda never asks for Aadhaar.');

  function next() {
    setTouched(true);
    if (problems.length) return;
    setTouched(false); setStep((s) => Math.min(4, s + 1));
  }

  function locate() {
    if (!geoConsent) return;
    if (!('geolocation' in navigator)) { setGeoState('unavailable'); return; }
    setGeoState('asking');
    navigator.geolocation.getCurrentPosition(
      (p) => { setGeo({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy_m: p.coords.accuracy }); setGeoState('done'); },
      (e) => setGeoState(e.code === 1 ? 'denied' : 'unavailable'),
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 },
    );
  }

  async function submit(confirmNotDuplicate = false) {
    setErr(null); setDups(null); setGstTaken(false);
    const roles: TnRole[] = [d.role];
    const body = {
      roles, display_name: d.display_name.trim(), legal_name: d.legal_name.trim() || null, constitution: d.constitution, category: d.kind,
      products: d.products, gstin: d.gst_registered === 'yes' ? d.gstin.replace(/\s/g, '').toUpperCase() : null,
      udyam: d.udyam.trim().toUpperCase() || null, fssai: food ? d.fssai.replace(/\s/g, '') || null : null,
      cin_llpin: isCompany || isLlp ? d.cin_llpin.trim().toUpperCase() : null,
      address: { line: d.line.trim(), city: d.city.trim(), state: d.state, pin: d.pin.trim() },
      representative: { name: d.rep_name.trim(), role: d.rep_role, authority_status: 'self_declared' as const },
      brand_claims: d.role === 'seller' ? d.brands.split(',').map((x) => x.trim()).filter(Boolean) : [],
    };
    try {
      setBusy('Saving your business…');
      const b = await createBusiness({ ...body, ...(confirmNotDuplicate ? { confirm_not_duplicate: true } : {}) });
      rememberBid(b.bid);
      if (geo) { setBusy('Recording your location…'); try { await shareLocation(b.bid, geo); } catch { /* optional; can retry from the business page */ } }
      setBusy('Running checks…');
      await runVerification(b.bid, { gst: !!consent.registry, udyam: !!consent.registry, fssai: !!consent.registry, mca: !!consent.registry, address: !!consent.address, store: !!consent.store, location: !!geo });
      try { sessionStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ }
      router.push(returnTo || `/network/business/${encodeURIComponent(b.bid)}?new=1`);
    } catch (e) {
      const x = errorDetail(e);
      if (e instanceof ApiError && e.status === 409 && x.code === 'possible_duplicate') setDups(x.candidates || []);
      else if (e instanceof ApiError && e.status === 409 && x.code === 'gstin_already_registered') setGstTaken(true);
      else setErr(e);
      setBusy(null);
    }
  }

  const showProblems = touched && problems.length > 0;
  return (
    <div className="narrow">
      <div className="stack sm">
        <Link href="/network" className="small muted row sm tn-back" style={{ minHeight: 32 }}><Icon name="chev" size={14} /><span>Network</span></Link>
        <h1 ref={head} tabIndex={-1} style={{ outline: 'none' }}>{role === 'seller' ? 'Verify your supplier business' : 'Verify your business'}</h1>
        <p className="muted">Step {step + 1} of 5 · {STEPS[step]}. You can go back at any time; nothing is sent until the last step.</p>
      </div>
      <ol className="steps" aria-label="Progress">
        {STEPS.map((s, i) => <li key={s} className={i < step ? 'done' : i === step ? 'cur' : ''} aria-current={i === step ? 'step' : undefined}><span className="num">{i + 1}</span> <span className="lbl">{s}</span></li>)}
      </ol>

      <form className="stack lg" onSubmit={(e) => { e.preventDefault(); if (step < 4) next(); else submit(false); }} noValidate>
        {step === 0 && (
          <>
            <fieldset className="tn-group">
              <legend>You are</legend>
              <div className="radio-cards two">
                <label className="radio-card"><input type="radio" name="role" checked={d.role === 'buyer'} onChange={() => router.replace('/network/onboard?role=buyer')} /><span><b>A shop that buys stock</b><span className="d">Kirana, supermarket, restaurant</span></span></label>
                <label className="radio-card"><input type="radio" name="role" checked={d.role === 'seller'} onChange={() => router.replace('/network/onboard?role=seller')} /><span><b>A supplier</b><span className="d">Distributor, wholesaler, manufacturer</span></span></label>
              </div>
            </fieldset>
            <fieldset className="tn-group">
              <legend>About the business</legend>
              <Field label="Business name" hint="as on your name board"><input className="input" value={d.display_name} onChange={(e) => set('display_name', e.target.value)} autoComplete="organization" aria-invalid={touched && !d.display_name.trim()} /></Field>
              <Field label="Legal name" hint="if different, as on GST or company records"><input className="input" value={d.legal_name} onChange={(e) => set('legal_name', e.target.value)} /></Field>
              <Field label="Kind of business">
                <select className="input" value={d.kind} onChange={(e) => set('kind', e.target.value)}>{(d.role === 'seller' ? SELLER_KINDS : BUYER_KINDS).map((k) => <option key={k.v} value={k.v}>{k.label}</option>)}</select>
              </Field>
              <Field label="Business type">
                <select className="input" value={d.constitution} onChange={(e) => set('constitution', e.target.value as Constitution)}>{CONSTITUTIONS.map((c) => <option key={c.v} value={c.v}>{c.label}</option>)}</select>
              </Field>
              <label className="check-row"><input type="checkbox" checked={d.handles_food} onChange={(e) => set('handles_food', e.target.checked)} /><span>We sell or handle food (packaged or loose)</span></label>
              <div className="field">
                <span>Is the business registered for GST?</span>
                <div className="chipset" role="radiogroup" aria-label="GST registered">
                  {(['yes', 'no'] as const).map((v) => <button key={v} type="button" className="chip-btn" role="radio" aria-checked={d.gst_registered === v} aria-pressed={d.gst_registered === v} onClick={() => set('gst_registered', v)}>{v === 'yes' ? 'Yes' : 'No, not registered'}</button>)}
                </div>
                {d.gst_registered === 'no' && <span className="hint">That is fine. Many small businesses are below the GST threshold.</span>}
              </div>
            </fieldset>

            <fieldset className="tn-group">
              <legend>Required for this business type</legend>
              {d.gst_registered === 'yes' && (
                <Field label="GSTIN" msg={d.gstin ? (gstStateMismatch ? { ok: false, message: `${gst.message} Your address says ${d.state || pin.state}.` } : gst) : null}>
                  <input className="input num" value={d.gstin} onChange={(e) => set('gstin', e.target.value.toUpperCase())} maxLength={15} inputMode="text" autoCapitalize="characters" spellCheck={false} placeholder="36ABCDE1234F1Z5" aria-invalid={touched && !gst.ok} />
                </Field>
              )}
              {(isCompany || isLlp) && (
                <Field label={isLlp ? 'LLPIN' : 'CIN (company identification number)'} msg={d.cin_llpin ? cinCheck(d.cin_llpin, isLlp ? 'llp' : 'company') : null}>
                  <input className="input num" value={d.cin_llpin} onChange={(e) => set('cin_llpin', e.target.value.toUpperCase())} spellCheck={false} placeholder={isLlp ? 'AAB-1234' : 'U15400TG2015PTC099999'} />
                </Field>
              )}
              {food && (
                <Field label="FSSAI licence or registration number" hint="needed to sell food" msg={d.fssai ? fssaiCheck(d.fssai) : null}>
                  <input className="input num" value={d.fssai} onChange={(e) => set('fssai', e.target.value.replace(/[^\d]/g, ''))} inputMode="numeric" maxLength={14} placeholder="14 digits" />
                </Field>
              )}
              {d.gst_registered !== 'yes' && !(isCompany || isLlp) && !food && <p className="small muted">Nothing else is required for this business type.</p>}
              {d.gst_registered === '' && <p className="small muted">Answer the GST question above to see what is required.</p>}
            </fieldset>

            <fieldset className="tn-group optional tn-opt">
              <legend>Optional: helps {d.role === 'seller' ? 'buyers' : 'suppliers'} trust you</legend>
              <Field label="Udyam registration number" msg={d.udyam ? udyamCheck(d.udyam) : null}>
                <input className="input num" value={d.udyam} onChange={(e) => set('udyam', e.target.value.toUpperCase())} spellCheck={false} placeholder="UDYAM-TS-02-0012345" />
              </Field>
              {d.role === 'seller' && (
                <Field label="Brands you are authorised to distribute" hint="comma separated; a reviewer checks your letter later">
                  <input className="input" value={d.brands} onChange={(e) => set('brands', e.target.value)} placeholder="Fortune, Aashirvaad" />
                </Field>
              )}
              {!food && <p className="small muted">FSSAI is only asked for food businesses.</p>}
            </fieldset>
          </>
        )}

        {step === 1 && (
          <>
            <fieldset className="tn-group">
              <legend>Where the business operates</legend>
              <Field label="Shop or warehouse address" hint="building, street, area"><input className="input" value={d.line} onChange={(e) => set('line', e.target.value)} autoComplete="street-address" /></Field>
              <div className="grid2 stack-narrow">
                <Field label="City or town"><input className="input" value={d.city} onChange={(e) => set('city', e.target.value)} autoComplete="address-level2" /></Field>
                <Field label="PIN code" msg={d.pin ? (pinMismatch ? { ok: false, message: `${pin.message} You chose ${d.state}.` } : pin) : null}>
                  <input className="input num" value={d.pin} onChange={(e) => { const v = e.target.value.replace(/\D/g, '').slice(0, 6); set('pin', v); const p = pinCheck(v); if (p.state && !d.state) set('state', p.state); }} inputMode="numeric" autoComplete="postal-code" maxLength={6} />
                </Field>
              </div>
              <Field label="State">
                <select className="input" value={d.state} onChange={(e) => set('state', e.target.value)}><option value="">Choose…</option>{INDIAN_STATES.map((s) => <option key={s}>{s}</option>)}</select>
              </Field>
            </fieldset>
            <fieldset className="tn-group optional tn-opt">
              <legend>Optional: confirm you are at the shop</legend>
              <p className="small muted">If you are at the shop now, your phone can share its location once. Sauda compares it with the address above and stores only that one reading, with a timestamp. It is not tracked again. You can skip this and do it later.</p>
              <label className="check-row"><input type="checkbox" checked={geoConsent} onChange={(e) => setGeoConsent(e.target.checked)} /><span>I agree to share this device’s location once for this check.</span></label>
              <div className="row sm wrap">
                <Button type="button" variant="secondary" size="sm" disabled={!geoConsent || geoState === 'asking'} busy={geoState === 'asking'} busyLabel="Asking your phone…" onClick={locate}><NIcon name="pin" size={14} />Use my current location</Button>
                {geoState === 'done' && geo && <span className="small" style={{ color: 'var(--ok)' }}>✓ Location captured (accuracy about {Math.round(geo.accuracy_m)} m). It is sent in the last step.</span>}
              </div>
              {geoState === 'denied' && <Callout tone="warn">Location permission was refused. That is fine; you can continue without it.</Callout>}
              {geoState === 'unavailable' && <Callout tone="warn">This device could not share a location right now. You can continue and try later from your business page.</Callout>}
            </fieldset>
          </>
        )}

        {step === 2 && (
          <fieldset className="tn-group">
            <legend>Who is acting for the business</legend>
            <p className="small muted">The person setting this up. Later, a reviewer may ask for a letter or document showing you can act for the business.</p>
            <Field label="Your name"><input className="input" value={d.rep_name} onChange={(e) => set('rep_name', e.target.value)} autoComplete="name" /></Field>
            <Field label="Your role">
              <select className="input" value={d.rep_role} onChange={(e) => set('rep_role', e.target.value)}>{REP_ROLES.map((r) => <option key={r}>{r}</option>)}</select>
            </Field>
            <Callout tone="neutral" icon="lock">Sauda never asks for Aadhaar, OTPs, passwords or bank logins. Do not type them anywhere here.</Callout>
          </fieldset>
        )}

        {step === 3 && (
          <fieldset className="tn-group">
            <legend>{d.role === 'seller' ? 'What you supply' : 'What you buy'}</legend>
            <div className="chips">
              {PRODUCT_CHOICES.map((p) => {
                const on = d.products.includes(p);
                return <button key={p} type="button" className="chip-btn" aria-pressed={on} onClick={() => set('products', on ? d.products.filter((x) => x !== p) : [...d.products, p])}>{on ? '✓ ' : ''}{p}</button>;
              })}
            </div>
            <p className="small muted">{d.role === 'seller' ? 'Buyers see these categories on your profile.' : 'Suppliers see these categories when they review your profile.'}</p>
          </fieldset>
        )}

        {step === 4 && (
          <>
            <fieldset className="tn-group">
              <legend>Checks Sauda will run</legend>
              <p className="small muted">Tick what you agree to. Each check says where its result came from. A check that cannot run is marked pending, never guessed.</p>
              {(d.gstin || d.udyam || d.fssai || d.cin_llpin) ? (
                <label className="check-row"><input type="checkbox" checked={consent.registry} onChange={(e) => setConsent((c) => ({ ...c, registry: e.target.checked }))} /><span>Compare the registration numbers I gave ({[d.gst_registered === 'yes' && d.gstin && 'GSTIN', d.udyam && 'Udyam', food && d.fssai && 'FSSAI', d.cin_llpin && (isLlp ? 'LLPIN' : 'CIN')].filter(Boolean).join(', ')}) with official or authorised records, where Sauda has access. Where it does not, a person checks the public portal by hand.</span></label>
              ) : <p className="small muted">No registration numbers given, so there is nothing to look up. Your record will show “Self-declared”.</p>}
              <label className="check-row"><input type="checkbox" checked={consent.address} onChange={(e) => setConsent((c) => ({ ...c, address: e.target.checked }))} /><span>Check that the address and PIN code exist and match each other.</span></label>
              <label className="check-row"><input type="checkbox" checked={consent.store} onChange={(e) => setConsent((c) => ({ ...c, store: e.target.checked }))} /><span>Keep the results and any documents I upload privately, and share only a summary with businesses I invite or accept.</span></label>
              {geo && <p className="small muted">Your one-time location reading will also be sent.</p>}
            </fieldset>
            <div className="surface stack sm">
              <p className="strong">{d.display_name || 'Your business'}</p>
              <p className="small muted">{[d.line, d.city, d.state, d.pin].filter(Boolean).join(', ')}</p>
              <p className="small muted">{d.rep_name} · {d.rep_role} · {d.products.join(', ')}</p>
            </div>
            {dups && (
              <div className="callout warn" role="alert"><Icon name="alert" size={16} /><div>
                <b>This looks like an existing business.</b>
                <p className="small" style={{ marginTop: 4 }}>A business with the same name and PIN{dups.length ? `: ${dups.map((c) => [c.display_name, c.city].filter(Boolean).join(', ')).join('; ')}` : ''} is already on Sauda. If it is yours, ask its owner to add you. If it is a different business, continue.</p>
                <div style={{ marginTop: 8 }}><Button type="button" size="sm" variant="secondary" busy={!!busy} busyLabel="Saving…" onClick={() => submit(true)}>It is a different business, continue</Button></div>
              </div></div>
            )}
            {gstTaken && <Callout tone="warn" title="This GSTIN is already registered on Sauda.">Ask the owner of that business to add you as a member. If you think this is a mistake, a Sauda reviewer can help.</Callout>}
            {!!err && <Callout tone="bad" title="That did not finish.">{err instanceof Error ? err.message : String(err)} Your answers are kept; try again.</Callout>}
          </>
        )}

        {showProblems && (
          <div className="callout bad" role="alert"><Icon name="alert" size={16} /><div><b>Before you continue:</b><ul className="plain-list" style={{ color: 'inherit', marginTop: 4 }}>{problems.map((p) => <li key={p}>{p}</li>)}</ul></div></div>
        )}
        {!touched && aadhaar && <Callout tone="bad">That looks like an Aadhaar number. Sauda never asks for Aadhaar; please remove it.</Callout>}

        <div className="tn-actions">
          {step > 0 ? <Button type="button" variant="secondary" onClick={() => { setTouched(false); setStep((s) => s - 1); }} disabled={!!busy}>Back</Button> : <span />}
          {step < 4
            ? <Button type="submit">Continue</Button>
            : <Button type="submit" busy={!!busy} busyLabel={busy || 'Working…'} disabled={!consent.store}>Save and run checks</Button>}
        </div>
        {step === 4 && !consent.store && <p className="xs muted right">Tick the last box to continue. The other checks are optional.</p>}
      </form>
    </div>
  );
}
