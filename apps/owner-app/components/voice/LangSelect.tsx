'use client';
// Compact language menu (native names) shared by voice restock and voice onboarding.
import { LANGS, type LangCode } from '@/lib/languages';

export function LangSelect({ value, onChange, label = 'Language you will speak', className }: {
  value: LangCode; onChange: (v: LangCode) => void; label?: string; className?: string;
}) {
  return (
    <select
      className={`lang-select${className ? ` ${className}` : ''}`}
      aria-label={label}
      title={label}
      value={value}
      onChange={(e) => onChange(e.target.value as LangCode)}
    >
      {LANGS.map((l) => (
        <option key={l.code} value={l.code} lang={l.code === 'bho' ? 'bho' : l.code}>
          {l.native}{l.beta ? ` (${l.beta})` : ''}
        </option>
      ))}
    </select>
  );
}
