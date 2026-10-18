'use client';
import './network.css';
import './discover.css';
import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api';
import { relTime, rupees } from '@/lib/format';
import {
  CONNECTION_WORD, LISTING_CATEGORIES, SORT_NOTE, absoluteUrl, categoryWord, dimWord, errorDetail, myBusinesses, pickBusiness, statusWord, titleCase, tnAreas, tnConnect, tnDiscover,
} from '@/lib/network';
import type { TnAreas } from '@/lib/types';
import { ProfileChooser, SampleShopLink, WhatsAppShare } from './SampleShop';
import type { TnBusinessMine, TnDiscoverCard, TnDiscoverResponse, TnDiscoverScope } from '@/lib/types';
import { Button, ButtonLink, Callout, EmptyState, ErrorState, Icon, Skeleton, StatusPill } from '../ui';
import { SegmentedControl, Sheet } from '../ui-client';
import { NIcon, SourceBadge } from './shared';

const PAGE = 20;

function SearchIcon() {
  return <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" aria-hidden focusable="false"><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></svg>;
}

// ---------------------------------------------------------------- supplier card (also used as the listing preview)
export function SupplierCard({ c, onConnect, preview }: { c: TnDiscoverCard; onConnect?: (c: TnDiscoverCard) => void; preview?: boolean }) {
  const w = categoryWord(c.trust?.category);
  const sources = [...new Set((c.trust?.dims || []).map((d) => d.source_kind).filter(Boolean) as string[])];
  const where = [c.city || titleCase(c.district), titleCase(c.state)].filter(Boolean).join(', ');
  const area = c.service_area?.label || '';
  const conn = c.connection || 'none';
  return (
    <article className={`scard ${c.is_fixture ? 'fx' : ''}`} aria-label={c.display_name}>
      <div className="scard-top">
        <div className="stack xs grow" style={{ minWidth: 0 }}>
          <h3>{c.display_name}</h3>
          <div className="facts">
            {where && <span>{where}</span>}
            {area && <span>{area.replace(/\s*\(self-declared\)\s*$/i, '')} <em className="sd">(self-declared)</em></span>}
          </div>
        </div>
        {!preview && onConnect && (
          conn === 'none'
            ? <Button size="sm" onClick={() => onConnect(c)} aria-label={`Request to connect with ${c.display_name}`}>Request to connect</Button>
            : conn === 'connected' && c.rid
              ? <ButtonLink size="sm" variant="secondary" href={`/network/relationships/${encodeURIComponent(c.rid)}`}><Icon name="check" size={14} />Connected</ButtonLink>
              : <Button size="sm" variant="secondary" disabled aria-label={`${CONNECTION_WORD[conn]}: ${c.display_name}`}>{conn === 'requested' ? <Icon name="clock" size={14} /> : <Icon name="x" size={14} />}{CONNECTION_WORD[conn]}</Button>
        )}
      </div>
      {c.categories?.length > 0 && <div className="tags" aria-label="Categories">{c.categories.map((t) => <span key={t} className="tag">{t}</span>)}</div>}
      <div className="row sm wrap" style={{ rowGap: 4 }}>
        <StatusPill tone={w.tone}>{c.trust?.category_text || w.label}</StatusPill>
        {c.is_fixture && <SourceBadge kind="simulated_fixture" />}
      </div>
      {c.trust?.dims?.length > 0 && (
        <ul className="mini-dims" aria-label="Checks">
          {c.trust.dims.filter((d) => d.status !== 'not_applicable').map((d) => {
            const s = statusWord(String(d.status));
            return <li key={String(d.dim)} title={`${d.label || dimWord(String(d.dim)).label}: ${s.label}`}><span className={`dot ${s.tone}`} aria-hidden />{d.label || dimWord(String(d.dim)).label}<span className="sr-only">: {s.label}</span></li>;
          })}
        </ul>
      )}
      <div className="scard-foot">
        {sources.filter((k) => !(c.is_fixture && k === 'simulated_fixture')).map((k) => <SourceBadge key={k} kind={k} />)}
        {c.min_order_paise ? <span>Min order {rupees(c.min_order_paise, true)}</span> : null}
        <span>{c.last_checked_at ? `Checked ${relTime(c.last_checked_at)}` : 'Not checked yet'}</span>
      </div>
      {c.notes && <p className="small muted break">{c.notes}</p>}
    </article>
  );
}

// ---------------------------------------------------------------- request sheet
function ConnectSheet({ card, fromBid, onClose, onSent, onNeedProfile }: { card: TnDiscoverCard | null; fromBid: string; onClose: () => void; onSent: (c: TnDiscoverCard, note: string) => void; onNeedProfile: () => void }) {
  const [cats, setCats] = useState<string[]>([]);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setCats(card?.categories?.slice(0, 1) || []); setMsg(''); setErr(null); }, [card?.bid]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!card) return null;
  const over = msg.length > 300;
  async function send() {
    if (!card) return;
    setBusy(true); setErr(null);
    try {
      const r = await tnConnect({ from_bid: fromBid, to_bid: card.bid, categories: cats, ...(msg.trim() ? { message: msg.trim() } : {}) });
      onSent({ ...card, connection: r.relationship?.state === 'declined' ? 'declined' : 'requested', rid: r.relationship?.rid || card.rid },
        r.duplicate ? 'You had already sent a request to this supplier.' : r.guard?.blocked ? 'Request sent. Your message was held back by the safety check, so the supplier sees only your categories.' : 'Request sent. The supplier will see your redacted profile and decide.');
    } catch (e) {
      const d = errorDetail(e);
      if (d.code === 'buyer_profile_required') { onNeedProfile(); return; }
      setErr(d.code === 'rate_limited' ? 'You have sent the maximum number of requests for today. Try again tomorrow.'
        : d.code === 'buyer_profile_required' ? 'Verify your buyer business first.'
          : e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }
  return (
    <Sheet open onClose={onClose} title={`Request to connect`}>
      <p className="small muted">With <b style={{ color: 'var(--ink)' }}>{card.display_name}</b>{card.city ? `, ${card.city}` : ''}</p>
      <fieldset className="stack sm" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="small strong" style={{ marginBottom: 6 }}>What do you want to buy?</legend>
        <div className="pick-list">
          {(card.categories.length ? card.categories : LISTING_CATEGORIES).map((t) => (
            <button key={t} type="button" className="chip-btn" aria-pressed={cats.includes(t)} onClick={() => setCats((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]))}>{t}</button>
          ))}
        </div>
      </fieldset>
      <label className="field">
        <span>Message (optional)</span>
        <textarea className="input" rows={3} value={msg} maxLength={400} aria-invalid={over || undefined} aria-describedby="cs-count"
          placeholder="For example: we buy about 20 bags a month and pay on delivery." onChange={(e) => setMsg(e.target.value)} />
        <span id="cs-count" className={`counter ${over ? 'over' : ''}`}>{msg.length}/300</span>
      </label>
      <p className="share-note"><b>What gets shared:</b> your redacted trust profile, that is your business name, city and state, verification category and the status of each check. Never your GSTIN, phone, email, street address or documents.</p>
      {err && <Callout tone="bad">{err}</Callout>}
      <div className="tn-actions">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={send} busy={busy} busyLabel="Sending…" disabled={!cats.length || over}><Icon name="send" size={16} />Send request</Button>
      </div>
    </Sheet>
  );
}

// ---------------------------------------------------------------- page
export function Discover() {
  const [biz, setBiz] = useState<TnBusinessMine | null | undefined>(undefined);
  const [bizErr, setBizErr] = useState<unknown>(null);
  const [q, setQ] = useState('');
  const [qd, setQd] = useState('');
  const [category, setCategory] = useState('');
  const [scope, setScope] = useState<TnDiscoverScope>('district');
  const [verifiedOnly, setVerifiedOnly] = useState(true);
  const [data, setData] = useState<TnDiscoverResponse | null>(null);
  const [rows, setRows] = useState<TnDiscoverCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [needsBuyer, setNeedsBuyer] = useState(false);
  const [sheet, setSheet] = useState<TnDiscoverCard | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [sent, setSent] = useState<TnDiscoverCard | null>(null);
  const [chooser, setChooser] = useState<TnDiscoverCard | null>(null);
  const [areas, setAreas] = useState<TnAreas | null>(null);
  const [pickState, setPickState] = useState('');
  const [pickDistrict, setPickDistrict] = useState('');
  const seq = useRef(0);

  const loadBiz = useCallback((prefer?: string) => {
    setBizErr(null);
    return myBusinesses().then((mine) => {
      const buyers = mine.filter((b) => b.roles.includes('buyer'));
      const b = (prefer && buyers.find((x) => x.bid === prefer)) || pickBusiness(buyers);
      setBiz(b);
      setNeedsBuyer(!b);
      if (!b) setScope((x) => (x === 'district' ? 'india' : x));
      return b;
    }).catch((e) => { setBizErr(e); setLoading(false); return null; });
  }, []);
  useEffect(() => { loadBiz(); }, [loadBiz]);
  useEffect(() => { const t = setTimeout(() => setQd(q.trim()), 300); return () => clearTimeout(t); }, [q]);

  const load = useCallback(async (cursor?: string | null) => {
    if (biz === undefined) return;
    const my = ++seq.current;
    if (cursor) setMore(true); else { setLoading(true); setError(null); }
    const area = !biz && pickDistrict ? { scope: 'district' as const, district: pickDistrict, state: pickState }
      : !biz && pickState && scope !== 'india' ? { scope: 'state' as const, state: pickState } : { scope };
    try {
      const r = await tnDiscover({ ...(biz ? { bid: biz.bid } : {}), q: qd || undefined, category: category || undefined, ...area, verified_only: verifiedOnly, limit: PAGE, cursor: cursor || undefined });
      if (my !== seq.current) return;
      setData(r); setRows((x) => (cursor ? [...x, ...r.results] : r.results)); setNeedsBuyer(!!r.viewer_needs_profile);
    } catch (e) {
      if (my !== seq.current) return;
      if (e instanceof ApiError && (errorDetail(e).code === 'buyer_profile_required')) setNeedsBuyer(true);
      else setError(e);
    } finally { if (my === seq.current) { setLoading(false); setMore(false); } }
  }, [biz, qd, category, scope, verifiedOnly, pickState, pickDistrict]);
  useEffect(() => { if (biz !== undefined) load(); }, [biz, load]);
  useEffect(() => { if (needsBuyer && !areas) tnAreas().then(setAreas).catch(() => {}); }, [needsBuyer, areas]);
  const districts = areas?.states.find((x) => x.state === pickState)?.districts || [];
  function connect(c: TnDiscoverCard) {
    setNote(null); setSent(null);
    if (!biz) setChooser(c); else setSheet(c);
  }

  const district = titleCase(data?.viewer?.district || data?.area?.district) || 'your district';
  const state = titleCase(data?.viewer?.state || data?.area?.state) || 'Your state';
  const areaName = scope === 'district' ? district : scope === 'state' ? state : 'India';

  return (
    <div className="narrow">
      <Link href="/network" className="small muted row sm tn-back" style={{ minHeight: 32 }}><Icon name="chev" size={14} /><span>Network</span></Link>
      <div className="page-head">
        <h1>Find verified suppliers</h1>
        <p>Suppliers who listed themselves on Sauda and deliver to your area. Each card shows what was checked and where the result came from.</p>
      </div>

      {bizErr ? (
        <ErrorState error={bizErr} onRetry={() => loadBiz()} title="Could not load your business" />
      ) : (
        <>
          {needsBuyer && (
            <Callout tone="info" title="Browsing without a business profile">
              You can look at every listed supplier. To request a connection, create your business profile or try a sample shop; Request to connect walks you through it.
            </Callout>
          )}
          {biz?.sandbox && <Callout tone="neutral" icon="flask">You are browsing as your sample shop, <b>{biz.display_name}</b>. Requests you send from it are demo requests to demo suppliers.</Callout>}
          <div className="dsc-controls" role="search" aria-label="Find suppliers">
            <label className="dsc-search">
              <span className="sr-only">Search suppliers</span>
              <SearchIcon />
              <input className="input" type="search" value={q} placeholder="Search by name or product" onChange={(e) => setQ(e.target.value)} autoComplete="off" />
            </label>
            <div className="dsc-chips" role="group" aria-label="Category">
              <button type="button" className="chip-btn" aria-pressed={!category} onClick={() => setCategory('')}>All</button>
              {LISTING_CATEGORIES.map((t) => <button key={t} type="button" className="chip-btn" aria-pressed={category === t} onClick={() => setCategory(category === t ? '' : t)}>{t}</button>)}
            </div>
            <div className="dsc-row">
              {needsBuyer ? (
                <div className="row sm wrap">
                  <label className="field" style={{ margin: 0 }}><span className="sr-only">State</span>
                    <select className="input" value={pickState} onChange={(e) => { setPickState(e.target.value); setPickDistrict(''); setScope(e.target.value ? 'state' : 'india'); }} aria-label="State">
                      <option value="">All India</option>
                      {(areas?.states || []).map((x) => <option key={x.state} value={x.state}>{titleCase(x.state)}</option>)}
                    </select>
                  </label>
                  {pickState && <label className="field" style={{ margin: 0 }}><span className="sr-only">District</span>
                    <select className="input" value={pickDistrict} onChange={(e) => setPickDistrict(e.target.value)} aria-label="District">
                      <option value="">Whole state</option>
                      {districts.map((x) => <option key={x} value={x}>{titleCase(x)}</option>)}
                    </select>
                  </label>}
                </div>
              ) : (
                <SegmentedControl label="Delivery area" value={scope} onChange={setScope}
                  options={[{ value: 'district', label: `Near me · ${district}` }, { value: 'state', label: state }, { value: 'india', label: 'All India' }]} />
              )}
              <label className="switch">
                <input type="checkbox" role="switch" checked={verifiedOnly} aria-checked={verifiedOnly} onChange={(e) => setVerifiedOnly(e.target.checked)} />
                <span>Verified only</span>
              </label>
            </div>
            <p className="dsc-note"><Icon name="info" size={14} />{data?.sort_note || SORT_NOTE}.</p>
          </div>

          {note && <Callout tone="ok">{note}
            {sent?.rid && biz && <span className="row sm wrap" style={{ marginTop: 8 }}>
              <span className="small">Know someone at {sent.display_name}? Tell them on WhatsApp.</span>
              <WhatsAppShare business={biz.display_name} link={absoluteUrl(`/network/relationships/${encodeURIComponent(sent.rid)}`)} />
            </span>}
          </Callout>}

          {loading && !rows.length ? (
            <div className="dsc-list" aria-busy="true" aria-label="Loading suppliers">
              {[0, 1, 2].map((i) => <div key={i} className="scard"><Skeleton lines={3} /></div>)}
            </div>
          ) : error ? (
            <ErrorState error={error} onRetry={() => load()} title="Could not load suppliers" />
          ) : rows.length === 0 ? (
            <EmptyState icon="box" title={scope === 'india' ? 'No verified suppliers listed yet' : `No verified suppliers deliver to ${areaName} yet`}
              action={<div className="row sm wrap" style={{ justifyContent: 'center' }}>
                {scope === 'district' && <Button size="sm" variant="secondary" onClick={() => setScope('state')}>Try {state}</Button>}
                {scope !== 'india' && <Button size="sm" variant="secondary" onClick={() => setScope('india')}>Try All India</Button>}
                <ButtonLink size="sm" href={`/network/invite?role=seller${biz ? `&bid=${encodeURIComponent(biz.bid)}` : ''}`}>Invite a supplier</ButtonLink>
              </div>}>
              {scope === 'india'
                ? 'Invite a supplier you already buy from; once they verify and list themselves, they appear here.'
                : scope === 'state' ? 'Try All India, or invite a supplier you already buy from.' : 'Try your state or All India, or invite a supplier you already buy from.'}
              {verifiedOnly ? ' You can also turn off "Verified only".' : ''}
            </EmptyState>
          ) : (
            <section aria-label={`Suppliers delivering to ${areaName}`} className="stack sm">
              <p className="small muted" aria-live="polite">{rows.length}{data?.total && data.total > rows.length ? ` of ${data.total}` : ''} supplier{rows.length === 1 ? '' : 's'}{verifiedOnly ? ', verified only' : ''}</p>
              <ul className="dsc-list">
                {rows.map((c) => <li key={c.bid}><SupplierCard c={c} onConnect={connect} /></li>)}
              </ul>
              {data?.next_cursor && <div><Button variant="secondary" size="sm" busy={more} busyLabel="Loading…" onClick={() => load(data.next_cursor)}>Show more</Button></div>}
              {rows.some((c) => c.is_fixture) && (
                <p className="xs muted row sm" style={{ alignItems: 'flex-start' }}><NIcon name="flask" size={14} /><span>Cards marked Simulated (demo data) are sample businesses with made-up records. They are not real companies.</span></p>
              )}
            </section>
          )}
        </>
      )}
      {!biz?.sandbox && !bizErr && <SampleShopLink onReady={async (bid) => { await loadBiz(bid); }} />}
      {biz && <ConnectSheet card={sheet} fromBid={biz.bid} onClose={() => setSheet(null)} onNeedProfile={() => { setChooser(sheet); setSheet(null); }}
        onSent={(c, t) => { setRows((x) => x.map((y) => (y.bid === c.bid ? c : y))); setSheet(null); setNote(t); setSent(c); }} />}
      <ProfileChooser open={!!chooser} onClose={() => setChooser(null)}
        onSample={async (bid) => { const c = chooser; const b = await loadBiz(bid); setChooser(null); if (b && c) setSheet(c); }} />
    </div>
  );
}
