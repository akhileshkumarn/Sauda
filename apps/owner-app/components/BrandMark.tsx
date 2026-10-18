/** Sauda mark: a single-stroke S on an ink tile, sealed with a marigold dot (the deal, closed). */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg className="brand-svg" width={size} height={size} viewBox="0 0 32 32" aria-hidden focusable="false">
      <rect width="32" height="32" rx="8" fill="var(--brand-tile, #1a1915)" />
      <path d="M20.6 10.4C19.7 8.9 18.1 8 16.1 8 13.8 8 12 9.8 12 12s1.8 4 4 4 4 1.8 4 4-1.8 4-4 4c-2 0-3.7-.9-4.6-2.4" fill="none" stroke="var(--brand-ink, #f6f5f1)" strokeWidth="2.7" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="23" cy="23" r="2.3" fill="var(--marigold, #e2a11b)" />
    </svg>
  );
}
