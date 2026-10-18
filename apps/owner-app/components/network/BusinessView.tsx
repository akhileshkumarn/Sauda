'use client';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { ApiError } from '@/lib/api';
import { ist } from '@/lib/format';
import { DOC_WORD, evidenceUrl, getBusiness, getLedger, listEvidence, outstandingWord, runVerification, shareLocation, uploadEvidence, requestManualReview } from '@/lib/network';
import { useAsync } from '@/lib/useAsync';
import type { TnBusinessFull, TnEvidence, TnEvidenceType, TnSummary } from '@/lib/types';
import { Button, ButtonLink, Callout, ErrorState, Icon, SectionHead, Skeleton } from '../ui';
import { Sheet } from '../ui-client';
import { CategoryHero, DimensionList, Limitations, NIcon, SimulatedNote, hasSimulated } from './shared';

const MAX_MB = 8;

export function BusinessView({ bid }: { bid: string }) {
  const sp = useSearchParams();
  const fresh = sp.get('new') === '1';
  const q = useAsync(() => getBusiness(bid), [bid]);
  if (q.loading && !q.data) return <div className="narrow"><Skeleton lines={8} /></div>;
  if (q.error && !q.data) return <div className="narrow"><Back /><ErrorState error={q.error} onRetry={q.reload} title="Could not load this business" /></div>;
  if (!q.data) return null;
  return <Body data={q.data} fresh={fresh} reload={q.reload} />;
}

function Back() {
  return <Link href="/network" className="small muted row sm tn-back" style={{ minHeight: 32 }}><Icon name="chev" size={14} /><span>Network</span></Link>;
}

function fallbackSummary(d: TnBusinessFull): TnSummary {
  return { category: 'additional_review_required', dimensions: [], outstanding: [], limitations: [], next_step: 'Run the checks to see where your business stands.' };
}

function Body({ data, fresh, reload }: { data: TnBusinessFull; fresh: boolean; reload: () => void }) {
  const b = data.business;
  const s = data.summary || fallbackSummary(data);
  const sim = b.is_fixture || hasSimulated(data.checks) || hasSimulated(s.dimensions);
  const [upload, setUpload] = useState<TnEvidenceType | null>(null);
  const [note, setNote] = useState<{ tone: 'ok' | 'bad' | 'warn'; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function locate() {
    if (!('geolocation' in navigator)) { setNote({ tone: 'warn', text: 'This device cannot share a location.' }); return; }
    setBusy('location'); setNote(null);
    navigator.geolocation.getCurrentPosition(async (p) => {
      try { await shareLocation(b.bid, { lat: p.coords.latitude, lng: p.coords.longitude, accuracy_m: p.coords.accuracy }); setNote({ tone: 'ok', text: 'Location recorded once and compared with your address.' }); reload(); }
      catch (e) { setNote({ tone: 'bad', text: e instanceof Error ? e.message : String(e) }); }
      finally { setBusy(null); }
    }, (e) => { setBusy(null); setNote({ tone: 'warn', text: e.code === 1 ? 'Location permission was refused. You can allow it in your browser settings and try again.' : 'Could not get a location right now. Try again from the shop.' }); }, { enableHighAccuracy: true, timeout: 12000 });
  }
  async function askReview() {
    setBusy('review'); setNote(null);
    try { await requestManualReview(b.bid); setNote({ tone: 'ok', text: 'Asked for a manual review. A Sauda reviewer will look at your record; you will see their decision here.' }); reload(); }
    catch (e) { setNote({ tone: 'bad', text: e instanceof ApiError ? e.message : String(e) }); }
    finally { setBusy(null); }
  }
  async function rerun() {
    setBusy('rerun'); setNote(null);
    try { await runVerification(b.bid, { gst: true, address: true }); reload(); }
    catch (e) { setNote({ tone: 'bad', text: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(null); }
  }

  const outstanding = s.outstanding || [];
  const docs: TnEvidenceType[] = ['gst_certificate', 'udyam_certificate', 'fssai_licence', 'authorisation_letter', 'storefront_photo', ...(b.roles.includes('seller') ? ['brand_authorisation' as const] : [])];
  return (
    <div className="narrow">
      <Back />
      {fresh && <Callout tone="ok" title="Saved.">Your checks have run. Here is where things stand.</Callout>}
      <CategoryHero summary={s} roles={b.roles} title={<>{b.display_name}{b.address?.city ? ` · ${b.address.city}` : ''}</>} />
      <SimulatedNote show={sim} />

      <section aria-labelledby="out-h" className={`stack sm ${outstanding.length ? 'tn-todo' : ''}`}>
        <SectionHead title={<span id="out-h">{outstanding.length ? `What you can do next · ${outstanding.length}` : 'Outstanding checks'}</span>} />
        {outstanding.length > 0 && <p className="small muted">Each one adds evidence to your record. Businesses you trade with may ask for some of them before they approve you.</p>}
        {outstanding.length === 0 && <p className="small muted">Nothing outstanding. You can still add documents below if a business asks for them.</p>}
        <ul className="req-list">
          {outstanding.map((code) => {
            const w = outstandingWord(code);
            return (
              <li key={code} style={{ alignItems: 'center', flexWrap: 'wrap' }}>
                <span className="dot warn" aria-hidden />
                <span className="grow">{w.label}</span>
                {w.action === 'upload' && w.doc && <Button size="sm" variant="secondary" onClick={() => setUpload(w.doc!)}><NIcon name="upload" size={14} />Upload</Button>}
                {w.action === 'location' && <Button size="sm" variant="secondary" busy={busy === 'location'} busyLabel="Asking…" onClick={locate}><NIcon name="pin" size={14} />Share location</Button>}
                {w.action === 'review' && <Button size="sm" variant="secondary" busy={busy === 'review'} busyLabel="Asking…" onClick={askReview}>Request manual review</Button>}
              </li>
            );
          })}
        </ul>
        {note && <Callout tone={note.tone}>{note.text}</Callout>}
        <details className="evidence">
          <summary><span className="chev"><Icon name="chev" size={14} /></span>Add another document or reading</summary>
          <div className="ev-body">
            <div className="chips">
              {docs.map((t) => <button key={t} type="button" className="chip-btn" onClick={() => setUpload(t)}>{DOC_WORD[t]}</button>)}
              <button type="button" className="chip-btn" onClick={locate} disabled={busy === 'location'}>Share location</button>
              {!outstanding.some((o) => outstandingWord(o).action === 'review') && <button type="button" className="chip-btn" onClick={askReview} disabled={busy === 'review'}>Request manual review</button>}
            </div>
            <p className="small muted">Location is read once, only when you tap, and is used to compare with your address. Stored with a timestamp; never tracked.</p>
          </div>
        </details>
      </section>

      <section aria-labelledby="dims-h">
        <div className="section-h"><h2 id="dims-h">What was checked</h2><span className="xs muted">Times in IST</span></div>
        <DimensionList dims={s.dimensions} checks={data.checks} />
        {!s.dimensions.length && !data.checks.length && <div style={{ paddingTop: 12 }}><Button size="sm" busy={busy === 'rerun'} busyLabel="Running checks…" onClick={rerun}>Run checks</Button></div>}
      </section>

      <Documents bid={b.bid} key={`docs-${data.checks.length}`} />

      <Limitations items={s.limitations || []} />

      <section className="stack sm">
        <SectionHead title="Your record" />
        <dl className="kv">
          <dt>Business type</dt><dd>{(b.constitution || '—').replace(/_/g, ' ')}</dd>
          {b.gstin && <><dt>GSTIN</dt><dd className="num">{b.gstin}</dd></>}
          {b.udyam && <><dt>Udyam</dt><dd className="num">{b.udyam}</dd></>}
          {b.fssai && <><dt>FSSAI</dt><dd className="num">{b.fssai}</dd></>}
          {b.cin_llpin && <><dt>CIN / LLPIN</dt><dd className="num">{b.cin_llpin}</dd></>}
          <dt>Address</dt><dd>{[b.address?.line, b.address?.city, b.address?.state, b.address?.pin].filter(Boolean).join(', ') || '—'}</dd>
          <dt>Representative</dt><dd>{[b.representative?.name, b.representative?.role].filter(Boolean).join(', ') || '—'}</dd>
          {b.geo?.captured_at && <><dt>Location shared</dt><dd>{ist(b.geo.captured_at)}</dd></>}
        </dl>
        <div className="row sm wrap" style={{ paddingTop: 8 }}>
          <ButtonLink href={`/network/business/${encodeURIComponent(b.bid)}/profile`} variant="secondary" size="sm">What other businesses see</ButtonLink>
        </div>
      </section>

      <AuditTrail bid={b.bid} key={`led-${data.checks.length}`} />

      <UploadSheet bid={b.bid} type={upload} onClose={() => setUpload(null)} onDone={(t) => { setUpload(null); setNote({ tone: 'ok', text: t }); reload(); }} />
    </div>
  );
}

function UploadSheet({ bid, type, onClose, onDone }: { bid: string; type: TnEvidenceType | null; onClose: () => void; onDone: (msg: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const photo = type === 'storefront_photo';
  async function send() {
    if (!type || !file) return;
    if (file.size > MAX_MB * 1024 * 1024) { setErr(`That file is larger than ${MAX_MB} MB.`); return; }
    setBusy(true); setErr(null);
    try {
      const r = await uploadEvidence(bid, type, file);
      if (r.evidence?.guard?.blocked) onDone('The document was received but held back by the safety screen. A reviewer will look at it.');
      else onDone(`${DOC_WORD[type]} received. Its fields will be compared with what you declared.`);
      setFile(null);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  return (
    <Sheet open={!!type} onClose={() => !busy && onClose()} title={type ? `Upload ${DOC_WORD[type].toLowerCase()}` : ''}>
      <p className="small muted">{photo ? 'A clear photo of the shop front with the name board visible.' : 'A photo or PDF of the certificate. Make sure the name and number are readable.'} Stored privately; only you and Sauda reviewers can open it. Businesses you trade with see a summary, never the file.</p>
      <label className="field">
        <span>Choose file <span className="hint">· JPG, PNG, WebP or PDF, up to {MAX_MB} MB</span></span>
        <input className="input" type="file" accept={photo ? 'image/jpeg,image/png,image/webp' : 'image/jpeg,image/png,image/webp,application/pdf'} capture={photo ? 'environment' : undefined} onChange={(e) => setFile(e.target.files?.[0] || null)} />
      </label>
      <p className="xs muted">Text inside documents is read as data only. Sauda never follows instructions written in a document.</p>
      {err && <Callout tone="bad">{err}</Callout>}
      <Button block busy={busy} busyLabel="Uploading…" disabled={!file} onClick={send}>Upload</Button>
      <Button variant="ghost" block onClick={onClose} disabled={busy}>Cancel</Button>
    </Sheet>
  );
}

function Documents({ bid }: { bid: string }) {
  const q = useAsync(() => listEvidence(bid), [bid]);
  const [open, setOpen] = useState<Record<string, string>>({});
  if (q.loading && !q.data) return null;
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={q.reload} title="Could not load your documents" />;
  const rows = q.data || [];
  if (!rows.length) return null;
  async function preview(e: TnEvidence) {
    setOpen((o) => ({ ...o, [e.eid]: 'loading' }));
    try { const url = await evidenceUrl(e.eid); window.open(url, '_blank', 'noopener,noreferrer'); setOpen((o) => ({ ...o, [e.eid]: '' })); }
    catch { setOpen((o) => ({ ...o, [e.eid]: 'unavailable' })); }
  }
  return (
    <section className="stack sm">
      <SectionHead title={`Your documents · ${rows.length}`} />
      <div className="list">
        {rows.map((e) => (
          <div key={e.eid} className="rowlink">
            <span className="none muted"><NIcon name="doc" size={18} /></span>
            <div className="grow stack xs">
              <span className="strong break">{DOC_WORD[e.type as TnEvidenceType] || String(e.type).replace(/_/g, ' ')}</span>
              <span className="small muted">{[e.mime?.split('/').pop()?.toUpperCase(), e.size ? `${Math.max(1, Math.round(e.size / 1024))} KB` : '', e.guard?.blocked ? 'held for review by the safety screen' : ''].filter(Boolean).join(' · ')}{open[e.eid] === 'unavailable' ? ' · Preview unavailable' : ''}</span>
            </div>
            <Button size="sm" variant="ghost" busy={open[e.eid] === 'loading'} busyLabel="Opening…" onClick={() => preview(e)}>Preview</Button>
          </div>
        ))}
      </div>
      <p className="xs muted">Only you and Sauda reviewers can open these. Preview links expire after 10 minutes.</p>
    </section>
  );
}

function AuditTrail({ bid }: { bid: string }) {
  const q = useAsync(() => getLedger(bid), [bid]);
  if (q.loading && !q.data) return null;
  if (q.error && !q.data) return <p className="xs muted">Audit trail unavailable right now. <button type="button" className="linkbtn" onClick={q.reload}>Try again</button></p>;
  const ev = q.data?.events || [];
  if (!ev.length) return null;
  const ok = q.data?.verification?.chain_ok ?? q.data?.verification?.ok;
  return (
    <section>
      <details className="evidence">
        <summary><span className="chev"><Icon name="chev" size={14} /></span>Audit trail · {ev.length} signed {ev.length === 1 ? 'entry' : 'entries'}{ok === true ? ' · chain intact' : ok === false ? ' · chain check failed' : ''}</summary>
        <div className="ev-body">
          <ol className="tl">
            {ev.slice().reverse().map((e, i) => {
              const t = String(e.type || e.event_type || 'event').replace(/^tn\./, '').replace(/[._]/g, ' ');
              const at = (e.ts || e.at || e.created_at) as string | undefined;
              return (
                <li key={i} className="tl-row done">
                  <span className="tl-dot"><Icon name="check" size={14} /></span>
                  <div className="tl-body"><div className="row between wrap sm"><span className="tl-title">{t}</span>{at && <span className="xs muted">{ist(at)}</span>}</div></div>
                </li>
              );
            })}
          </ol>
          <p className="xs muted">Every change to your verification is appended to a signed record. Contact details are masked before they are written.</p>
        </div>
      </details>
    </section>
  );
}
