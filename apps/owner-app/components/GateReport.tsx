import type { GateReport as GR, GateRuleResult } from '@/lib/types';
import { normalizeGate } from '@/lib/api';
import { maskVpasIn, reasonText } from '@/lib/format';
import { Evidence, Icon, StatusPill } from './ui';

/** Plain-language name of each deterministic check. Rule IDs live under technical evidence. */
export const RULE_LABEL: Record<string, string> = {
  R1: 'Your signed limits are valid and not expired',
  R2: 'Supplier is registered and its identity matches',
  R3: 'Total is within your budget',
  R4: 'Every price is at or below its ceiling',
  R5: 'Advance is within your limit',
  R6: 'Delivery arrives by your date',
  R7: 'Quantities and prices look normal',
  R8: 'Payment goes to the payout account on record',
  R9: 'Supplier messages passed safety screening',
  R10: 'You approve before anything is ordered',
  R11: 'This order has not been placed before',
  R12: 'You have not switched off the limits',
};

const sortRules = (a: GateRuleResult, b: GateRuleResult) => Number(a.rule.slice(1)) - Number(b.rule.slice(1));

export function GateReport({ report: raw, title = 'Safety checks' }: { report: GR; title?: string }) {
  const report = normalizeGate(raw);
  const res = [...report.results].sort(sortRules);
  const failed = res.filter((r) => r.verdict === 'DENY');
  const approval = res.filter((r) => r.verdict === 'CONFIRM');
  const passed = res.filter((r) => r.verdict === 'PASS' || r.verdict === 'ALLOW');
  const Group = ({ items, tone, heading }: { items: GateRuleResult[]; tone: 'ok' | 'warn' | 'bad'; heading: string }) => items.length ? (
    <div className="stack sm">
      <span className="small" style={{ color: 'var(--ink)' }}>{heading} · {items.length}</span>
      <ul className="stack xs small" style={{ listStyle: 'none', padding: 0 }}>
        {items.map((r) => (
          <li key={r.rule} className="row sm top">
            <span style={{ color: `var(--${tone})` }}><Icon name={tone === 'ok' ? 'check' : tone === 'warn' ? 'alert' : 'x'} size={14} /></span>
            <span>{tone === 'ok' ? (RULE_LABEL[r.rule] || r.check || r.rule) : reasonText(r.reason_code || '', {}) || RULE_LABEL[r.rule]}</span>
          </li>
        ))}
      </ul>
    </div>
  ) : null;
  const parts = [passed.length ? `${passed.length} ${passed.length === 1 ? 'check' : 'checks'} passed` : null, approval.length ? `${approval.length} ${approval.length === 1 ? 'needs' : 'need'} your approval` : null, failed.length ? `${failed.length} failed` : null].filter(Boolean);
  return (
    <section className="stack sm" aria-label={title}>
      <div className="section-h" style={{ marginBottom: 0 }}><h2>{title}</h2></div>
      <span className="row sm"><StatusPill tone={failed.length ? 'bad' : approval.length ? 'warn' : 'ok'}>{parts.join(' · ') || 'No checks reported'}</StatusPill></span>
      <Group items={failed} tone="bad" heading="Failed" />
      <Evidence label="See all checks">
        <Group items={approval} tone="warn" heading="Needs your approval" />
        <Group items={passed} tone="ok" heading="Passed" />
        <span>Policy gate action <span className="code">{report.action || '—'}</span>, verdict <b>{report.verdict}</b></span>
        {res.map((r) => (
          <div key={r.rule} className="mono">{maskVpasIn(`${r.rule} ${r.verdict}${r.reason_code ? ` ${r.reason_code}` : ''}${r.detail ? ` · ${r.detail}` : ''}`)}</div>
        ))}
      </Evidence>
    </section>
  );
}
