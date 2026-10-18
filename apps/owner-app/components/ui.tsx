// Sauda UI kit. Every status is shown with an icon AND a text label (never colour alone).
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import Link from 'next/link';
import { rupees } from '@/lib/format';
import type { RuleVerdict } from '@/lib/types';

export const PLAN_B = 'Product set and prices are real; festival demand uplift is a stated assumption.';
export const SUPPLIER_DISCLOSURE = 'Simulated distributors: supplier agents with real catalogues and published strategies. Any UCP or A2A supplier can replace them.';
export const SETTLEMENT_CAPTION = 'Payment goes from your UPI app straight to the supplier. Sauda never holds funds.';

// ---------------------------------------------------------------- icons
const PATHS: Record<string, ReactNode> = {
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  alert: <><path d="M12 3.5l9.5 16.5h-19z" /><path d="M12 10v4.5M12 17.5v.01" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5.5M12 7.5v.01" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  shield: <><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></>,
  shieldx: <><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M9.5 9.5l5 5M14.5 9.5l-5 5" /></>,
  lock: <><rect x="5" y="10.5" width="14" height="10" rx="2" /><path d="M8 10.5V8a4 4 0 018 0v2.5" /></>,
  home: <><path d="M4 11l8-7 8 7" /><path d="M6 9.5V20h12V9.5" /></>,
  cart: <><path d="M3 4h2.5l2.2 11h10.6l2-8H6.5" /><circle cx="9" cy="19.5" r="1.3" /><circle cx="17" cy="19.5" r="1.3" /></>,
  box: <><path d="M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5z" /><path d="M3.5 7.5L12 12l8.5-4.5M12 12v9" /></>,
  bolt: <path d="M13 3L5 13.5h6L10 21l8-10.5h-6z" />,
  chart: <><path d="M4 20V4M4 20h16" /><path d="M8 16v-4M12 16V8M16 16v-6" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  trash: <><path d="M4.5 7h15M10 7V4.5h4V7M6.5 7l1 13h9l1-13" /></>,
  swap: <><path d="M7 7h12l-3-3M17 17H5l3 3" /></>,
  chev: <path d="M9 6l6 6-6 6" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  pen: <><path d="M4 20h4L19 9l-4-4L4 16z" /></>,
  mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0013 0M12 17.5V21" /></>,
  link: <><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1" /></>,
  flask: <><path d="M9.5 3h5M10.5 3v6L5 19a1.5 1.5 0 001.3 2h11.4A1.5 1.5 0 0019 19l-5.5-10V3" /></>,
  pause: <><circle cx="12" cy="12" r="9" /><path d="M10 9v6M14 9v6" /></>,
  user: <><circle cx="12" cy="8.5" r="3.5" /><path d="M5 20c1-3.5 3.7-5 7-5s6 1.5 7 5" /></>,
  upi: <><rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="M3 10h18M7 15h4" /></>,
  refresh: <><path d="M19.5 12a7.5 7.5 0 11-2.2-5.3" /><path d="M19.5 4.5v4h-4" /></>,
  more: <><circle cx="5.5" cy="12" r=".6" /><circle cx="12" cy="12" r=".6" /><circle cx="18.5" cy="12" r=".6" /></>,
  send: <path d="M12 19V5M6 11l6-6 6 6" />,
  stop: <rect x="7" y="7" width="10" height="10" rx="2" />,
  wifi: <><path d="M4 9.5a12 12 0 0116 0M7 13a7.5 7.5 0 0110 0M10 16.5a3 3 0 014 0" /><path d="M12 19.5v.01" /></>,
};
export type IconName = keyof typeof PATHS | string;

export function Icon({ name, size = 16, label, stroke = 2 }: { name: IconName; size?: number; label?: string; stroke?: number }) {
  stroke = Math.min(stroke, 1.75);
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round"
      role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true} focusable="false">
      {PATHS[name] || PATHS.info}
    </svg>
  );
}

// ---------------------------------------------------------------- Button
type BtnVariant = 'primary' | 'secondary' | 'ghost' | 'text' | 'danger' | 'danger-solid' | 'success';
export function Button({ variant = 'primary', size, block, busy, busyLabel, icon, children, className = '', disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: 'sm'; block?: boolean; busy?: boolean; busyLabel?: string; icon?: IconName }) {
  const cls = ['btn', variant === 'primary' ? '' : variant, size || '', block ? 'block' : '', className].filter(Boolean).join(' ');
  return (
    <button className={cls} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
      {busy ? <><span className="spinner" aria-hidden />{busyLabel || children}</> : <>{icon && <Icon name={icon} size={size === 'sm' ? 14 : 18} />}{children}</>}
    </button>
  );
}

export function ButtonLink({ href, variant = 'primary', size, block, icon, children }: { href: string; variant?: BtnVariant; size?: 'sm'; block?: boolean; icon?: IconName; children: ReactNode }) {
  const cls = ['btn', variant === 'primary' ? '' : variant, size || '', block ? 'block' : ''].filter(Boolean).join(' ');
  return <Link className={cls} href={href}>{icon && <Icon name={icon} size={size === 'sm' ? 14 : 18} />}{children}</Link>;
}

// ---------------------------------------------------------------- Card
export function Card({ title, subtitle, action, tone, className = '', children, as = 'section', id, labelledBy }:
  { title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; tone?: 'ok' | 'bad' | 'warn' | 'quar' | 'accent'; className?: string; children?: ReactNode; as?: 'section' | 'div' | 'article'; id?: string; labelledBy?: string }) {
  const Tag = as;
  const cls = ['card', tone ? (tone === 'accent' ? 'accent' : `tone-${tone}`) : '', className].filter(Boolean).join(' ');
  return (
    <Tag className={cls} id={id} aria-labelledby={labelledBy}>
      {(title || action) && (
        <div className="card-head">
          <div>{title && <h2 id={labelledBy}>{title}</h2>}{subtitle && <p>{subtitle}</p>}</div>
          {action && <div className="none">{action}</div>}
        </div>
      )}
      {children}
    </Tag>
  );
}

export function PageHead({ eyebrow, title, children, action }: { eyebrow?: string; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="row between top wrap">
      <div className="page-head grow">
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {action}
    </div>
  );
}

// ---------------------------------------------------------------- StatusPill
export type Tone = 'ok' | 'bad' | 'warn' | 'info' | 'quar' | 'neutral' | 'accent';
const TONE_ICON: Record<Tone, IconName> = { ok: 'check', bad: 'x', warn: 'alert', info: 'info', quar: 'lock', neutral: 'clock', accent: 'info' };

export function StatusPill({ tone, children, title, size }: { tone: Tone; children: ReactNode; icon?: IconName | null; title?: string; size?: 'lg' }) {
  return (
    <span className={`pill ${tone} ${size || ''}`} title={title}>
      <span className="dot" aria-hidden />
      <span>{children}</span>
    </span>
  );
}
/** 6px status dot. Always pair with a text label nearby. */
export function StatusDot({ tone = 'neutral', label }: { tone?: Tone; label?: string }) {
  return <span className={`dot ${tone}`} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true} title={label} />;
}

/** Legacy alias. */
export function Chip({ tone, children, title }: { tone: 'ok' | 'bad' | 'warn' | 'neutral' | 'accent'; children: ReactNode; title?: string }) {
  return <StatusPill tone={tone} title={title}>{children}</StatusPill>;
}

export function verdictTone(v?: RuleVerdict | string | null): 'ok' | 'bad' | 'warn' | 'neutral' {
  const s = String(v || '').toUpperCase();
  if (s === 'PASS' || s === 'ALLOW' || s === 'OK' || s === 'CLEAN' || s === 'ALLOWED') return 'ok';
  if (s === 'DENY' || s === 'BLOCKED' || s === 'BLOCK' || s === 'FAIL') return 'bad';
  if (s === 'CONFIRM' || s === 'NEEDS_APPROVAL') return 'warn';
  return 'neutral';
}

const VERDICT_WORD: Record<string, string> = { PASS: 'Passed', ALLOW: 'Allowed', CONFIRM: 'Needs your approval', DENY: 'Blocked' };
export function VerdictChip({ verdict }: { verdict?: RuleVerdict | string | null }) {
  const s = String(verdict || '').toUpperCase();
  return <StatusPill tone={verdictTone(verdict)}>{VERDICT_WORD[s] || s.toLowerCase() || 'unknown'}</StatusPill>;
}

// ---------------------------------------------------------------- Money
/** ₹ with Indian digit grouping (1,23,456.00) and tabular numerals. Input is integer paise. */
export function Money({ paise, whole, size, className = '' }: { paise: number | null | undefined; whole?: boolean; size?: 'lg' | 'xl'; className?: string }) {
  const text = rupees(paise, whole);
  return <span className={`money ${size || ''} ${className}`}>{text}</span>;
}

// ---------------------------------------------------------------- Callout
export function Callout({ tone = 'info', icon, title, children }: { tone?: 'info' | 'neutral' | 'ok' | 'bad' | 'warn' | 'quar'; icon?: IconName; title?: ReactNode; children?: ReactNode }) {
  const ic = icon || (tone === 'ok' ? 'check' : tone === 'bad' ? 'alert' : tone === 'warn' ? 'alert' : tone === 'quar' ? 'lock' : 'info');
  return (
    <div className={`callout ${tone}`} role={tone === 'bad' ? 'alert' : 'note'}>
      <Icon name={ic} size={16} />
      <div>{title && <b>{title} </b>}{children}</div>
    </div>
  );
}
/** Legacy alias. */
export function Banner({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'neutral' | 'bad' | 'ok' }) {
  return <Callout tone={tone}>{children}</Callout>;
}
export function PlanBBanner() { return <Callout tone="neutral" icon="flask">{PLAN_B}</Callout>; }
export function SupplierBanner() { return <Callout tone="neutral" icon="flask">{SUPPLIER_DISCLOSURE}</Callout>; }

// ---------------------------------------------------------------- Evidence
export function Evidence({ label = 'Details', children, open }: { label?: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="evidence" open={open}>
      <summary><span className="chev"><Icon name="chev" size={14} /></span>{label}</summary>
      <div className="ev-body">{children}</div>
    </details>
  );
}
export const Disclosure = Evidence;

/** A plain list row: leading content, trailing value, optional chevron. */
export function Row({ href, children, trailing, chevron = !!href }: { href?: string; children: ReactNode; trailing?: ReactNode; chevron?: boolean }) {
  const body = <>{<div className="grow stack xs">{children}</div>}{trailing && <div className="none right">{trailing}</div>}{chevron && <span className="chev-ico"><Icon name="chev" size={16} /></span>}</>;
  return href ? <Link href={href} className="rowlink">{body}</Link> : <div className="rowlink">{body}</div>;
}

/** Section heading with an optional trailing link. */
export function SectionHead({ title, href, linkText = 'See all' }: { title: ReactNode; href?: string; linkText?: string }) {
  return <div className="section-h"><h2>{title}</h2>{href && <Link href={href}>{linkText}</Link>}</div>;
}

// ---------------------------------------------------------------- EmptyState / ErrorState / Skeleton
export function EmptyState({ icon = 'box', title, children, action }: { icon?: IconName; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-ico"><Icon name={icon} size={28} /></div>
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function errorText(error: unknown): { title: string; detail: string } {
  const e = error as { status?: number; message?: string } | null;
  const msg = e?.message || (error ? String(error) : 'Unknown error');
  const st = e?.status;
  if (st === 401 || st === 403) return { title: 'You are not signed in to this shop', detail: 'Sign in again with the Google account that owns the shop.' };
  if (st === 404) return { title: 'We could not find this', detail: msg };
  if (st === 409 || st === 410) return { title: 'This has already changed', detail: msg };
  if (st === 429) return { title: 'Too many tries in a minute', detail: 'Wait a few seconds and try again.' };
  if (st && st >= 500) return { title: 'Sauda had a problem on its side', detail: msg };
  if (/fetch|network|Failed to fetch|load failed/i.test(msg)) return { title: 'Cannot reach Sauda', detail: 'Check your internet connection and try again.' };
  return { title: 'Something went wrong', detail: msg };
}

export function ErrorState({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const t = errorText(error);
  return (
    <div className="stack" role="alert" style={{ padding: '24px 0' }}>
      <div className="stack xs">
        <h2 className="row sm" style={{ fontSize: 17 }}><span className="dot bad" aria-hidden />{title || t.title}</h2>
        <p className="small muted break">{t.detail}</p>
      </div>
      {onRetry && <div><Button variant="secondary" icon="refresh" onClick={onRetry}>Try again</Button></div>}
    </div>
  );
}
/** Legacy alias. */
export const ErrorCard = ErrorState;

export function Skeleton({ lines = 3, block }: { lines?: number; block?: boolean }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }).map((_, i) => <div key={i} className={`skeleton ${block ? 'block' : ''}`} style={block ? undefined : { width: `${92 - (i % 4) * 14}%` }} />)}
    </div>
  );
}
export function SkeletonCard({ lines = 4 }: { lines?: number }) {
  return <div style={{ padding: '8px 0' }}><Skeleton lines={lines} /></div>;
}

// ---------------------------------------------------------------- Timeline
export type StepState = 'done' | 'current' | 'bad' | 'warn' | 'todo' | 'na';
export interface Step { key: string; title: ReactNode; body?: ReactNode; state: StepState; meta?: ReactNode }
const STEP_ICON: Record<StepState, IconName> = { done: 'check', current: 'clock', bad: 'x', warn: 'alert', todo: 'clock', na: 'minus' };
const STEP_WORD: Record<StepState, string> = { done: 'Done', current: 'In progress', bad: 'Failed', warn: 'Needs attention', todo: 'Not yet', na: 'Not tracked' };

export function Timeline({ steps, label }: { steps: Step[]; label?: string }) {
  return (
    <ol className="tl" aria-label={label}>
      {steps.map((s) => (
        <li key={s.key} className={`tl-row ${s.state}`}>
          <span className="tl-dot"><Icon name={STEP_ICON[s.state]} size={14} stroke={1.75} label={STEP_WORD[s.state]} /></span>
          <div className="tl-body">
            <div className="row between wrap sm"><span className="tl-title">{s.title}</span>{s.meta}</div>
            {s.body && <div style={{ marginTop: 2 }}>{s.body}</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------- Meter
export function Meter({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className={`meter ${value > max ? 'over' : ''}`} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-valuetext={`${pct}%`}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}
