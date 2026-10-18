'use client';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { ist } from '@/lib/format';
import { TIER_WORD, absoluteUrl, categoryWord, dimWord, getProfile, listRelationships, readinessList, requirementWord, sourceWord } from '@/lib/network';
import type { TnReadiness } from '@/lib/types';
import { useAsync } from '@/lib/useAsync';
import type { TnProfile } from '@/lib/types';
import { ErrorState, Icon, SectionHead, Skeleton, StatusPill } from '../ui';
import { CheckStatus, Limitations, SourceBadge } from './shared';
import { WhatsAppShare } from './SampleShop';

const INDEPENDENT = new Set(['official_registry', 'authorised_provider', 'human_review', 'uploaded_evidence', 'device_signal']);

export function ProfileView({ bid }: { bid: string }) {
  const sp = useSearchParams();
  const back = sp.get('back');
  const as = sp.get('as');
  const q = useAsync(async () => {
    const p = await getProfile(bid);
    // Readiness is computed against the viewer's own requirements on the relationship, when there is one.
    if (as && as !== bid && !readinessList(p.readiness).length) {
      try {
        const rel = (await listRelationships(as)).find((r) => r.buyer_bid === bid || r.seller_bid === bid);
        if (rel?.readiness) return { ...p, readiness: rel.readiness as TnReadiness[] | Record<string, TnReadiness> };
      } catch { /* optional */ }
    }
    return p;
  }, [bid, as]);
  return (
    <div className="narrow">
      <Link href={back || '/network'} className="small muted row sm tn-back" style={{ minHeight: 32 }}><Icon name="chev" size={14} /><span>Back</span></Link>
      {q.loading && !q.data && <Skeleton lines={8} />}
      {q.error && !q.data ? <ErrorState error={q.error} onRetry={q.reload} title="Could not load this profile" /> : null}
      {q.data && <Body p={q.data} own={!as || as === bid} />}
    </div>
  );
}

function Body({ p, own }: { p: TnProfile; own: boolean }) {
  const s = p.summary;
  const w = categoryWord(s?.category, p.roles, (p as { sandbox?: boolean }).sandbox);
  const shareLink = absoluteUrl(`/network/business/${encodeURIComponent(p.bid)}/profile`);
  const rows = p.checks?.length ? p.checks : (s?.dimensions || []).map((d) => ({ ...d, check_id: d.dim, source_name: '' }));
  const live = rows.filter((r) => r.status !== 'not_applicable');
  const independent = live.filter((r) => r.source_kind && INDEPENDENT.has(r.source_kind) && ['verified', 'partially_verified'].includes(r.status));
  const simulated = live.filter((r) => r.source_kind === 'simulated_fixture');
  const declared = live.filter((r) => !independent.includes(r) && !simulated.includes(r));
  const ready = readinessList(p.readiness);

  return (
    <>
      <div className="tn-hero">
        <p className="small muted">Business profile · shared summary{own ? ' · what others see' : ''}</p>
        <h1>{p.display_name}</h1>
        <p className="muted">
          {p.roles.map((r) => (r === 'buyer' ? 'Buyer' : 'Supplier')).join(' and ')}
          {p.address?.city || p.address?.state ? ` · ${[p.address.city, p.address.state].filter(Boolean).join(', ')}` : ''}
          {p.constitution ? ` · ${p.constitution.replace(/_/g, ' ')}` : ''}
        </p>
        <div className="row sm wrap"><StatusPill tone={w.tone} size="lg">{w.label}</StatusPill>
          <WhatsAppShare business={p.display_name} link={shareLink} label="Share profile on WhatsApp"
            text={`${p.display_name} on Sauda: see its verification summary. The link opens after you sign in, and shows only what the business chose to share: ${shareLink}`} /></div>
      </div>

      <section className="stack sm" aria-labelledby="claims-h">
        <SectionHead title={<span id="claims-h">Who they say they are</span>} />
        <dl className="kv">
          {p.gstin_masked && <><dt>GSTIN</dt><dd className="num">{p.gstin_masked}</dd></>}
          {p.legal_name && p.legal_name !== p.display_name && <><dt>Legal name</dt><dd>{p.legal_name}</dd></>}
          {p.category && <><dt>Kind of business</dt><dd>{p.category.replace(/_/g, ' ')}</dd></>}
          {p.products?.length ? <><dt>Products</dt><dd>{p.products.join(', ')}</dd></> : null}
          {p.representative?.name && <><dt>Representative</dt><dd>{[p.representative.name, p.representative.role].filter(Boolean).join(', ')}</dd></>}
        </dl>
      </section>

      <Group title="Independently checked" empty="Nothing has been confirmed by an independent source yet." rows={independent} />
      {simulated.length > 0 && <Group title="Not checked against a government registry yet" empty="" rows={simulated} />}
      <Group title="Self-declared or still pending" empty="Nothing left self-declared." rows={declared} />

      {p.pending_review && p.pending_review.length > 0 && (
        <section className="stack sm">
          <SectionHead title="Waiting for a Sauda reviewer" />
          <ul className="req-list">{p.pending_review.map((x, i) => <li key={i}><span className="dot info" aria-hidden />{x}</li>)}</ul>
        </section>
      )}

      <section className="stack sm" aria-labelledby="meet-h">
        <SectionHead title={<span id="meet-h">Meets your requirements?</span>} />
        {ready.length === 0 && <p className="small muted">{own ? 'This is your own profile as others see it. Each business compares it with its own requirements.' : 'No trading relationship with this business yet, so there are no requirements to compare. Sauda’s default for small prepaid orders is identity and registration.'}</p>}
        <ul className="req-list">
          {ready.map((r) => (
            <li key={r.tier} style={{ flexDirection: 'column', alignItems: 'stretch', gap: 4 }}>
              <div className="row between wrap sm">
                <span className="strong">{TIER_WORD[r.tier] || r.tier.replace(/_/g, ' ')}</span>
                <StatusPill tone={r.ready ? 'ok' : 'warn'}>{r.ready ? 'Meets your requirements' : 'Not yet'}</StatusPill>
              </div>
              {!r.ready && r.missing.length > 0 && <span className="small muted">Missing: {r.missing.map(requirementWord).join('; ')}</span>}
              {r.note && <span className="small muted">{r.note}</span>}
            </li>
          ))}
        </ul>
        <p className="xs muted">Meeting requirements lets you approve trading. It never grants credit or approves large orders; those stay your decision.</p>
      </section>

      <Limitations items={s?.limitations || []} />
      <p className="xs muted">This is a summary. Documents, contact details and the business’s own customers and suppliers are never shared.</p>
    </>
  );
}

type Row = { check_id: string; dim: string; status: string; source_kind?: string | null; source_name?: string; summary: string; checked_at?: string | null };
function Group({ title, rows, empty }: { title: string; rows: Row[]; empty: string }) {
  return (
    <section className="stack sm">
      <SectionHead title={title} />
      {rows.length === 0 ? (empty ? <p className="small muted">{empty}</p> : null) : (
        <ul className="dims">
          {rows.map((r) => (
            <li key={r.check_id + r.dim} className="dim">
              <div className="dim-top">
                <span className="dim-name">{dimWord(r.dim).label}</span>
                <CheckStatus status={r.status} />
                <p className="dim-sum">{r.summary || dimWord(r.dim).help}</p>
                <div className="dim-meta" style={{ paddingBottom: 8 }}>
                  <SourceBadge kind={r.source_kind} name={r.source_name} />
                  {r.source_name && r.source_name !== sourceWord(r.source_kind) && <span className="break">{r.source_name}</span>}
                  {r.checked_at && <span>{ist(r.checked_at)}</span>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
