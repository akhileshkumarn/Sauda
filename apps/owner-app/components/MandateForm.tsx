'use client';
import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import { ApiError, SHOP_ID, signMandate } from '@/lib/api';
import { plusDaysIso, rupees, SUPPLIER_NAMES, supplierName } from '@/lib/format';
import { rememberProducts } from '@/lib/session';
import type { Draft, DraftLine, IntentMandateBody } from '@/lib/types';
import { Permissions } from './Permissions';
import { Button, Callout, Card, Icon } from './ui';

function nonce() {
  const a = new Uint8Array(12); crypto.getRandomValues(a);
  return Array.from(a).map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** IST end-of-day N days from today, ISO with +05:30. Day 0 = tonight. */
function expiryIso(days: number) {
  return `${plusDaysIso(days)}T23:59:00+05:30`;
}

export function MandateForm({ draft, lines, negotiationId, sid }: { draft: Draft; lines: DraftLine[]; negotiationId?: string; sid?: string }) {
  const router = useRouter();
  const atCeiling = lines.reduce((s, l) => s + l.qty * l.ceiling_paise, 0);
  const initialBudget = draft.stated_budget_paise ?? draft.suggested_budget_paise ?? draft.budget_paise ?? atCeiling;
  const [budgetRupees, setBudgetRupees] = useState(String(Math.ceil(initialBudget / 100)));
  const allSuppliers = draft.allowed_supplier_ids?.length ? draft.allowed_supplier_ids : Object.keys(SUPPLIER_NAMES);
  const [suppliers, setSuppliers] = useState<string[]>(allSuppliers.slice(0, 3));
  const [advance, setAdvance] = useState(20);
  const [deliverBy, setDeliverBy] = useState(draft.deliver_by && draft.deliver_by >= plusDaysIso(0) ? draft.deliver_by : plusDaysIso(7));
  const [expiryDays, setExpiryDays] = useState(1);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [err, setErr] = useState<string | null>(null);

  const budgetPaise = Math.round(parseFloat(budgetRupees || '0') * 100);
  const expiresAt = expiryIso(expiryDays);
  const problems: string[] = [];
  if (!lines.length) problems.push('Add at least one item.');
  if (!(budgetPaise > 0)) problems.push('Set a budget above ₹0.');
  if (!suppliers.length) problems.push('Choose at least one supplier.');
  if (deliverBy < plusDaysIso(0)) problems.push('Deliver-by date cannot be in the past.');
  const tight = budgetPaise > 0 && budgetPaise < atCeiling;

  async function sign() {
    if (inFlight.current || problems.length) return; // double-submit guard
    inFlight.current = true; setErr(null); setBusy(true);
    const body: IntentMandateBody = {
      kind: 'intent',
      shop_id: draft.shop_id || SHOP_ID,
      budget_paise: budgetPaise,
      allowed_supplier_ids: suppliers,
      lines: lines.map((l) => ({ gtin: l.gtin, qty: l.qty, ceiling_paise: l.ceiling_paise, ceiling_source: l.ceiling_source })),
      max_advance_pct: advance,
      deliver_by: deliverBy,
      autonomy_tier: 2,
      expires_at: expiresAt,
      nonce: nonce(),
    };
    try {
      rememberProducts(lines);
      const r = await signMandate(body, negotiationId);
      router.push(`/mandate/${encodeURIComponent(r.mandate_id)}?new=1${sid ? `&sid=${encodeURIComponent(sid)}` : ''}`);
    } catch (e) {
      const msg = e instanceof ApiError && e.status === 409 ? 'Someone else is restocking this shop right now. Only one negotiation runs per shop at a time; try signing again in a minute.'
        : e instanceof ApiError && e.status === 422 ? `Sauda could not accept these limits: ${e.message}` : e instanceof Error ? e.message : String(e);
      setErr(msg);
      setBusy(false); inFlight.current = false;
    }
  }

  return (
    <Card title="Your limits" subtitle="Sauda can only act inside these.">
      <div className="stack lg">
        <label className="field rf-budget">Total budget
          <div className="input-affix"><span aria-hidden>₹</span>
            <input className="input num" inputMode="numeric" value={budgetRupees} aria-describedby="budget-hint" aria-invalid={!(budgetPaise > 0)}
              onChange={(e) => setBudgetRupees(e.target.value.replace(/[^\d]/g, '').slice(0, 9))} />
          </div>
          <span id="budget-hint" className="rf-budget-hint">
            <span>{lines.length} {lines.length === 1 ? 'item' : 'items'} at ceiling</span>
            <span className="num">{rupees(atCeiling, true)}</span>
          </span>
        </label>
        {tight && <Callout tone="warn">Budget is below the ceiling total, so Sauda must negotiate down or leave items out.</Callout>}

        <div className="field" role="group" aria-labelledby="sup-label">
          <span id="sup-label">Suppliers Sauda may contact</span>
          <div className="chips rf-chips">
            {allSuppliers.map((s) => {
              const on = suppliers.includes(s);
              return (
                <button type="button" key={s} className="chip-btn" aria-pressed={on} disabled={!on && suppliers.length >= 3}
                  onClick={() => setSuppliers((cur) => (on ? cur.filter((x) => x !== s) : cur.length >= 3 ? cur : [...cur, s]))}>
                  {on ? <Icon name="check" size={14} /> : null}{supplierName(s)}
                </button>
              );
            })}
          </div>
          <span className="hint">Simulated suppliers · up to 3</span>
        </div>

        <div className="grid2 stack-narrow">
          <label className="field">Most advance allowed
            <select className="input" value={advance} onChange={(e) => setAdvance(parseInt(e.target.value, 10))}>
              {[0, 10, 20].map((v) => <option key={v} value={v}>{v === 0 ? 'No advance' : `${v}% of order`}</option>)}
            </select>
          </label>
          <label className="field">Deliver by
            <input className="input" type="date" value={deliverBy} min={plusDaysIso(0)} onChange={(e) => setDeliverBy(e.target.value)} />
          </label>
        </div>
        <label className="field">Limits expire
          <select className="input" value={expiryDays} onChange={(e) => setExpiryDays(parseInt(e.target.value, 10))}>
            <option value={0}>Tonight, 23:59 IST</option>
            <option value={1}>Tomorrow, 23:59 IST</option>
            <option value={3}>In 3 days</option>
            <option value={6}>In 6 days</option>
          </select>
        </label>

        <div className="stack sm">
          <Permissions showLines={false} m={{ budget_paise: budgetPaise, suppliers, lines, max_advance_pct: advance, deliver_by: deliverBy, expires_at: expiresAt }} />
        </div>

        {problems.length > 0 && <Callout tone="warn" title="Fix before signing:">{problems.join(' ')}</Callout>}
        {err && <Callout tone="bad">{err}</Callout>}
        <div className="rf-signbar" role="group" aria-label="Sign your limits">
          <Button block busy={busy} busyLabel="Signing…" disabled={problems.length > 0} onClick={sign} icon="lock">
            Sign limits · {rupees(budgetPaise, true)}
          </Button>
          <p className="caption">Signing buys nothing. You approve every order.</p>
        </div>
      </div>
    </Card>
  );
}
