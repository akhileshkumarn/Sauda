'use client';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { getMandate, revokeMandate } from '@/lib/api';
import { ist } from '@/lib/format';
import { productNames } from '@/lib/session';
import { useAsync } from '@/lib/useAsync';
import type { MandateStatus } from '@/lib/types';
import { Permissions } from './Permissions';
import { Button, ButtonLink, Callout, Card, ErrorState, Evidence, Icon, Money, Skeleton, StatusPill, type Tone } from './ui';
import { Sheet } from './ui-client';

const STATUS: Record<MandateStatus, { tone: Tone; label: string }> = {
  active: { tone: 'ok', label: 'Active' },
  consumed: { tone: 'neutral', label: 'Used for an order' },
  revoked: { tone: 'bad', label: 'Switched off' },
  expired: { tone: 'warn', label: 'Expired' },
  draft: { tone: 'neutral', label: 'Draft' },
};

export function MandateCard({ id, justSigned, sid }: { id: string; justSigned?: boolean; sid?: string }) {
  const { data: m, error, loading, reload, setData } = useAsync(() => getMandate(id), [id]);
  const [arming, setArming] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [err, setErr] = useState<string | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => { setNames(productNames()); }, []);

  if (loading && !m) return <Skeleton lines={6} />;
  if (error || !m) return <ErrorState error={error} onRetry={reload} title="Could not load these limits" />;

  const b = m.body as Record<string, unknown>;
  const lines = ((b.lines as { gtin: string; qty: number; ceiling_paise: number; ceiling_source?: string; name?: string }[]) || [])
    .map((l) => ({ ...l, name: l.name || names[l.gtin] }));
  const st = STATUS[m.status] || { tone: 'neutral' as Tone, label: m.status };

  async function revoke() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setErr(null);
    try {
      const r = await revokeMandate(id);
      setData({ ...m!, status: (r.status as MandateStatus) || 'revoked' });
      setArming(false);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); inFlight.current = false; }
  }

  return (
    <div className="stack lg">
      {justSigned && m.status === 'active' && <Callout tone="ok" title="Limits signed.">Sauda can now ask suppliers for quotes, but only inside these limits.</Callout>}
      {m.status === 'revoked' && <Callout tone="bad" title="Switched off.">Every action under these limits is now refused. Nothing more can be ordered with them.</Callout>}
      {m.status === 'expired' && <Callout tone="warn" title="Expired.">Start a new restock to sign fresh limits.</Callout>}

      <div className="stack xs">
        <span className="small muted">Budget</span>
        <span className="hero-num"><Money paise={Number(b.budget_paise || 0)} whole /></span>
        <span className="small muted row sm wrap" style={{ rowGap: 0 }}><StatusPill tone={st.tone}>{st.label}</StatusPill><span>expires {ist(m.expires_at || (b.expires_at as string))}</span></span>
      </div>
      <Card>
        <Permissions m={{
          budget_paise: Number(b.budget_paise || 0),
          suppliers: (b.allowed_supplier_ids as string[]) || [],
          lines,
          max_advance_pct: Number(b.max_advance_pct ?? 0),
          deliver_by: String(b.deliver_by || ''),
          expires_at: String(m.expires_at || b.expires_at || ''),
        }} />
      </Card>

      {err && <Callout tone="bad">{err}</Callout>}
      {m.status === 'active' && (
        <div className="stack">
          <ButtonLink href={`/restock?run=${encodeURIComponent(m.mandate_id)}${sid ? `&sid=${encodeURIComponent(sid)}` : ''}`} block>Start negotiating</ButtonLink>
          <div className="row between wrap sm">
            {sid ? <Link className="linkbtn muted" style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center' }} href={`/restock/${encodeURIComponent(sid)}`}>Back to this restock</Link> : <span />}
            <button type="button" className="linkbtn muted" style={{ minHeight: 44 }} onClick={() => setArming(true)}>Switch off these limits</button>
          </div>
          <Sheet open={arming} onClose={() => !busy && setArming(false)} title="Switch off these limits?">
            <p className="muted">Any running negotiation stops, and nothing can be ordered under them. This cannot be undone.</p>
            <Button variant="danger-solid" block onClick={revoke} busy={busy} busyLabel="Switching off…">Switch off</Button>
            <Button variant="ghost" block onClick={() => setArming(false)} disabled={busy}>Keep them</Button>
          </Sheet>
        </div>
      )}

      <Evidence label="Signature details">
        <div className="row sm"><Icon name="lock" size={14} /><span>Intent mandate <span className="code">{m.mandate_id}</span>, signed with Cloud KMS key version {String(m.kms_key_version)}. Autonomy tier {String(b.autonomy_tier ?? '—')} (owner approves orders).</span></div>
        <div>Body hash (SHA-256 of canonical JSON)<div className="mono">{m.body_hash}</div></div>
        <div>Signature<div className="mono faint">{m.signature}</div></div>
        <pre className="json">{JSON.stringify(m.body, null, 2)}</pre>
      </Evidence>
    </div>
  );
}
