'use client';
import Link from 'next/link';
import { getEvents, getMetrics, getOverview } from '@/lib/api';
import { ist, rupees, supplierName } from '@/lib/format';
import { useAsync } from '@/lib/useAsync';
import type { LedgerEvent, Metrics, OverviewOrder } from '@/lib/types';
import { orderStatus } from './status';
import { TrustIntro, TrustLinks } from './TrustIntro';
import { ButtonLink, Callout, EmptyState, ErrorState, Evidence, Icon, Money, PLAN_B, Skeleton, Stat, StatusPill, SUPPLIER_DISCLOSURE } from './ui';

function pct(v: number) {
  const p = v <= 1 ? v * 100 : v;
  return `${Math.round(p * 10) / 10}%`;
}

function duration(min: number) {
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.floor(min / 60); const m = Math.round(min % 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

function Intro() {
  return (
    <TrustIntro eyebrow="Trust · Savings" title="Savings"
      lede="How much less this shop paid than suppliers first asked, after Sauda negotiated inside your limits. It tells you, in rupees from your own restocks, whether letting Sauda negotiate is worth it."
      guide={{
        looking: 'The amount saved, split into realised (orders placed and not cancelled) and projected (carts not ordered yet), the calculation behind it, and a breakdown per restock where the record carries a figure.',
        obtained: 'Opening quote = each supplier’s first quote (round 1) for the lines it won. Saving = opening quote minus the final negotiated price. Sauda’s server computes this from the signed record of each restock.',
        act: 'Open a restock’s signed record to see every step, or approve and pay a waiting cart so its projected saving becomes realised.',
        ignore: 'Nothing changes. These figures are for your information; they describe this shop only and are not a return-on-investment claim.',
      }} />
  );
}

export function MetricCards({ shopId }: { shopId: string }) {
  const { data: m, error, loading, reload } = useAsync(() => getMetrics(shopId), [shopId]);
  if (loading && !m) return (
    <div className="stack lg">
      <Intro />
      <div className="stack" aria-busy="true" aria-label="Loading savings"><Skeleton lines={2} /><div className="tiles">{[0, 1, 2, 3].map((i) => <div key={i} className="tile"><Skeleton lines={2} /></div>)}</div></div>
    </div>
  );
  if (error || !m) return <div className="stack lg"><Intro /><ErrorState error={error} onRetry={reload} title="Could not load savings" /></div>;
  const saved = m.rupees_saved || 0;
  if (!saved && !m.orders) {
    return (
      <div className="stack lg">
        <Intro />
        <EmptyState icon="chart" title="No savings yet" action={<ButtonLink href="/restock" icon="plus">Start a restock</ButtonLink>}>
          Savings appear after Sauda negotiates a restock. They are measured against the suppliers’ opening quotes, and count as realised once the order is placed.
        </EmptyState>
        <TrustLinks current="savings" />
      </div>
    );
  }
  return <Savings m={m} shopId={shopId} />;
}

function Savings({ m, shopId }: { m: Metrics; shopId: string }) {
  const saved = m.rupees_saved || 0;
  const p = m.savings_pct || 0;
  const exactOpening = (m as { opening_cost_paise?: number }).opening_cost_paise;
  const exact = typeof exactOpening === 'number' && exactOpening > 0;
  const opening = exact ? exactOpening : p > 0 ? Math.round((saved * 100) / p) : 0;
  const paid = opening - saved;
  const hasRealised = typeof m.realised_savings_paise === 'number';
  const realised = hasRealised ? m.realised_savings_paise! : null;
  const projected = realised != null ? Math.max(0, saved - realised) : null;

  const tiles: { label: string; value: string; sub: string }[] = [
    { label: 'Price-cap compliance', value: pct(m.ceiling_compliance), sub: 'lines at or below MRP or mandi price × 1.10' },
  ];
  if (m.orders != null) tiles.push({ label: 'Orders', value: String(m.orders), sub: `confirmed ${m.orders === 1 ? 'restock' : 'restocks'} for this shop` });
  tiles.push({ label: 'Messages blocked', value: String(m.attacks_blocked), sub: m.supplier_messages_blocked != null ? `${m.supplier_messages_blocked} from suppliers, ${m.attack_box_blocked ?? 0} from security tests` : 'by screening and policy checks, including security tests' });

  return (
    <div className="stack lg">
      <Intro />

      <section className="tz-save" aria-labelledby="save-h">
        <h2 id="save-h" className="sr-only">Amount saved</h2>
        <div className="tz-save-main">
          <span className="small muted">{realised != null ? 'Realised savings: orders placed, not cancelled' : 'Negotiated savings'}</span>
          <Money paise={realised ?? saved} size="xl" tone="save" />
          <p className="muted">
            {realised != null
              ? <>{m.realised_savings_pct != null ? `${pct(m.realised_savings_pct)} ` : ''}below the suppliers’ opening quotes{m.realised_basis ? `, ${m.realised_basis}` : ''}.</>
              : <>{pct(p)} below the suppliers’ opening quotes{m.orders != null ? `, across ${m.orders} confirmed ${m.orders === 1 ? 'restock' : 'restocks'}` : ''}.</>}
          </p>
        </div>
        <dl className="tz-split">
          <div><dt><StatusPill tone="ok">Realised</StatusPill></dt><dd>{realised != null ? <Money paise={realised} /> : <span className="muted small">Not reported</span>}</dd><dd className="xs muted">Orders placed and not cancelled.</dd></div>
          <div><dt><StatusPill tone="neutral">Projected</StatusPill></dt><dd>{projected != null ? <Money paise={projected} /> : <span className="muted small">Not reported</span>}</dd><dd className="xs muted">Negotiated on carts that were not ordered, or were cancelled. Not money saved yet.</dd></div>
        </dl>
        {realised == null && <Callout tone="neutral" title="Realised and projected are not separated here.">The server did not say which part of {rupees(saved)} came from orders actually placed, so this figure may include carts that were never ordered.</Callout>}
      </section>

      <section className="stack sm" aria-labelledby="calc-h">
        <div className="section-h" style={{ marginBottom: 0 }}><h2 id="calc-h">How this is calculated</h2></div>
        <div className="tz-calc">
          <div><span className="k">Opening quotes for the same items</span><span className="v num">{opening ? `${exact ? '' : '≈ '}${rupees(opening)}` : '—'}</span></div>
          <div className="op" aria-hidden>−</div>
          <div><span className="k">Price after Sauda negotiated</span><span className="v num">{opening ? `${exact ? '' : '≈ '}${rupees(paid)}` : '—'}</span></div>
          <div className="op" aria-hidden>=</div>
          <div className="res"><span className="k">Difference</span><span className="v num">{rupees(saved)} <span className="small">({pct(p)})</span></span></div>
        </div>
        {!exact && opening > 0 && <p className="xs muted">≈ The server reports the saving and the percentage; the two prices above are worked back from those and may be off by a few paise.</p>}
        <p className="xs muted">Baseline: each supplier’s first quote (round 1) for the lines it won. {m.baseline_label ? `${m.baseline_label}.` : 'Not compared with your past bills, because this shop has no purchase history in Sauda.'}</p>
      </section>

      <Breakdown />

      <div className="tiles tiles-3">
        {tiles.map((t) => <Stat key={t.label} label={t.label} value={t.value} basis={t.sub} />)}
      </div>
      <p className="xs muted">Phone time saved (estimate): <b className="num">{duration(m.time_saved_min)}</b>{m.time_saved_assumption_min_per_call ? `, assuming ${m.time_saved_assumption_min_per_call} min per supplier exchange` : ''}. An estimate, not a measurement.</p>

      <Evidence label="About the suppliers and data"><span>{SUPPLIER_DISCLOSURE} These figures describe this shop only; they are not a market-wide or return-on-investment claim.</span><span>{PLAN_B}</span></Evidence>
      <Evidence label="Technical details">
        <span>GET /metrics/{shopId}{m.last_negotiation_id ? <> · last negotiation <span className="code">{m.last_negotiation_id}</span></> : null}</span>
        <pre className="json">{JSON.stringify(m, null, 2)}</pre>
      </Evidence>
      <TrustLinks current="savings" nid={m.last_negotiation_id || undefined} />
    </div>
  );
}

// ---------------------------------------------------------------- per-restock breakdown
// Built from recent orders grouped by negotiation, with the saving read from that negotiation's own signed
// "cart.assembled" event. A restock whose record carries no figure says so instead of guessing.
interface Row { nid: string; orders: OverviewOrder[]; total: number | null; saving: number | null; live: boolean; when: string }

async function loadBreakdown(): Promise<Row[]> {
  const ov = await getOverview();
  const by = new Map<string, OverviewOrder[]>();
  for (const o of ov.recent_orders || []) { if (!o.negotiation_id) continue; if (!by.has(o.negotiation_id)) by.set(o.negotiation_id, []); by.get(o.negotiation_id)!.push(o); }
  const rows = await Promise.all([...by.entries()].map(async ([nid, orders]) => {
    let evs: LedgerEvent[] = [];
    try { evs = await getEvents(nid); } catch { evs = []; }
    const cart = [...evs].reverse().find((e) => e.type === 'cart.assembled' && e.negotiation_id === nid);
    const n = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
    const live = orders.some((o) => String(o.status).toLowerCase() !== 'cancelled');
    const when = orders.map((o) => o.created_at).sort().reverse()[0] || '';
    return { nid, orders, total: cart ? n(cart.payload.total_paise) : null, saving: cart ? n(cart.payload.savings_paise) : null, live, when };
  }));
  return rows.sort((a, b) => (a.when < b.when ? 1 : -1));
}

function Breakdown() {
  const { data, error, loading, reload } = useAsync(() => loadBreakdown(), []);
  return (
    <section className="stack sm" aria-labelledby="bd-h">
      <div className="section-h" style={{ marginBottom: 0 }}><h2 id="bd-h">By restock</h2><Link href="/orders">All orders</Link></div>
      {loading && !data && <div aria-busy="true" aria-label="Loading restocks"><Skeleton lines={3} /></div>}
      {error && !data ? ([401, 403].includes((error as { status?: number }).status ?? 0)
        ? <p className="small muted">Sign in as the shop owner to see savings per restock.</p>
        : <ErrorState error={error} onRetry={reload} title="Could not load the per-restock breakdown" />) : null}
      {data && data.length === 0 && <p className="small muted">No orders yet, so there is nothing to break down. Savings on a cart count once it is ordered.</p>}
      {data && data.length > 0 && (
        <ul className="tz-bd">
          {data.map((r) => (
            <li key={r.nid}>
              <div className="tz-bd-top">
                <span className="stack xs" style={{ gap: 2, minWidth: 0 }}>
                  <b className="break">{r.orders.map((o) => supplierName(o.supplier_id, o.supplier_name || undefined)).filter((v, i, a) => a.indexOf(v) === i).join(', ')}</b>
                  <span className="xs muted">{r.when ? ist(r.when) : ''} · {r.orders.length} {r.orders.length === 1 ? 'order' : 'orders'}</span>
                </span>
                <span className="tz-bd-amt">
                  {r.saving != null ? <><Money paise={r.saving} tone="save" /><StatusPill tone={r.live ? 'ok' : 'neutral'}>{r.live ? 'Realised' : 'Not realised (cancelled)'}</StatusPill></> : <span className="small muted">No saving in its record</span>}
                </span>
              </div>
              <div className="tz-bd-links">
                {r.orders.map((o) => <Link key={o.order_id} href={`/pay/${encodeURIComponent(o.order_id)}`}>{supplierName(o.supplier_id, o.supplier_name || undefined)} · {orderStatus(o).label}<Icon name="chev" size={12} /></Link>)}
                <Link href={`/trust/${encodeURIComponent(r.nid)}`}>Signed record<Icon name="chev" size={12} /></Link>
              </div>
              {r.total != null && r.saving != null && <span className="xs muted">Final cart {rupees(r.total)} against opening quotes of {rupees(r.total + r.saving)}.</span>}
            </li>
          ))}
        </ul>
      )}
      <p className="xs muted">Only recent orders are listed. A saving shows only when that restock’s signed record carries it.</p>
    </section>
  );
}
