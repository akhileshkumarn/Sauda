'use client';
import Link from 'next/link';
import { QRCodeSVG } from 'qrcode.react';
import { useRef, useState } from 'react';
import { getOrder, SHOP_ID, submitPaymentProof } from '@/lib/api';
import { ist, maskVpa, paiseToRupeeString, paymentState, reasonText, rupees, supplierName } from '@/lib/format';
import { lastNegotiationId } from '@/lib/session';
import { useAsync } from '@/lib/useAsync';
import type { Order } from '@/lib/types';
import { poAckStatus } from './status';
import { Button, ButtonLink, Callout, Card, ErrorState, Evidence, Icon, Money, SETTLEMENT_CAPTION, Skeleton, StatusPill, Timeline, type Step } from './ui';

export function upiLink(o: Order): string | null {
  const pm = o.payment_mandate;
  if (!pm) return null;
  if (pm.upi_link) return pm.upi_link;
  const q = new URLSearchParams({
    pa: pm.payee_vpa,
    pn: pm.payee_name || supplierName(o.supplier_id, o.supplier_name),
    am: paiseToRupeeString(pm.amount_paise),
    cu: 'INR',
    tn: `Sauda ${o.order_id}`,
  });
  return `upi://pay?${q.toString().replace(/\+/g, '%20')}`;
}

export function PayView({ orderId, more = 0 }: { orderId: string; more?: number }) {
  const { data: o, error, loading, reload, setData } = useAsync(() => getOrder(orderId), [orderId]);
  const [utr, setUtr] = useState('');
  const [amt, setAmt] = useState(''); // what the owner actually paid, typed by them (never prefilled)
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  if (loading && !o) return <Skeleton lines={7} />;
  if (error || !o) return <ErrorState error={error} onRetry={reload} title="Could not load this order" />;

  const pm = o.payment_mandate || null;
  const link = upiLink(o);
  const pay = paymentState(o.payment_status || pm?.status || (o.status === 'settled' ? 'settled' : null));
  const cancelled = String(o.status) === 'cancelled' || pay === 'cancelled';
  const ack = poAckStatus(o.po_status || o.po_ack);
  const ackOk = !!ack && /accept|ok|ack|received|confirm/.test(ack);
  const ackBad = !!o.po_error || (!!ack && /reject|declin/.test(ack));
  const name = supplierName(o.supplier_id, o.supplier_name);
  const demo = !!pm && (!!o.demo_amount || !!pm.demo_amount || pm.amount_paise !== o.total_paise);
  const orderTotal = o.order_total_paise ?? pm?.order_total_paise ?? o.total_paise;
  const noPayment = !pm && !cancelled && !ackOk;
  const nid = o.negotiation_id || lastNegotiationId();
  const paidPaise = Math.round(parseFloat(amt || '0') * 100);

  const steps: Step[] = [
    { key: 'po', title: 'Purchase order sent', state: 'done', body: <>To {name}{o.created_at ? ` · ${ist(o.created_at)}` : ''}</> },
    { key: 'ack', title: 'Supplier accepted', state: ackOk ? 'done' : ackBad ? 'bad' : 'current',
      body: ackOk ? `${name} confirmed the purchase order.` : ackBad ? `${name} did not confirm the order${o.po_error ? ' (could not be reached)' : ''}. Call them before paying.` : 'Waiting for the supplier to confirm.' },
    { key: 'link', title: 'Payment link issued', state: pm ? 'done' : cancelled || noPayment ? 'na' : 'current',
      body: pm ? <>UPI request for <Money paise={pm.amount_paise} /> to {pm.payee_name || name}, payout account on record</> : noPayment ? 'No payment requested until the supplier accepts the order.' : 'Preparing the UPI link.' },
    { key: 'paid', title: 'You reported payment', state: pay === 'claimed' ? 'done' : pay === 'mismatch' ? 'bad' : pm && !cancelled ? 'current' : 'todo',
      meta: pay === 'claimed' ? <StatusPill tone="neutral">Not bank-verified</StatusPill> : undefined,
      body: pay === 'claimed' ? <>Claimed by you with UTR <span className="mono">{o.utr || '—'}</span>. Sauda has not verified this payment with the bank.</>
        : pay === 'mismatch' ? 'Your report did not match this payment request. This is final for this order: call the supplier to sort it out.'
        : 'After paying in your UPI app, enter the 12-digit UTR below.' },
    { key: 'del', title: 'Delivery', state: 'na', body: 'Not tracked in this build. Check with the supplier.' },
  ];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (inFlight.current || !pm) return;
    inFlight.current = true; setBusy(true); setResult(null);
    try {
      const r = await submitPaymentProof(orderId, { utr: utr.trim(), amount_paise: paidPaise });
      if (r.status === 'claimed') {
        setResult({ ok: true, text: `Recorded as claimed: you reported paying ${rupees(paidPaise)} with UTR ${r.utr || utr}. Sauda has not verified this with the bank.` });
        setData({ ...o!, payment_status: 'claimed', utr: r.utr || utr, payment_mandate: { ...pm, status: 'claimed' } });
      } else if (r.status === 'invalid') {
        setResult({ ok: false, text: r.problems?.length ? r.problems.map((x) => reasonText(x.toUpperCase())).join('. ') : r.reason || 'That does not look like a UTR. It is the 12-digit number in your UPI app.' });
      } else {
        setResult({ ok: false, text: `Not recorded: ${r.problems?.length ? r.problems.map((x) => reasonText(x === 'payee_mismatch' ? 'PAYEE_MISMATCH_PROOF' : x.toUpperCase())).join('. ') : (r.reason || r.status).replace(/_/g, ' ')}. A mismatch is final for this order; call the supplier.` });
        setData({ ...o!, payment_status: 'mismatch' });
      }
    } catch (err) { setResult({ ok: false, text: err instanceof Error ? err.message : String(err) }); }
    finally { setBusy(false); inFlight.current = false; }
  }

  return (
    <div className="stack lg">
      {more > 0 && <Callout tone="info">This restock created {more + 1} orders, one per supplier. <Link href="/orders">See all orders</Link> to pay each one.</Callout>}
      <div className="row between top">
        <div className="stack xs grow"><span className="row sm"><span className="strong break" style={{ fontSize: 17 }}>{name}</span><span className="tag">Simulated</span></span><span className="small muted">Order total</span></div>
        <Money paise={o.total_paise} size="lg" className="none" />
      </div>

      {cancelled && <Callout tone="neutral" title="Cancelled.">This order was cancelled. Do not pay it.</Callout>}

      {noPayment && <Callout tone="warn" icon="clock" title="Supplier hasn’t accepted the order; no payment requested.">Do not pay yet. Sauda asks for payment only after the supplier accepts the purchase order.</Callout>}

      {pm && pay !== 'claimed' && pay !== 'mismatch' && !cancelled && (
        <section aria-label="Pay by UPI">
          <div className="stack lg" style={{ alignItems: 'center', paddingTop: 8 }}>
                        <div className="stack xs center"><span className="small muted">{demo ? 'Test payment' : 'Amount to pay'}</span><Money paise={pm.amount_paise} size="xl" />
              {demo && <span className="small muted">Order total {rupees(orderTotal)}</span>}
              <span className="small muted">Paid to <span className="mono" style={{ fontSize: 13 }}>{maskVpa(pm.payee_vpa, pm.payout_vpa_masked || pm.payee_vpa_masked || o.payout_vpa_masked)}</span></span></div>
            {link && <div className="qr" aria-label="UPI QR code"><QRCodeSVG value={link} size={196} level="M" marginSize={0} /></div>}
            {link && <a className="btn block" href={link}>Open UPI app</a>}
            <span className="xs faint center">{SETTLEMENT_CAPTION}{demo ? ' Token test amount to a team member’s account on record.' : ''}</span>
          </div>
        </section>
      )}

      {pm && pay !== 'claimed' && pay !== 'mismatch' && !cancelled && (
        <form className="stack" onSubmit={submit} aria-labelledby="utr-h" style={{ borderTop: '1px solid var(--line)', paddingTop: 20 }}>
          <div className="stack xs">
            <h2 id="utr-h">Paid? Enter the UTR</h2>
            <p className="small muted">From your UPI app. Recorded as your claim; not bank-verified.</p>
          </div>
          <label className="field" htmlFor="paid-amt">Amount you paid
            <div className="input-affix"><span aria-hidden>₹</span>
              <input id="paid-amt" className="input num" inputMode="decimal" autoComplete="off" placeholder="as shown in your UPI app" value={amt}
                onChange={(e) => setAmt(e.target.value.replace(/[^\d.]/g, '').replace(/(\..*)\./g, '$1').slice(0, 10))} />
            </div>
          </label>
          <label className="field" htmlFor="utr">UTR (UPI reference)</label>
          <input id="utr" className="input mono" inputMode="numeric" autoComplete="off" placeholder="12 digits, e.g. 428917365012" value={utr}
            onChange={(e) => setUtr(e.target.value.replace(/\D/g, '').slice(0, 12))} aria-invalid={utr.length > 0 && utr.length !== 12} />
          <Button block type="submit" variant="secondary" busy={busy} busyLabel="Checking…" disabled={!/^\d{12}$/.test(utr) || !(paidPaise > 0)}>Record my payment</Button>
        </form>
      )}
      {result && <Callout tone={result.ok ? 'ok' : 'bad'}>{result.text}</Callout>}

      <Card title="Progress">
        <Timeline steps={steps} label="Order progress" />
      </Card>

      <div className="row wrap">
        <Link className="small muted" href={`/savings/${SHOP_ID}`}>Savings</Link>
        {nid ? <Link className="small muted" href={`/trust/${encodeURIComponent(nid)}`}>Signed record</Link> : <Link className="small muted" href="/orders">All orders</Link>}
      </div>

      <Evidence>
        <span>Order <span className="code">{o.order_id}</span></span>
        {pm && <span>Payment mandate <span className="code">{pm.mandate_id}</span>{pm.body_hash ? <> · body hash <span className="code">{pm.body_hash.slice(0, 16)}…</span></> : null}</span>}
        {pm?.cooling_off_until && <span>Cooling-off until {ist(pm.cooling_off_until)}</span>}
        <span>Supplier acknowledgement: <span className="code">{ack || 'none'}</span>{o.po_error ? <> · error <span className="code">{o.po_error.slice(0, 120)}</span></> : null}</span>
        <span>Payment status (stored): <span className="code">{String(o.payment_status ?? pm?.status ?? '—')}</span>{String(o.payment_status) === 'settled' ? ' (legacy value, shown as “claimed”)' : ''}</span>
      </Evidence>
    </div>
  );
}
