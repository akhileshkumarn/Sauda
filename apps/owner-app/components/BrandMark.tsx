/**
 * Sauda mark: a taraazu (balance scale) reduced to a beam, a post and two level pans on an ink
 * tile. Level pans = a fair deal; the marigold pivot is the seal on it. Drawn on a 32-unit grid
 * with 2.4-unit strokes so it stays legible at 16 px.
 */
export function BrandMark({ size = 28 }: { size?: number }) {
  const ink = 'var(--brand-ink, #f6f5f1)';
  return (
    <svg className="brand-svg" width={size} height={size} viewBox="0 0 32 32" aria-hidden focusable="false">
      <rect width="32" height="32" rx="8" fill="var(--brand-tile, #1a1915)" />
      <g fill="none" stroke={ink} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
        <path d="M7.5 12.5h17M16 12.5v11.5M12.5 24h7M9.5 12.5v4M22.5 12.5v4" />
      </g>
      <path d="M5.75 17h7.5a3.75 3.75 0 0 1-7.5 0zM18.75 17h7.5a3.75 3.75 0 0 1-7.5 0z" fill={ink} />
      <circle cx="16" cy="8.4" r="2.5" fill="var(--marigold, #e2a11b)" />
    </svg>
  );
}
