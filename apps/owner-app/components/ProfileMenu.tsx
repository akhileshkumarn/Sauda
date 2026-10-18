'use client';
import { useEffect, useRef, useState } from 'react';
import { AUTH_MODE, onUser, signOut } from '@/lib/auth';
import { MOCK } from '@/lib/api';
import { effectiveTheme, getThemePref, setThemePref } from '@/lib/theme';

type User = { name: string; email: string; photo?: string };

function SunMoon({ dark }: { dark: boolean }) {
  return dark ? (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  ) : (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

/** Top-right controls: a light/dark toggle and, when signed in, the profile menu. */
export function ProfileMenu() {
  const [user, setUser] = useState<User | null>(null);
  const [dark, setDark] = useState(false);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setDark(effectiveTheme(getThemePref()) === 'dark');
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    const onSys = () => { if (getThemePref() === 'system') setDark(mq.matches); };
    mq?.addEventListener?.('change', onSys);
    return () => mq?.removeEventListener?.('change', onSys);
  }, []);

  useEffect(() => {
    if (MOCK || AUTH_MODE === 'demo') { setUser({ name: 'Shop owner', email: '' }); return; }
    let off = () => {};
    onUser((u) => setUser(u)).then((f) => { off = f; }).catch(() => setUser(null));
    return () => off();
  }, []);

  useEffect(() => {
    if (!open) return;
    // Move focus into the menu so keyboard users land on the first action.
    const first = popRef.current?.querySelector<HTMLElement>('[role="menuitem"]') || popRef.current;
    first?.focus();
    const onDoc = (e: MouseEvent | TouchEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); setOpen(false); btnRef.current?.focus(); return; }
      if (e.key === 'Tab') { setOpen(false); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
        const items = Array.from(popRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') || []);
        if (!items.length) return;
        e.preventDefault();
        const i = items.indexOf(document.activeElement as HTMLElement);
        const n = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : e.key === 'ArrowDown' ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
        items[n].focus();
      }
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('touchstart', onDoc, { passive: true });
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('touchstart', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);

  // Follows the system until the first click; a click pins the opposite of what is showing.
  const toggle = () => { const next = dark ? 'light' : 'dark'; setThemePref(next); setDark(next === 'dark'); };
  const initial = (user?.name || user?.email || '?').trim().charAt(0).toUpperCase();

  return (
    <div className="topbar-right" ref={ref}>
      <button type="button" className="icon-btn" onClick={toggle} aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'} title={dark ? 'Light mode' : 'Dark mode'}>
        <SunMoon dark={dark} />
      </button>
      {user && (
        <>
          <button ref={btnRef} type="button" className="avatar-btn" aria-haspopup="menu" aria-expanded={open} aria-controls={open ? 'profile-menu' : undefined} aria-label={`Your profile: ${user.name}`}
            onClick={() => setOpen((o) => !o)}
            onKeyDown={(e) => { if (e.key === 'ArrowDown' && !open) { e.preventDefault(); setOpen(true); } }}>
            {user.photo ? <img src={user.photo} alt="" referrerPolicy="no-referrer" /> : <span>{initial}</span>}
          </button>
          {open && (
            <div className="pm-pop" id="profile-menu" role="menu" aria-label="Profile" ref={popRef} tabIndex={-1}>
              <div className="pm-head">
                <span className="pm-av" aria-hidden>{user.photo ? <img src={user.photo} alt="" referrerPolicy="no-referrer" /> : initial}</span>
                <span className="pm-id">
                  <span className="pm-name">{user.name}</span>
                  {user.email ? <span className="pm-email">{user.email}</span> : <span className="pm-email">{MOCK ? 'Sample shop, no account' : 'Signed in'}</span>}
                </span>
              </div>
              {AUTH_MODE === 'firebase' && !MOCK ? (
                <>
                  <div className="pm-sep" role="separator" />
                  <button type="button" role="menuitem" className="pm-item" onClick={() => { setOpen(false); signOut(); }}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                      <path d="M15 4h3a2 2 0 012 2v12a2 2 0 01-2 2h-3M10 16l-4-4 4-4M6 12h10" />
                    </svg>
                    Sign out
                  </button>
                </>
              ) : (
                <p className="pm-note"><span className="dot neutral" aria-hidden />Sign-out is not needed in this mode.</p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
