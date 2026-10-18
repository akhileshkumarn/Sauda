/** Sauda mark: a single-stroke S on an ink tile, with the accent "deal sealed" dot. */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg className="brand-svg" width={size} height={size} viewBox="0 0 32 32" aria-hidden focusable="false">
      <rect width="32" height="32" rx="9" fill="var(--brand-tile, #0a0a0a)" />
      <path d="M20.6 10.4C19.7 8.9 18.1 8 16.1 8 13.8 8 12 9.8 12 12s1.8 4 4 4 4 1.8 4 4-1.8 4-4 4c-2 0-3.7-.9-4.6-2.4" fill="none" stroke="var(--brand-ink, #fafafa)" strokeWidth="2.7" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="22.6" cy="22.6" r="2.1" fill="#2dd4bf" />
    </svg>
  );
}
