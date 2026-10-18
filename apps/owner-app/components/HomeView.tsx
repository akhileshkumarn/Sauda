'use client';
import Link from 'next/link';
import { useRef, useState } from 'react';
import { ApiError, getOverview, listSessions, setKillSwitch } from '@/lib/api';
import { relTime, supplierName } from '@/lib/format';
import { useAsync } from '@/lib/useAsync';
import type { Overview, SessionSummary } from '@/lib/types';
import { NewRestockButton, SessionRow } from './restock/SessionList';
import { negotiationLabel, orderStatus, sessionLabel } from './status';
import { Button, Callout, ErrorState, Icon, Money, SectionHead, Skeleton, StatusPill, type Tone } from './ui';
import { Sheet } from './ui-client';
import { VerifyEntry } from './network/VerifyEntry';

export function HomeView() {
  const { data, error, loading, reload } = useAsync(() => getOverview(), []);
  const ss = useAsync(() => listSessions({ limit: 20 }).catch(() => [] as SessionSummary[]), []);
  return (
    <div className="narrow">
      <div className="stack xs" style={{ paddingTop: 8 }}>
        <h1 className="break">{data?.shop?.name || (loading ? '\u00a0' : 'Your shop')}</h1>
        <p className="muted">Restock inside limits you sign. Nothing is bought until you approve.</p>
        <p className="xs faint">Sample shop · real products and prices · suppliers are simulated</p>
      </div>
      <NewRestockButton />

      {loading && !data && <Skeleton lines={5} />}
      {error && !data ? <ErrorState error={error} onRetry={reload} title="Could not load your shop" /> : null}
      {data && <Body o={data} sessions={ss.data || []} />}
    </div>
  );
}

function Body({ o, sessions }: { o: Overview; sessions: SessionSummary[] }) {
  const firstRun = !o.active_negotiation && !o.pending_confirmation_id && o.recent_orders.length === 0 && sessions.length === 0;
  const resume = sessions.find((x) => x.resumable && x.status !== 'cancelled');
  const recent = sessions.filter((x) => x.sid !== resume?.sid).slice(0, 3);
  return (
    <>
      <Continue o={o} resume={resume || null} />
      {recent.length > 0 && (
        <section>
          <SectionHead title="Recent restocks" href="/restock" />
          <div className="list">{recent.map((r) => <SessionRow key={r.sid} r={r} />)}</div>
        </section>
      )}
      {o.recent_orders.length > 0 && (
        <section>
          <SectionHead title="Recent orders" href="/orders" />
          <div className="list">
            {o.recent_orders.slice(0, 3).map((r) => {
              const st = orderStatus(r);
              return (
                <Link key={r.order_id} href={`/pay/${encodeURIComponent(r.order_id)}`} className="li sess-row">
                  <div className="grow stack xs">
                    <span className="strong ellipsis">{supplierName(r.supplier_id, r.supplier_name || undefined)}</span>
                    <span className="small muted row sm wrap" style={{ rowGap: 0 }}><StatusPill tone={st.tone}>{st.label}</StatusPill><span>{relTime(r.created_at)}</span></span>
                  </div>
                  <Money paise={r.total_paise} className="strong none" />
                  <span className="chev-ico"><Icon name="chev" size={16} /></span>
                </Link>
              );
            })}
          </div>
        </section>
      )}
      {firstRun && <p className="small muted">Try: “10 atta 5 kg, 20 sunflower oil, keep under ₹8,000”. You check every line before anything happens.</p>}
      <p className="xs muted">You list it · you sign limits · Sauda negotiates · you approve and pay by UPI.</p>
      <VerifyEntry />
      <PauseCard initial={o.shop?.kill_switch ?? null} />
    </>
  );
}

function Continue({ o, resume }: { o: Overview; resume: SessionSummary | null }) {
  const n = o.active_negotiation;
  let href: string | null = null; let title = ''; let tone: Tone = 'neutral'; let label = ''; let money: number | null = null; let meta = '';
  if (o.pending_confirmation_id) {
    href = `/confirm/${encodeURIComponent(o.pending_confirmation_id)}`; title = 'Approve your cart'; tone = 'warn'; label = 'Needs your approval';
    meta = n?.started_at ? `started ${relTime(n.started_at)}` : '';
  } else if (resume) {
    const st = sessionLabel(resume.status);
    href = `/restock/${encodeURIComponent(resume.sid)}`; title = resume.title || 'Untitled restock'; tone = st.tone; label = st.label;
    money = resume.total_paise ?? resume.budget_paise ?? null;
    meta = `${resume.line_count} ${resume.line_count === 1 ? 'item' : 'items'} · ${relTime(resume.updated_at)}`;
  } else if (n) {
    const st = negotiationLabel(n.status, n.round);
    href = n.intent_mandate_id ? `/mandate/${encodeURIComponent(n.intent_mandate_id)}` : '/restock'; title = 'Your restock'; tone = st.tone; label = st.label;
    meta = n.started_at ? `started ${relTime(n.started_at)}` : '';
  }
  if (!href) return null;
  return (
    <section>
      <SectionHead title="Continue" />
      <Link href={href} className="rowlink" style={{ borderTop: '1px solid var(--line)' }}>
        <div className="grow stack xs">
          <span className="strong break" style={{ fontSize: 17 }}>{title}</span>
          <span className="small muted row sm wrap" style={{ rowGap: 0 }}><StatusPill tone={tone}>{label}</StatusPill>{meta && <span className="num">{meta}</span>}</span>
        </div>
        {money ? <Money paise={money} whole className="strong none" /> : null}
        <span className="chev-ico"><Icon name="chev" size={16} /></span>
      </Link>
      {!o.pending_confirmation_id && n && <Link href={`/trust/${encodeURIComponent(n.negotiation_id)}`} className="small muted" style={{ display: 'inline-flex', minHeight: 44, alignItems: 'center' }}>See the signed record</Link>}
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
    <div className="stack sm" style={{ paddingTop: 8 }}>
      {on === true ? (
        <div className="row between wrap sm">
          <StatusPill tone="bad">Sauda is paused for this shop</StatusPill>
          <Button variant="secondary" size="sm" icon="refresh" busy={busy} busyLabel="Resuming…" onClick={() => flip(false)}>Resume</Button>
        </div>
      ) : (
        <div><button type="button" className="linkbtn muted" style={{ minHeight: 44 }} onClick={() => setArming(true)}>Pause Sauda</button></div>
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
