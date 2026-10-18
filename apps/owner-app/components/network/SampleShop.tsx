'use client';
// "Try with a sample shop", the profile chooser and WhatsApp share. Shared by Network, Find suppliers and invitations.
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { onUser } from '@/lib/auth';
import { SAMPLE_NOTE, inviteMessage, rememberBid, sandboxDelete, sandboxStart, whatsappHref } from '@/lib/network';
import { Button, ButtonLink, Callout } from '../ui';
import { Sheet } from '../ui-client';
import { NIcon } from './shared';

function useFirstName(): string {
  const [n, setN] = useState('');
  useEffect(() => {
    let off: (() => void) | undefined;
    onUser((u) => setN((u?.name || '').split(/\s+/)[0] || '')).then((f) => { off = f; }).catch(() => {});
    return () => { off?.(); };
  }, []);
  return n;
}

/** Starts (or reopens) the user's personal sample shop, then goes to it or calls onReady. */
export function useStartSample(onReady?: (bid: string) => void) {
  const router = useRouter();
  const first = useFirstName();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function start() {
    setBusy(true); setErr(null);
    try {
      const r = await sandboxStart(first);
      rememberBid(r.business.bid);
      if (onReady) onReady(r.business.bid);
      else router.push(`/network/business/${encodeURIComponent(r.business.bid)}`);
    } catch (e) {
      setErr(`Could not open a sample shop just now. ${e instanceof Error ? e.message : ''} Try again, or fill in the form instead.`);
    } finally { setBusy(false); }
  }
  return { start, busy, err };
}

export function SampleShopButton({ variant = 'secondary', block, onReady, label = 'Try with a sample shop' }:
  { variant?: 'primary' | 'secondary' | 'ghost'; block?: boolean; onReady?: (bid: string) => void; label?: string }) {
  const s = useStartSample(onReady);
  return (
    <div className="stack xs" style={block ? { width: '100%' } : undefined}>
      <Button variant={variant} block={block} busy={s.busy} busyLabel="Opening your sample shop…" onClick={s.start}><NIcon name="flask" size={16} />{label}</Button>
      {s.err && <Callout tone="bad">{s.err}</Callout>}
    </div>
  );
}

/** The quiet text link on Find suppliers. */
export function SampleShopLink({ onReady }: { onReady?: (bid: string) => void }) {
  const s = useStartSample(onReady);
  return (
    <p className="small muted row sm wrap" style={{ alignItems: 'center' }}>
      <NIcon name="flask" size={14} />
      <span>No shop to hand?</span>
      <button type="button" onClick={s.start} disabled={s.busy}
        style={{ background: 'none', border: 0, padding: 0, color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer', font: 'inherit', minHeight: 32 }}>
        {s.busy ? 'Opening your sample shop…' : 'Try with a sample shop'}
      </button>
      {s.err && <span role="alert">{s.err}</span>}
    </p>
  );
}

/** Opened by "Request to connect" when the viewer has no buying business yet. */
export function ProfileChooser({ open, onClose, onSample }: { open: boolean; onClose: () => void; onSample: (bid: string) => void }) {
  return (
    <Sheet open={open} onClose={onClose} title="First, a business to connect as">
      <p className="small muted">Suppliers see a redacted profile of the business that asks to connect. Pick one way to continue; you keep your search.</p>
      <div className="stack sm">
        <ButtonLink href="/network/onboard?role=buyer" block>Create your business profile</ButtonLink>
        <SampleShopButton block onReady={(bid) => { onClose(); onSample(bid); }} />
      </div>
      <p className="xs muted">{SAMPLE_NOTE}</p>
    </Sheet>
  );
}

/** A plain wa.me link with prefilled text. No API, no credentials, no private data. */
export function WhatsAppShare({ business, link, label = 'Share on WhatsApp', text, variant = 'secondary' }:
  { business: string; link: string; label?: string; text?: string; variant?: 'primary' | 'secondary' }) {
  return (
    <a className={`btn ${variant === 'primary' ? '' : 'secondary'} sm`} href={whatsappHref(text || inviteMessage(business, link))}
      target="_blank" rel="noopener noreferrer" aria-label={`${label} (opens WhatsApp)`}>
      <NIcon name="send" size={14} />{label}
    </a>
  );
}

/** Banner shown on a sample shop, with reset and delete. */
export function SampleBanner({ onChanged }: { onChanged?: () => void }) {
  const router = useRouter();
  const first = useFirstName();
  const [busy, setBusy] = useState<'reset' | 'delete' | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  async function reset() {
    setBusy('reset');
    try { await sandboxDelete(); const r = await sandboxStart(first); rememberBid(r.business.bid); onChanged?.(); router.refresh(); }
    finally { setBusy(null); }
  }
  async function del() {
    setBusy('delete');
    try { await sandboxDelete(); try { localStorage.removeItem('sauda-tn-bid'); } catch { /* ignore */ } router.push('/network'); onChanged?.(); }
    finally { setBusy(null); }
  }
  return (
    <Callout tone="neutral" icon="flask" title="Sample shop">
      <span>{SAMPLE_NOTE} Every feature works on it; checks are simulated, so it shows as Partially verified (sample).</span>
      <span className="row sm wrap" style={{ marginTop: 8 }}>
        <Button size="sm" variant="secondary" busy={busy === 'reset'} busyLabel="Resetting…" onClick={reset}>Start the sample again</Button>
        {confirmDel
          ? <><Button size="sm" variant="secondary" busy={busy === 'delete'} busyLabel="Deleting…" onClick={del}>Yes, delete it</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDel(false)}>Keep it</Button></>
          : <Button size="sm" variant="ghost" onClick={() => setConfirmDel(true)}>Delete sample shop</Button>}
      </span>
    </Callout>
  );
}
