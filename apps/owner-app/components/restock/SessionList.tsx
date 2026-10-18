'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import { createSession, listSessions } from '@/lib/api';
import { relTime } from '@/lib/format';
import { useAsync } from '@/lib/useAsync';
import type { SessionSummary } from '@/lib/types';
import { sessionLabel } from '../status';
import { Button, Callout, EmptyState, ErrorState, Icon, Money, PageHead, StatusPill } from '../ui';

/** "New restock": always creates a new session; never reuses or overwrites an existing one. */
export function NewRestockButton({ block = true, variant }: { block?: boolean; variant?: 'secondary' }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const once = useRef(false);
  async function go() {
    if (once.current) return;
    once.current = true; setBusy(true); setErr(null);
    try { const s = await createSession(); router.push(`/restock/${encodeURIComponent(s.sid)}`); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); once.current = false; }
  }
  return (
    <div className="stack sm">
      <Button block={block} variant={variant} icon="plus" busy={busy} busyLabel="Starting…" onClick={go}>New restock</Button>
      {err && <Callout tone="bad">Could not start a restock: {err}</Callout>}
    </div>
  );
}

export function SessionRow({ r }: { r: SessionSummary }) {
  const money = r.total_paise ?? r.budget_paise ?? null;
  const st = sessionLabel(r.status);
  const attention = r.needs_attention && r.status !== 'awaiting_approval';
  return (
    <Link href={`/restock/${encodeURIComponent(r.sid)}`} className="li sess-row rf-sess">
      <div className="stack xs" style={{ minWidth: 0 }}>
        <span className="strong ellipsis" title={r.title || undefined}>{r.title || 'Untitled restock'}</span>
        <span className="small muted num row sm wrap" style={{ rowGap: 0 }}>
          <StatusPill tone={attention ? 'warn' : st.tone}>{attention ? 'Needs a look' : st.label}</StatusPill>
          <span>{r.line_count} {r.line_count === 1 ? 'item' : 'items'} · {relTime(r.updated_at)}</span>
        </span>
      </div>
      <span className="amt">{money ? <><Money paise={money} whole /><small>{r.total_paise ? 'total' : 'up to'}</small></> : null}</span>
      <span className="chev-ico"><Icon name="chev" size={16} /></span>
    </Link>
  );
}

export function SessionList() {
  const { data, error, loading, reload } = useAsync(() => listSessions({ limit: 20 }), []);
  const [q, setQ] = useState('');
  const rows = (data || []).filter((r) => !q.trim() || (r.title || '').toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div className="stack lg">
      <PageHead title="Restocks" description="Every list you have started, newest first. Open one to carry on where you left off."
        action={<div className="ph-primary"><NewRestockButton /></div>} />
      {loading && !data && (
        <div className="rf-skel-rows" aria-busy="true" aria-label="Loading your restocks">
          {[62, 48, 56, 40].map((w) => <div key={w} className="rf-skel-row" style={{ minHeight: 64 }}><div className="stack xs"><div className="skeleton" style={{ width: `${w}%` }} /><div className="skeleton rf-sm" /></div><div className="skeleton" /></div>)}
        </div>
      )}
      {error && !data ? <ErrorState error={error} onRetry={reload} title="Could not load your restocks" /> : null}
      {data && data.length === 0 && (
        <EmptyState icon="cart" title="No restocks yet">Tap New restock, then say or type what you need, like “10 atta 5 kg, 20 sunflower oil”.</EmptyState>
      )}
      {data && data.length > 0 && (
        <div className="stack sm">
          {data.length > 5 && <input className="input" type="search" placeholder="Search restocks" aria-label="Search restocks" value={q} onChange={(e) => setQ(e.target.value)} />}
          <div className="list">{rows.map((r) => <SessionRow key={r.sid} r={r} />)}</div>
          {rows.length === 0 && <p className="small muted">No restock matches “{q}”.</p>}
        </div>
      )}
      <p className="xs muted row sm" style={{ gap: 6 }}><Icon name="lock" size={12} />Only you see these. Nothing is bought until you approve.</p>
    </div>
  );
}
