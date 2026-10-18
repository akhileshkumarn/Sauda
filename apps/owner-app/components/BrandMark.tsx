/**
 * Sauda wordmark: hand-drawn squared capitals, every letter on the same cap and base line (cap height
 * 40 on a 48-unit box). The two A's carry a level marigold crossbar at the same height: two sides,
 * one level. The word is the logo; there is no separate symbol beside it. Strokes use currentColor.
 */
export function Wordmark({ height = 20, title = 'Sauda' }: { height?: number; title?: string }) {
  const gold = 'var(--marigold, #e2a11b)';
  return (
    <svg className="wordmark-svg" height={height} width={(height * 164) / 48} viewBox="0 0 164 48" role="img" aria-label={title}
      fill="none" stroke="currentColor" strokeWidth="3.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M24 9a5 5 0 0 0-5-5H8a5 5 0 0 0-5 5v10a5 5 0 0 0 5 5h11a5 5 0 0 1 5 5v10a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5" />
      <path d="M34 44V11a7 7 0 0 1 7-7h10a7 7 0 0 1 7 7v33" />
      <path d="M68 4v33a7 7 0 0 0 7 7h10a7 7 0 0 0 7-7V4" />
      <path d="M102 4v40h14a10 10 0 0 0 10-10V14a10 10 0 0 0-10-10z" />
      <path d="M136 44V11a7 7 0 0 1 7-7h10a7 7 0 0 1 7 7v33" />
      <path d="M34 28h24" stroke={gold} />
      <path d="M136 28h24" stroke={gold} />
    </svg>
  );
}

/** Compact mark where a word cannot fit (assistant avatar, favicon): the wordmark's A with its level bar. */
export function BrandMark({ size = 28 }: { size?: number }) {
  const ink = 'var(--brand-ink, #f6f5f1)';
  return (
    <svg className="brand-svg" width={size} height={size} viewBox="0 0 48 48" aria-hidden focusable="false">
      <rect width="48" height="48" rx="11" fill="var(--brand-tile, #1a1915)" />
      <path d="M14 38V16.5a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6V38" fill="none" stroke={ink} strokeWidth="4.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14 27h20" stroke="var(--marigold, #e2a11b)" strokeWidth="4.4" strokeLinecap="round" />
    </svg>
  );
}
