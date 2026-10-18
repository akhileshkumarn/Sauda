'use client';
// Buyer / seller role switch for a business. A business can be both. Identity checks are reused; only
// the checks that apply to the new role are added.
import { useState } from 'react';
import { ApiError } from '@/lib/api';
import { dimWord, statusWord } from '@/lib/network';
import { changeRoles, type RoleChangeResult } from '@/lib/networkRoles';
import type { TnBusiness, TnRole } from '@/lib/types';
import { Button, Callout, SectionHead } from '../ui';

const LABEL: Record<TnRole, string> = { buyer: 'I buy for my shop', seller: 'I sell to other businesses' };
const ON_TEXT: Record<TnRole, string> = {
  seller: 'Turning on selling lets you list in Find suppliers. Your identity checks are reused; supplier-only checks will be added.',
  buyer: 'Turning on buying lets you find suppliers and ask to connect. Your identity checks are reused.',
};
const OFF_TEXT: Record<TnRole, string> = {
  seller: 'Turning off selling removes you from Find suppliers. It is blocked while buyers have an active relationship with you as a supplier.',
  buyer: 'Turning off buying stops supplier search and requests. It is blocked while suppliers have an active relationship with you as a buyer.',
};

export function RoleSwitch({ business, onChanged }: { business: TnBusiness; onChanged?: () => void }) {
  const current = business.roles;
  const [pending, setPending] = useState<TnRole[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad' | 'warn'; title?: string; text: string; checks?: NonNullable<RoleChangeResult['role_change']>['new_checks'] } | null>(null);
  const shown = pending || current;

  function toggle(r: TnRole, on: boolean) {
    const next = (on ? [...shown, r] : shown.filter((x) => x !== r)).filter((x, i, a) => a.indexOf(x) === i);
    const same = next.length === current.length && next.every((x) => current.includes(x));
    setMsg(null);
    setPending(same ? null : (['buyer', 'seller'] as TnRole[]).filter((x) => next.includes(x)));
  }

  const added = (pending || []).filter((r) => !current.includes(r));
  const removed = pending ? current.filter((r) => !pending.includes(r)) : [];

  async function confirm() {
    if (!pending) return;
    setBusy(true); setMsg(null);
    try {
      const r = await changeRoles(business.bid, business.version, pending);
      const rc = r.role_change;
      setPending(null);
      setMsg({ tone: 'ok', title: 'Roles updated.', text: rc?.added?.length ? 'Your identity checks were reused. These checks were added for the new role:' : 'Your roles were updated.', checks: rc?.new_checks });
      onChanged?.();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'role_in_use') setMsg({ tone: 'warn', title: 'Not changed.', text: e.message || 'Active relationships depend on this role. Pause or close them first.' });
      else if (e instanceof ApiError && e.code === 'version_conflict') setMsg({ tone: 'warn', title: 'This business changed elsewhere.', text: 'Reload the page and try again.' });
      else setMsg({ tone: 'bad', text: e instanceof Error ? e.message : String(e) });
    } finally { setBusy(false); }
  }

  return (
    <section className="stack sm" aria-labelledby="roles-h">
      <SectionHead title={<span id="roles-h">How you trade</span>} />
      {(['buyer', 'seller'] as TnRole[]).map((r) => (
        <label key={r} className="check-row">
          <input type="checkbox" checked={shown.includes(r)} disabled={busy || (shown.length === 1 && shown.includes(r))} onChange={(e) => toggle(r, e.target.checked)} />
          <span>{LABEL[r]}</span>
        </label>
      ))}
      <p className="xs muted">A business needs at least one role.</p>
      {pending && (
        <Callout tone="info" title="Confirm the change">
          <span className="stack xs">
            {added.map((r) => <span key={`a-${r}`}>{ON_TEXT[r]}</span>)}
            {removed.map((r) => <span key={`r-${r}`}>{OFF_TEXT[r]}</span>)}
            <span className="row sm wrap" style={{ paddingTop: 6 }}>
              <Button size="sm" busy={busy} busyLabel="Saving…" onClick={confirm}>Confirm</Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPending(null)}>Cancel</Button>
            </span>
          </span>
        </Callout>
      )}
      {msg && (
        <Callout tone={msg.tone} title={msg.title}>
          <span className="stack xs">
            <span>{msg.text}</span>
            {msg.checks && msg.checks.length > 0 && (
              <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                {msg.checks.map((c) => <li key={c.check_id}>{dimWord(c.dim).label}: {statusWord(c.status).label.toLowerCase()}. {c.summary}</li>)}
              </ul>
            )}
          </span>
        </Callout>
      )}
    </section>
  );
}
