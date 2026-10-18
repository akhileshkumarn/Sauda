'use client';
import { getMetrics } from '@/lib/api';
import { rupees } from '@/lib/format';
import { useAsync } from '@/lib/useAsync';
import { ButtonLink, Callout, Card, EmptyState, ErrorState, Evidence, Money, PLAN_B, Skeleton, SUPPLIER_DISCLOSURE } from './ui';

function pct(v: number) {
  const p = v <= 1 ? v * 100 : v;
  return `${Math.round(p * 10) / 10}%`;
}

function duration(min: number) {
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.floor(min / 60); const m = Math.round(min % 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function MetricCards({ shopId }: { shopId: string }) {
  const { data: m, error, loading, reload } = useAsync(() => getMetrics(shopId), [shopId]);
  if (loading && !m) return <div className="stack"><div className="card"><Skeleton lines={3} /></div><div className="tiles">{[0, 1, 2, 3].map((i) => <div key={i} className="tile"><Skeleton lines={2} /></div>)}</div></div>;
  if (error || !m) return <ErrorState error={error} onRetry={reload} title="Could not load savings" />;
  const saved = m.rupees_saved || 0;
  const p = m.savings_pct || 0;
  const exactOpening = (m as { opening_cost_paise?: number }).opening_cost_paise;
  const exact = typeof exactOpening === 'number' && exactOpening > 0;
  const opening = exact ? exactOpening : p > 0 ? Math.round((saved * 100) / p) : 0;
  const paid = opening - saved;
  if (!saved && !m.orders) {
    return (
      <EmptyState icon="chart" title="No savings yet" action={<ButtonLink href="/restock" icon="plus">New restock</ButtonLink>}>
        Savings appear after a restock is negotiated and confirmed. They are measured against the suppliers’ opening quotes.
      </EmptyState>
    );
  }
  const tiles: { label: string; value: string; sub: string }[] = [
    { label: 'Price-cap compliance', value: pct(m.ceiling_compliance), sub: 'lines at or below MRP or mandi price × 1.10' },
  ];
  if (m.orders != null) tiles.push({ label: 'Orders', value: String(m.orders), sub: `confirmed ${m.orders === 1 ? 'restock' : 'restocks'} for this shop` });
  tiles.push({ label: 'Attacks stopped', value: String(m.attacks_blocked), sub: m.supplier_messages_blocked != null ? `${m.supplier_messages_blocked} from suppliers, ${m.attack_box_blocked ?? 0} from tests` : 'by screening and policy checks' });

  return (
    <div className="stack lg">
      <section className="save-hero" aria-labelledby="save-h">
        <h1 id="save-h" className="sr-only">Savings</h1>
        <span className="small muted">Saved with Sauda</span>
        <Money paise={saved} size="xl" />
        <p className="muted" style={{ maxWidth: '52ch' }}>That is {pct(p)} below the prices suppliers first quoted, after Sauda negotiated inside your limits{m.orders != null ? ` across ${m.orders} confirmed ${m.orders === 1 ? 'restock' : 'restocks'}` : ''}.</p>
      </section>

      <div className="tiles tiles-3">
        {tiles.map((t) => <div key={t.label} className="tile"><span className="label">{t.label}</span><span className="value">{t.value}</span><span className="sub">{t.sub}</span></div>)}
      </div>

      <Card title="How this is calculated">
        <div className="stack">
          <dl className="kv">
            <dt>Opening quotes for the same items</dt><dd className="num">{opening ? `${exact ? '' : '≈ '}${rupees(opening)}` : '—'}</dd>
            <dt>Price after Sauda negotiated</dt><dd className="num">{opening ? `${exact ? '' : '≈ '}${rupees(paid)}` : '—'}</dd>
            <dt className="strong" style={{ color: 'var(--ink)' }}>Difference</dt><dd className="num" style={{ color: 'var(--ok)' }}>{rupees(saved)} ({pct(p)})</dd>
          </dl>
          {!exact && opening > 0 && <p className="xs faint">≈ derived from the saved amount and percentage.</p>}
          <p className="xs muted">Baseline: each supplier’s first quote (round 1) for the lines it won. {m.baseline_label ? `${m.baseline_label}.` : 'Not compared with your past bills, because this shop has no purchase history in Sauda.'}</p>
          {m.realised_savings_paise != null && (
            <p className="xs muted">Counting only orders that were placed and not cancelled: <b className="num">{rupees(m.realised_savings_paise)}</b>{m.realised_savings_pct != null ? ` (${pct(m.realised_savings_pct)})` : ''}.</p>
          )}
          <p className="xs muted">Phone time saved (estimate): <b className="num">{duration(m.time_saved_min)}</b>{m.time_saved_assumption_min_per_call ? `, assuming ${m.time_saved_assumption_min_per_call} min per supplier exchange` : ''}.</p>
        </div>
      </Card>

      <Evidence label="About the suppliers and data"><span>{SUPPLIER_DISCLOSURE} These figures describe this shop only; they are not a market-wide or return-on-investment claim.</span><span>{PLAN_B}</span></Evidence>
      <Evidence label="Technical details">
        <span>GET /metrics/{shopId}{m.last_negotiation_id ? <> · last negotiation <span className="code">{m.last_negotiation_id}</span></> : null}</span>
        <pre className="json">{JSON.stringify(m, null, 2)}</pre>
      </Evidence>
    </div>
  );
}
