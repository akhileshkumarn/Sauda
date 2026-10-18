'use client';
import { useEffect, useState, type ReactNode } from 'react';
import { AUTH_MODE, onUser, signInWithGoogle } from '@/lib/auth';
import { MOCK } from '@/lib/api';
import { Button, Callout, Icon, Skeleton } from './ui';
import { BrandMark } from './BrandMark';

/** Owner pages only. Judge pages (/trust, /attack, /savings) never use this. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<{ name: string; email: string } | null | undefined>(undefined);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (MOCK || AUTH_MODE === 'demo') { setUser({ name: 'Shop owner', email: '' }); return; }
    let off = () => {};
    onUser(setUser).then((f) => { off = f; }).catch((e) => { setErr(String(e?.message || e)); setUser(null); });
    return () => off();
  }, []);
  if (user === undefined) return <div className="card"><Skeleton lines={3} /></div>;
  if (!user) {
    return (
      <div className="narrow">
        <section className="card pad-lg stack lg" aria-labelledby="signin-h">
          <BrandMark size={44} />
          <div className="stack sm">
            <h1 id="signin-h">Sign in to your shop</h1>
            <p className="muted">Sauda drafts your restock, negotiates with registered suppliers inside limits you sign, and orders only after you approve.</p>
          </div>
          <ul className="stack sm small" style={{ listStyle: 'none', padding: 0 }}>
            <li className="row sm top"><span style={{ color: 'var(--ok)' }}><Icon name="lock" /></span><span>Your limits are signed with your Google identity. Nobody else can change them.</span></li>
            <li className="row sm top"><span style={{ color: 'var(--ok)' }}><Icon name="shield" /></span><span>Nothing is bought until you approve the cart.</span></li>
          </ul>
          <Button block busy={busy} busyLabel="Opening Google…" onClick={() => { setBusy(true); setErr(null); signInWithGoogle().catch((e) => setErr(String(e?.message || e))).finally(() => setBusy(false)); }}>Continue with Google</Button>
          {err && <Callout tone="bad" title="Sign-in did not finish.">{err}</Callout>}
          <p className="xs faint">Judges: the Trust, Attack and Savings tabs work without signing in.</p>
        </section>
      </div>
    );
  }
  return (
    <>
      {children}
    </>
  );
}
