'use client';
import Link from 'next/link';
import { useRef, useState } from 'react';
import { ApiError, getMetrics, getOverview, listSessions, setKillSwitch, SHOP_ID } from '@/lib/api';
import { paymentState, relTime, supplierName } from '@/lib/format';
import { categoryWord, myBusinesses, pickBusiness } from '@/lib/network';
import { useAsync } from '@/lib/useAsync';
import type { Metrics, Overview, OverviewOrder, SessionSummary } from '@/lib/types';
import { NewRestockButton } from './restock/SessionList';
import { negotiationLabel, orderStatus, sessionLabel } from './status';
import { Button, Callout, ErrorState, Icon, Money, PageHead, SectionHead, Skeleton, StatusPill, type IconName, type Tone } from './ui';
import { Sheet } from './ui-client';

/**
 * Home answers one question: what should I do next?
 * Everything here comes from the overview, sessions, metrics and network APIs. Nothing is invented:
 * a block with no data shows an empty state instead of a number.
 */
export function HomeView() {
  const { data, error, loading, reload } = useAsync(() => getOverview(), []);
  const ss = useAsync(() => listSessions({ limit: 20 }).catch(() => [] as SessionSummary[]), []);
  return (
    <div className="home">
      <PageHead size="display" title={data?.shop?.name || (loading ? ' ' : 'Your shop')}
        description="Restock inside limits you sign. Nothing is bought until you approve."
        action={<div className="home-new"><NewRestockButton /></div>} />
      <p className="home-sample"><span className="dot neutral" aria-hidden />Sample shop · real products and prices · suppliers are simulated</p>

      {loading && !data && <div className="home-skel"><Skeleton lines={2} block /><Skeleton lines={4} /></div>}
      {error && !data ? <ErrorState error={error} onRetry={reload} title="Could not load your shop" /> : null}
      {data && <Body o={data} sessions={ss.data || []} />}
    </div>
  );
}

type Todo = { key: string; href: string; icon: IconName; title: string; meta: string; tone: Tone; label: string; money?: number | null };

function Body({ o, sessions }: { o: Overview; sessions: SessionSummary[] }) {
  const resume = sessions.find((x) => x.resumable && x.status !== 'cancelled' && x.status !== 'awaiting_approval');
  const all = waitingOnYou(o, sessions);
  const lead = all[0] && all[0].tone === 'warn' ? all[0] : null;
  const todos = lead ? all.slice(1) : all; // the lead item is already the Next step panel
  return (
    <>
      <NextUp o={o} resume={resume || null} first={lead} />
      <div className="home-grid">
        <div className="home-main">
          <section aria-labelledby="h-wait">
            <SectionHead title={<span id="h-wait">Waiting on you</span>} />
            {todos.length ? (
              <ul className="list plain">
                {todos.map((t) => (
                  <li key={t.key}>
                    <Link href={t.href} className="rowlink todo">
                      <span className={`todo-ico ${t.tone}`} aria-hidden><Icon name={t.icon} size={16} /></span>
                      <div className="grow stack xs">
                        <span className="strong break">{t.title}</span>
                        <span className="small muted row sm wrap" style={{ rowGap: 0 }}><StatusPill tone={t.tone}>{t.label}</StatusPill>{t.meta && <span className="num">{t.meta}</span>}</span>
                      </div>
                      {t.money ? <Money paise={t.money} whole className="strong none" /> : null}
                      <span className="chev-ico"><Icon name="chev" size={16} /></span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="home-empty"><Icon name="check" size={16} />{lead ? 'Nothing else needs your approval or payment.' : 'Nothing needs your approval or payment right now.'}</p>
            )}
          </section>
          <RecentOrders orders={o.recent_orders} />
        </div>
        <aside className="home-side" aria-label="Shop health">
          <SavingsBlock />
          <VerifyBlock />
          <section aria-labelledby="h-safety">
            <SectionHead title={<span id="h-safety">Safety</span>} />
            <PauseCard initial={o.shop?.kill_switch ?? null} />
          </section>
        </aside>
      </div>
      <p className="home-how"><Icon name="lock" size={14} />You list it · you sign limits · Sauda negotiates · you approve and pay by UPI.</p>
    </>
  );
}

/** Things only the owner can move forward: an approval, limits to sign, a payment to make. */
function waitingOnYou(o: Overview, sessions: SessionSummary[]): Todo[] {
  const out: Todo[] = [];
  const n = o.active_negotiation;
  if (o.pending_confirmation_id) {
    out.push({ key: 'confirm', href: `/confirm/${encodeURIComponent(o.pending_confirmation_id)}`, icon: 'check', title: 'Approve your cart', tone: 'warn', label: 'Needs your approval', meta: n?.started_at ? `started ${relTime(n.started_at)}` : '' });
  }
  for (const s of sessions) {
    if (s.status === 'awaiting_approval' && !o.pending_confirmation_id) {
      out.push({ key: s.sid, href: `/restock/${encodeURIComponent(s.sid)}`, icon: 'check', title: s.title || 'Untitled restock', tone: 'warn', label: 'Needs your approval', meta: relTime(s.updated_at), money: s.total_paise ?? null });
    } else if (s.status === 'awaiting_review') {
      out.push({ key: s.sid, href: `/restock/${encodeURIComponent(s.sid)}`, icon: 'lock', title: s.title || 'Untitled restock', tone: 'info', label: 'Limits to review and sign', meta: `${s.line_count} ${s.line_count === 1 ? 'item' : 'items'}`, money: s.budget_paise ?? null });
    }
  }
  for (const r of o.recent_orders) {
    if (paymentState(r.payment_status) === 'issued') {
      out.push({ key: r.order_id, href: `/pay/${encodeURIComponent(r.order_id)}`, icon: 'upi', title: `Pay ${supplierName(r.supplier_id, r.supplier_name || undefined)}`, tone: 'warn', label: 'Waiting for your payment', meta: relTime(r.created_at), money: r.total_paise });
    }
  }
  return out.slice(0, 5);
}

/** The single most useful next step, as the one raised panel on the page. */
function NextUp({ o, resume, first }: { o: Overview; resume: SessionSummary | null; first: Todo | null }) {
  const n = o.active_negotiation;
  let href: string | null = null; let kicker = ''; let title = ''; let body = ''; let cta = ''; let tone: Tone = 'neutral'; let label = ''; let money: number | null = null;
  if (first && first.tone === 'warn') {
    href = first.href; kicker = 'Next step'; title = first.title; label = first.label; tone = first.tone; money = first.money ?? null;
    body = first.icon === 'upi' ? 'Pay from your UPI app straight to the supplier, then add the reference so it shows as claimed.' : 'Sauda negotiated inside your limits. Check the cart line by line; nothing is ordered until you approve.';
    cta = first.icon === 'upi' ? 'Open payment' : 'Review and approve';
  } else if (resume) {
    const st = sessionLabel(resume.status);
    href = `/restock/${encodeURIComponent(resume.sid)}`; kicker = 'Continue where you left off'; title = resume.title || 'Untitled restock'; tone = st.tone; label = st.label;
    money = resume.total_paise ?? resume.budget_paise ?? null;
    body = `${resume.line_count} ${resume.line_count === 1 ? 'item' : 'items'} · saved ${relTime(resume.updated_at)}`;
    cta = resume.status === 'draft' ? 'Continue the list' : 'Open restock';
  } else if (n) {
    const st = negotiationLabel(n.status, n.round);
    href = n.intent_mandate_id ? `/mandate/${encodeURIComponent(n.intent_mandate_id)}` : '/restock'; kicker = 'In progress'; title = 'Your restock'; tone = st.tone; label = st.label;
    body = n.started_at ? `Started ${relTime(n.started_at)}` : ''; cta = 'Open';
  }
  if (!href) {
    return (
      <section className="panel next-up idle" aria-labelledby="h-next">
        <div className="next-copy">
          <span className="next-k">Next step</span>
          <h2 id="h-next" className="h-section">Start a restock</h2>
          <p className="muted">Say or type it, for example “10 atta 5 kg, 20 sunflower oil, keep under ₹8,000”. You check every line before anything is signed.</p>
        </div>
        <div className="next-cta"><NewRestockButton /></div>
      </section>
    );
  }
  return (
    <section className={`panel next-up ${tone === 'warn' ? 'panel-warn' : 'panel-accent'}`} aria-labelledby="h-next">
      <div className="next-copy">
        <span className="next-k">{kicker}</span>
        <h2 id="h-next" className="h-section break">{title}</h2>
        <span className="row sm wrap small muted" style={{ rowGap: 2 }}><StatusPill tone={tone}>{label}</StatusPill>{body && kicker !== 'Next step' ? <span className="num">{body}</span> : null}</span>
        {kicker === 'Next step' && <p className="muted small">{body}</p>}
      </div>
      <div className="next-cta">
        {money ? <span className="next-money"><Money paise={money} whole size="lg" /><small>{kicker === 'Next step' ? 'total' : 'up to'}</small></span> : null}
        <Link className="btn" href={href}>{cta}<Icon name="arrow" size={18} /></Link>
      </div>
    </section>
  );
}

function RecentOrders({ orders }: { orders: OverviewOrder[] }) {
  return (
    <section aria-labelledby="h-orders">
      <SectionHead title={<span id="h-orders">Recent orders</span>} href={orders.length ? '/orders' : undefined} />
      {orders.length ? (
        <ul className="list plain">
          {orders.slice(0, 4).map((r) => {
            const st = orderStatus(r);
            return (
              <li key={r.order_id}>
                <Link href={`/pay/${encodeURIComponent(r.order_id)}`} className="rowlink">
                  <div className="grow stack xs">
                    <span className="strong ellipsis">{supplierName(r.supplier_id, r.supplier_name || undefined)}</span>
                    <span className="small muted row sm wrap" style={{ rowGap: 0 }}><StatusPill tone={st.tone}>{st.label}</StatusPill><span>{relTime(r.created_at)}</span></span>
                  </div>
                  <Money paise={r.total_paise} className="strong none" />
                  <span className="chev-ico"><Icon name="chev" size={16} /></span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="home-empty"><Icon name="box" size={16} />No orders yet. Each approved cart becomes one order per supplier.</p>
      )}
    </section>
  );
}

function savingsOf(m: Metrics): { paise: number; basis: string } | null {
  if (m.realised_savings_paise && m.realised_savings_paise > 0) {
    return { paise: m.realised_savings_paise, basis: m.realised_basis || 'on orders you approved, against the suppliers’ opening quotes' };
  }
  if (m.rupees_saved > 0) {
    const pct = m.savings_pct <= 1 ? m.savings_pct * 100 : m.savings_pct;
    const n = m.orders;
    return { paise: m.rupees_saved, basis: `${Math.round(pct * 10) / 10}% below the suppliers’ opening quotes${n != null ? `, across ${n} confirmed ${n === 1 ? 'restock' : 'restocks'}` : ''}` };
  }
  return null;
}

function SavingsBlock() {
  const q = useAsync(() => getMetrics(SHOP_ID), []);
  const s = q.data ? savingsOf(q.data) : null;
  return (
    <section aria-labelledby="h-save">
      <SectionHead title={<span id="h-save">Savings</span>} href={`/savings/${SHOP_ID}`} linkText="How it’s measured" />
      {q.loading && !q.data ? <Skeleton lines={2} /> : q.error && !q.data ? (
        <p className="home-empty"><Icon name="alert" size={16} />Savings could not be loaded right now.</p>
      ) : s ? (
        <div className="stat money-stat">
          <span className="stat-v"><Money paise={s.paise} whole size="xl" tone="save" /></span>
          <span className="stat-b">{s.basis}</span>
        </div>
      ) : (
        <p className="home-empty"><Icon name="chart" size={16} />No savings yet. They appear after a negotiated restock is confirmed.</p>
      )}
    </section>
  );
}

function VerifyBlock() {
  const q = useAsync(() => myBusinesses(), []);
  const b = q.data ? pickBusiness(q.data) : null;
  const w = b ? categoryWord(b.summary?.category, b.roles) : null;
  const next = b?.summary?.next_step;
  return (
    <section aria-labelledby="h-verify">
      <SectionHead title={<span id="h-verify">Business verification</span>} href={b ? `/network/business/${encodeURIComponent(b.bid)}` : undefined} linkText="Open" />
      {q.loading && !q.data ? <Skeleton lines={2} /> : q.error && !q.data ? (
        <p className="home-empty"><Icon name="alert" size={16} />Verification status could not be loaded right now.</p>
      ) : b && w ? (
        <div className="stack sm">
          <span className="strong break">{b.display_name}</span>
          <StatusPill tone={w.tone}>{w.label}</StatusPill>
          {next && <p className="small muted"><b className="ink">Next:</b> {next}</p>}
        </div>
      ) : (
        <div className="stack sm">
          <p className="small muted">Not verified yet. Suppliers can check who you are before they trade with you. About five minutes; no Aadhaar.</p>
          <div><Link className="btn secondary sm" href="/network/onboard?role=buyer"><Icon name="shield" size={14} />Verify my business</Link></div>
        </div>
      )}
    </section>
  );
}

function PauseCard({ initial }: { initial: boolean | null }) {
  const [on, setOn] = useState<boolean | null>(initial);
  const [arming, setArming] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [err, setErr] = useState<string | null>(null);
  async function flip(next: boolean) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setErr(null);
    try { const r = await setKillSwitch(next); setOn(r.kill_switch); setArming(false); }
    catch (e) { setErr(e instanceof ApiError && e.status === 403 ? 'Only the shop owner can pause Sauda. On this shared shop it is reserved for the operator.' : e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); inFlight.current = false; }
  }
  return (
    <div className="stack sm">
      {on === true ? (
        <div className="row between wrap sm">
          <StatusPill tone="bad">Sauda is paused for this shop</StatusPill>
          <Button variant="secondary" size="sm" icon="refresh" busy={busy} busyLabel="Resuming…" onClick={() => flip(false)}>Resume</Button>
        </div>
      ) : (
        <div className="stack xs">
          {on === false && <StatusPill tone="ok">Running: Sauda acts only inside limits you sign</StatusPill>}
          <p className="small muted">The kill switch stops every negotiation, order and payment for this shop until you resume.</p>
          <div><Button variant="danger" size="sm" onClick={() => setArming(true)}>Pause Sauda</Button></div>
        </div>
      )}
      <Sheet open={arming && on !== true} onClose={() => !busy && setArming(false)} title="Pause Sauda?">
        <p className="muted">Sauda will refuse every negotiation round, order and payment for this shop until you resume. Nothing already ordered is cancelled.</p>
        {err && <Callout tone="bad">{err}</Callout>}
        <Button variant="danger-solid" block busy={busy} busyLabel="Pausing…" onClick={() => flip(true)}>Pause now</Button>
        <Button variant="ghost" block onClick={() => setArming(false)} disabled={busy}>Keep running</Button>
      </Sheet>
      {err && !arming && <Callout tone="bad">{err}</Callout>}
    </div>
  );
}
