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
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
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
          <button type="button" className="avatar-btn" aria-haspopup="menu" aria-expanded={open} aria-label="Your profile" onClick={() => setOpen((o) => !o)}>
            {user.photo ? <img src={user.photo} alt="" referrerPolicy="no-referrer" /> : <span>{initial}</span>}
          </button>
          {open && (
            <div className="profile-pop" role="menu" aria-label="Profile">
              <div className="profile-head">
                <div className="profile-name ellipsis">{user.name}</div>
                {user.email && <div className="profile-email ellipsis">{user.email}</div>}
              </div>
              {AUTH_MODE === 'firebase' && !MOCK && (
                <button type="button" role="menuitem" className="profile-item" onClick={() => { setOpen(false); signOut(); }}>Sign out</button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
