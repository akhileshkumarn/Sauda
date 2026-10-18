'use client';
import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import { answerConfirmation, ApiError, getConfirmation } from '@/lib/api';
import { cap1, ceilingSource, ist, istDate, maskVpa, reasonText, rupees, supplierName } from '@/lib/format';
import { rememberNegotiation } from '@/lib/session';
import { useAsync } from '@/lib/useAsync';
import type { Allocation, Confirmation } from '@/lib/types';
import { GateReport } from './GateReport';
import { Button, ButtonLink, Callout, ErrorState, Evidence, Icon, Meter, Money, SETTLEMENT_CAPTION, StatusPill } from './ui';

function SupplierBlock({ a, why }: { a: Allocation; why: Confirmation['cart']['why'] }) {
  const name = supplierName(a.supplier_id, a.supplier_name);
  const adv = Math.round((a.subtotal_paise * (a.advance_pct || 0)) / 100);
  const reasons = a.lines.map((l) => ({ l, w: why?.find((x) => x.gtin === l.gtin && x.supplier_id === a.supplier_id) }));
  return (
    <section className="stack sm" aria-label={name}>
      <div className="rf-sup-h">
        <h2><span title={name}>{name}</span><span className="tag">Partner agent</span></h2>
        <Money paise={a.subtotal_paise} className="strong rf-num" />
      </div>
      <ul className="rf-items">
        {a.lines.map((l) => {
          const under = l.unit_price_paise <= l.ceiling_paise;
          const opened = l.opening_price_paise && l.opening_price_paise > l.unit_price_paise ? l.opening_price_paise : null;
          return (
            <li key={l.gtin} className="rf-item">
              <span className="nm rf-clamp" title={cap1(l.name)}>{cap1(l.name)}</span>
              <Money paise={l.qty * l.unit_price_paise} className="amt rf-num" />
              <span className="meta">
                <span>{l.qty.toLocaleString('en-IN')} × {rupees(l.unit_price_paise)}</span>
                {opened ? <span><span className="sr-only">opened at </span><span className="strike">{rupees(opened)}</span></span> : null}
                {!under && <StatusPill tone="bad">Over ceiling {rupees(l.ceiling_paise)}</StatusPill>}
              </span>
            </li>
          );
        })}
      </ul>
      <span className="rf-terms">
        <span>Paid to <span className="mono" style={{ fontSize: 13 }}>{maskVpa(a.payee_vpa, a.payout_vpa_masked)}</span></span>
        <span>· {a.delivery_days != null ? `delivery in ${a.delivery_days} ${a.delivery_days === 1 ? 'day' : 'days'}` : 'delivery not stated'}</span>
        <span>· {a.advance_pct ? <>{a.advance_pct}% advance (<Money paise={adv} />)</> : 'no advance'}</span>
      </span>
      <Evidence label="Why this supplier">
        <div className="row sm"><StatusPill tone="ok">Registered supplier</StatusPill><span>· payout account on record</span></div>
        {reasons.map(({ l, w }) => (
          <div key={l.gtin}>
            <b style={{ color: 'var(--ink)', fontWeight: 500 }}>{cap1(l.name)}</b>: {w ? w.text.replace(/^[^:]+:\s*/, '') : 'chosen by Sauda'}. Ceiling {rupees(l.ceiling_paise)} ({ceilingSource(l.ceiling_source)}{l.ceiling_as_of ? `, ${istDate(l.ceiling_as_of)}` : ''}).
          </div>
        ))}
      </Evidence>
    </section>
  );
}

function ConfirmSkeleton() {
  return (
    <div className="rf-skel" aria-busy="true" aria-label="Loading the cart">
      <div className="stack sm"><div className="skeleton rf-sm" /><div className="skeleton rf-hero" /><div className="skeleton" style={{ height: 6, width: '70%' }} /></div>
      <div className="rf-skel-rows">{[72, 60, 66, 54].map((w) => <div key={w} className="rf-skel-row"><div className="skeleton" style={{ width: `${w}%` }} /><div className="skeleton" /></div>)}</div>
    </div>
  );
}

export function ConfirmView({ id }: { id: string }) {
  const router = useRouter();
  const { data: c, error, loading, reload } = useAsync(() => getConfirmation(id), [id]);
  const [busy, setBusy] = useState<'approve' | 'decline' | null>(null);
  const inFlight = useRef(false);
  const [err, setErr] = useState<{ title: string; body: string; reload?: boolean } | null>(null);
  const [declined, setDeclined] = useState(false);
  const [placed, setPlaced] = useState(false);
  const [askDecline, setAskDecline] = useState(false);

  if (loading && !c) return <ConfirmSkeleton />;
  if (error || !c) return <ErrorState error={error} onRetry={reload} title="Could not load the cart" />;

  const gate = c.gate_report || { action: 'place_order', verdict: 'CONFIRM', results: [] };
  const denied = gate.results.filter((r) => r.verdict === 'DENY');
  const open = c.status === 'requested' && !declined && !placed;
  const budget = c.cart.budget_paise || 0;
  const opening = c.cart.opening_cost_paise ?? (c.cart.total_paise + (c.cart.savings_paise || 0));

  async function answer(approved: boolean) {
    if (inFlight.current) return; // double-submit guard
    inFlight.current = true;
    setBusy(approved ? 'approve' : 'decline'); setErr(null);
    try {
      rememberNegotiation(c!.negotiation_id);
      const r = await answerConfirmation(id, approved);
      if (!approved) { setDeclined(true); return; }
      if (r.order_ids?.length) { setPlaced(true); router.push(`/pay/${encodeURIComponent(r.order_ids[0])}${r.order_ids.length > 1 ? `?more=${r.order_ids.length - 1}` : ''}`); return; }
      const reasons = (r as { reasons?: string[] }).reasons || [];
      setErr({ title: 'Not ordered: a safety check failed at approval.', body: reasons.length ? reasons.map((x) => reasonText(x)).join('. ') : `Sauda returned “${r.status}” without an order.`, reload: true });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.code === 'cart_changed') {
        reload();
        setErr({ title: 'The offer changed; review again.', body: 'Sauda reloaded the cart with the latest prices. Nothing was ordered.' });
      } else if (e instanceof ApiError && e.status === 409 && e.code === 'already_answered') {
        setErr({ title: 'You already answered this cart.', body: 'It was decided earlier (perhaps on another device). Reload to see where it stands. Nothing new was ordered.', reload: true });
      } else if (e instanceof ApiError && e.status === 409 && /^negotiation/.test(e.code)) {
        setErr({ title: 'This restock is no longer waiting for approval.', body: `${e.message}. Nothing new was ordered.`, reload: true });
      } else if (e instanceof ApiError && (e.status === 409 || e.status === 410)) {
        setErr({ title: e.status === 410 ? 'This cart expired.' : 'This cart cannot be approved any more.', body: `${e.message}. Reload to see its current state. Nothing new was ordered.`, reload: true });
      } else setErr({ title: 'Could not send your answer.', body: e instanceof Error ? e.message : String(e) });
    } finally { setBusy(null); inFlight.current = false; }
  }

  const over = budget > 0 && c.cart.total_paise > budget;
  const failedN = denied.length;
  const summary = (
    <section className="rf-total" aria-label="Order total">
      <span className="small muted">Order total</span>
      <Money paise={c.cart.total_paise} size="xl" />
      {budget > 0 && (
        <div className="rf-budgetbar">
          <Meter value={c.cart.total_paise} max={budget} label="Budget used" />
          <div className="row">
            <span>{Math.min(999, Math.round((c.cart.total_paise / budget) * 100))}% of {rupees(budget, true)} budget</span>
            <span style={over ? { color: 'var(--bad)' } : undefined}>{over ? `${rupees(c.cart.total_paise - budget, true)} over` : `${rupees(budget - c.cart.total_paise, true)} left`}</span>
          </div>
        </div>
      )}
      {c.cart.savings_paise > 0 && (
        <span className="rf-save" title={`Opening quotes totalled ${rupees(opening)} for the same items (partner supplier agents).`}>
          <Icon name="check" size={14} />
          <span><b style={{ fontWeight: 600 }}><Money paise={c.cart.savings_paise} whole /></b> below opening quotes{typeof c.cart.savings_pct === 'number' ? ` (${c.cart.savings_pct}%)` : ''}</span>
        </span>
      )}
      {c.expires_at && open && <span className="small muted">Decide by {ist(c.expires_at)}</span>}
    </section>
  );

  return (
    <div className="stack lg">
      {c.status === 'approved' && !placed && <Callout tone="ok" title="Already approved.">See your orders for payment.</Callout>}
      {c.status === 'declined' && !declined && <Callout tone="neutral" title="You declined this cart.">Nothing was ordered.</Callout>}
      {c.status === 'expired' && <Callout tone="warn" title="This cart expired.">Start a new restock to get fresh quotes.</Callout>}
      {summary}
      <div className="stack lg">
          {c.cart.blocked_suppliers?.map((b) => (
            <div key={b.supplier_id} className="rf-blocked" role="note">
              <span><b>{supplierName(b.supplier_id)} was blocked</b> and is not in this cart.</span>
              <span className="muted">{b.reason_codes.map((r) => reasonText(r, { supplier: supplierName(b.supplier_id) })).join('. ')}.</span>
            </div>
          ))}
          {c.cart.dropped_lines?.length ? (
            <Callout tone="warn" title="Left out:">{c.cart.dropped_lines.map((d) => `${d.name} (${d.reason})`).join('; ')}.</Callout>
          ) : null}
          {c.cart.allocations.map((a) => <SupplierBlock key={a.supplier_id} a={a} why={c.cart.why} />)}
          <GateReport report={gate} title="Safety checks" />
      </div>
      <p className="xs muted">{SETTLEMENT_CAPTION}</p>

      {err && (
        <div className="stack sm">
          <Callout tone="bad" title={err.title}>{err.body}</Callout>
          {err.reload && <Button variant="secondary" icon="refresh" onClick={() => { setErr(null); reload(); }}>Reload cart</Button>}
        </div>
      )}
      {declined && (
        <div className="stack">
          <Callout tone="neutral" title="Declined.">Nothing was ordered. Your limits stay active, so you can run the negotiation again.</Callout>
          <ButtonLink href="/dashboard" variant="secondary">Back to dashboard</ButtonLink>
        </div>
      )}
      {open && failedN > 0 && <Callout tone="bad">A safety check failed, so this cart cannot be approved. Decline it and start again.</Callout>}
      {open && (
        <div className="rf-decide" role="group" aria-label="Your decision">
          {askDecline ? (
            <div className="rf-decline-ask" role="alertdialog" aria-labelledby="decline-q">
              <span id="decline-q" className="small" style={{ color: 'var(--ink)' }}><b>Decline this cart?</b> Nothing will be ordered. Your limits stay active.</span>
              <div className="row">
                <Button variant="secondary" disabled={!!busy} onClick={() => setAskDecline(false)}>Keep it</Button>
                <Button variant="danger" busy={busy === 'decline'} busyLabel="Declining…" disabled={!!busy} onClick={() => answer(false)}>Yes, decline</Button>
              </div>
            </div>
          ) : (
            <>
              <Button block busy={busy === 'approve'} busyLabel="Placing order…" disabled={!!busy || failedN > 0} onClick={() => answer(true)}>
                Approve {rupees(c.cart.total_paise, true)}
              </Button>
              <div className="rf-or">
                <Button variant="text" style={{ minHeight: 44 }} disabled={!!busy} onClick={() => setAskDecline(true)}>Decline cart</Button>
              </div>
            </>
          )}
        </div>
      )}
      <Evidence>
        <span>Confirmation <span className="code">{c.confirmation_id}</span> · cart <span className="code">{c.cart_draft_id}</span> · negotiation <span className="code">{c.negotiation_id}</span></span>
      </Evidence>
    </div>
  );
}
