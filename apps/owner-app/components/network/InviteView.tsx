'use client';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { istDate, relTime } from '@/lib/format';
import { createInvitation, listInvitations, looksLikeAadhaar, myBusinesses, pickBusiness, revokeInvitation } from '@/lib/network';
import { useAsync } from '@/lib/useAsync';
import type { TnBusinessMine, TnRole } from '@/lib/types';
import { Button, ButtonLink, Callout, EmptyState, ErrorState, Icon, SectionHead, Skeleton, StatusPill } from '../ui';
import { NIcon } from './shared';
import { SampleShopButton, WhatsAppShare } from './SampleShop';

type Line = { key: number; name: string; category: string; contact: string };
type Sent = { name: string; contact_masked: string; link: string; error?: string; duplicate?: boolean };
let seq = 1;
const blank = (): Line => ({ key: seq++, name: '', category: '', contact: '' });
const validContact = (c: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c.trim()) || /^(\+91[\s-]?)?[6-9]\d{9}$/.test(c.replace(/[\s-]/g, ''));

export function InviteView() {
  const sp = useSearchParams();
  const role: TnRole = sp.get('role') === 'buyer' ? 'buyer' : 'seller';
  const bidParam = sp.get('bid');
  const mine = useAsync(() => myBusinesses(), []);
  if (mine.loading && !mine.data) return <div className="narrow"><Skeleton lines={6} /></div>;
  if (mine.error && !mine.data) return <div className="narrow"><ErrorState error={mine.error} onRetry={mine.reload} title="Could not load your business" /></div>;
  const biz = (bidParam && mine.data?.find((b) => b.bid === bidParam)) || pickBusiness(mine.data || []);
  if (!biz) {
    return (
      <div className="narrow">
        <EmptyState icon="shield" title="Invitations come from a business" action={<div className="stack sm" style={{ width: '100%', maxWidth: 320 }}>
          <ButtonLink href={`/network/onboard?role=${role === 'seller' ? 'buyer' : 'seller'}`} block>Create your business profile</ButtonLink>
          <SampleShopButton block onReady={() => mine.reload()} />
        </div>}>
          Set up your business (it does not need to be fully verified), or explore a ready shop, then invite the {role === 'seller' ? 'suppliers' : 'buyers'} you trade with.
        </EmptyState>
      </div>
    );
  }
  return <Form biz={biz} role={role} />;
}

function Form({ biz, role }: { biz: TnBusinessMine; role: TnRole }) {
  const [lines, setLines] = useState<Line[]>([blank(), blank()]);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<Sent[] | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const invs = useAsync(() => listInvitations(biz.bid), [biz.bid, sent]);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revErr, setRevErr] = useState<string | null>(null);
  const who = role === 'seller' ? 'supplier' : 'buyer';

  const filled = lines.filter((l) => l.name.trim() || l.contact.trim());
  const bad = filled.filter((l) => !l.name.trim() || !validContact(l.contact) || looksLikeAadhaar(l.name));
  const upd = (k: number, p: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === k ? { ...l, ...p } : l)));

  async function send() {
    setTouched(true);
    if (!filled.length || bad.length) return;
    setBusy(true);
    const out: Sent[] = [];
    for (const l of filled) {
      try {
        const r = await createInvitation({ from_bid: biz.bid, role_invited: role, contact: l.contact.trim(), categories: l.category ? [l.category.trim()] : [], display_name: l.name.trim() });
        if (r.duplicate || !r.token) { out.push({ name: l.name.trim(), contact_masked: r.invitation?.contact_masked || '', link: '', duplicate: true }); continue; }
        const link = r.share_url || `${window.location.origin}/invite/${encodeURIComponent(r.token)}`;
        out.push({ name: l.name.trim(), contact_masked: r.invitation?.contact_masked || '', link });
      } catch (e) {
        out.push({ name: l.name.trim(), contact_masked: '', link: '', error: e instanceof Error ? e.message : String(e) });
      }
    }
    setSent(out); setBusy(false); setTouched(false); setLines([blank()]);
  }
  async function copy(i: number, text: string) {
    try { await navigator.clipboard.writeText(text); setCopied(i); setTimeout(() => setCopied(null), 2000); } catch { setCopied(-1); }
  }

  const invited = (invs.data || []).filter((i) => i.role_invited === role);
  async function revoke(iid: string) {
    setRevoking(iid); setRevErr(null);
    try { await revokeInvitation(iid); invs.reload(); } catch (e) { setRevErr(e instanceof Error ? e.message : String(e)); } finally { setRevoking(null); }
  }
  const INV: Record<string, { label: string; tone: 'ok' | 'neutral' | 'bad' | 'info' }> = { sent: { label: 'Sent, not yet opened', tone: 'info' }, accepted: { label: 'Accepted', tone: 'ok' }, expired: { label: 'Expired', tone: 'neutral' }, revoked: { label: 'Revoked', tone: 'neutral' } };
  return (
    <div className="narrow">
      <Link href="/network" className="small muted row sm tn-back" style={{ minHeight: 32 }}><Icon name="chev" size={14} /><span>Network</span></Link>
      <div className="page-head">
        <h1>{role === 'seller' ? 'Invite your suppliers' : 'Invite your buyers'}</h1>
        <p>From {biz.display_name}. Each {who} gets a private link to verify their business and accept. Either side can decide not to trade.</p>
      </div>

      {sent && (
        <section className="share" aria-live="polite" aria-labelledby="links-h">
          <h2 id="links-h">Share these links yourself</h2>
          <p className="small">Sauda does not send messages. Copy each link, or tap Share on WhatsApp to open WhatsApp with the message ready (only your business name and the link are included). <b>Each link is shown only once</b>; if you lose it, send a new invitation.</p>
          {sent.map((s, i) => (
            <div key={i} className="stack xs">
              <span className="strong break">{s.name}{s.contact_masked ? <span className="muted small"> · {s.contact_masked}</span> : null}</span>
              {s.error ? <Callout tone="bad">{s.error}</Callout> : s.duplicate ? <Callout tone="neutral">Already invited. The link was shown when the invitation was first created; Sauda cannot show it again. Revoke it below and invite again if the link was lost.</Callout> : (
                <div className="row sm wrap">
                  <code className="grow">{s.link}</code>
                  <Button size="sm" variant="secondary" onClick={() => copy(i, s.link)} aria-label={`Copy link for ${s.name}`}><NIcon name="copy" size={14} />{copied === i ? 'Copied' : 'Copy'}</Button>
                  <WhatsAppShare business={biz.display_name} link={s.link} />
                </div>
              )}
            </div>
          ))}
          {copied === -1 && <p className="small" style={{ color: 'var(--bad)' }}>Copy was blocked by the browser. Select the link and copy it by hand.</p>}
        </section>
      )}

      <form className="stack" onSubmit={(e) => { e.preventDefault(); send(); }} noValidate aria-labelledby="add-h">
        <SectionHead title={<span id="add-h">{sent ? `Invite more ${who}s` : `Add ${who}s`}</span>} />
        <div style={{ borderTop: '1px solid var(--line)' }}>
          {lines.map((l, i) => {
            const show = touched && (l.name.trim() || l.contact.trim());
            return (
              <div key={l.key} className="inv-row">
                <label className="field"><span>Business name</span><input className="input" value={l.name} onChange={(e) => upd(l.key, { name: e.target.value })} aria-invalid={!!show && !l.name.trim()} /></label>
                <label className="field"><span>Category <span className="hint">· optional</span></span><input className="input" value={l.category} placeholder={role === 'seller' ? 'Rice, oil…' : 'Kirana…'} onChange={(e) => upd(l.key, { category: e.target.value })} /></label>
                <label className="field"><span>Phone or email</span><input className="input" value={l.contact} inputMode="email" autoComplete="off" onChange={(e) => upd(l.key, { contact: e.target.value })} aria-invalid={!!show && !validContact(l.contact)} />
                  {show && !validContact(l.contact) ? <span className="fieldmsg bad">Enter a 10-digit mobile number or an email address</span> : null}</label>
                <Button type="button" variant="ghost" size="sm" className="icon" aria-label={`Remove row ${i + 1}`} onClick={() => setLines((ls) => (ls.length > 1 ? ls.filter((x) => x.key !== l.key) : [blank()]))}><Icon name="trash" size={16} /></Button>
              </div>
            );
          })}
        </div>
        <div><Button type="button" variant="secondary" size="sm" icon="plus" onClick={() => setLines((ls) => [...ls, blank()])}>Add another</Button></div>
        <p className="xs muted">Contacts are stored masked and hashed, used only for this invitation. Sauda does not message them.</p>
        {touched && !filled.length && <Callout tone="bad">Add at least one {who}.</Callout>}
        <Button type="submit" block busy={busy} busyLabel="Creating links…" disabled={!filled.length}>
          {filled.length > 1 ? `Create ${filled.length} invitation links` : 'Create invitation link'}
        </Button>
      </form>

      <section aria-labelledby="track-h">
        <SectionHead title={<span id="track-h">{role === 'seller' ? 'Suppliers' : 'Buyers'} you have invited</span>} />
        {invs.loading && !invs.data && <Skeleton lines={3} />}
        {invs.error && !invs.data ? <ErrorState error={invs.error} onRetry={invs.reload} title="Could not load invitations" /> : null}
        {invs.data && invited.length === 0 && <p className="small muted">None yet.</p>}
        {revErr && <Callout tone="bad">{revErr}</Callout>}
        <div className="list">
          {invited.map((i) => {
            const w = INV[i.status] || { label: i.status, tone: 'neutral' as const };
            const body = (
              <div className="grow stack xs">
                <span className="strong break">{i.display_name_hint || i.display_name || i.contact_masked}</span>
                <span className="small muted row sm wrap" style={{ rowGap: 0 }}><StatusPill tone={w.tone}>{w.label}</StatusPill><span>{i.contact_masked}</span>{i.categories?.length ? <span>{i.categories.join(', ')}</span> : null}{i.created_at && <span>{relTime(i.created_at)}</span>}{i.status === 'sent' && i.expires_at && <span>expires {istDate(i.expires_at)}</span>}</span>
              </div>
            );
            return i.rid ? (
              <Link key={i.iid} href={`/network/relationships/${encodeURIComponent(i.rid)}?bid=${encodeURIComponent(biz.bid)}`} className="rowlink">{body}<span className="chev-ico"><Icon name="chev" size={16} /></span></Link>
            ) : (
              <div key={i.iid} className="rowlink">{body}{i.status === 'sent' && <Button size="sm" variant="ghost" busy={revoking === i.iid} busyLabel="Revoking…" onClick={() => revoke(i.iid)}>Revoke</Button>}</div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
