'use client';
// Landing page for the business-email sign-in link. Completes the link on the secondary Firebase app,
// sends the ID token to Sauda and shows the result. The owner's own sign-in is not affected.
import { useEffect, useRef, useState } from 'react';
import { NOT_ENABLED_TEXT, completeEmailLink, isEmailLink, storedEmail } from '@/lib/contactOtp';
import type { ContactVerifyResult } from '@/lib/networkRoles';
import { Button, ButtonLink, Callout, PageHead } from '../ui';
import { ContactResult, PROVES_TEXT, contactErrorText } from './ContactVerify';

type Phase = 'checking' | 'need_email' | 'verifying' | 'success' | 'error' | 'not_link' | 'not_enabled';

export function VerifyContactReturn({ bid }: { bid: string }) {
  const [phase, setPhase] = useState<Phase>('checking');
  const [email, setEmail] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<ContactVerifyResult | null>(null);
  const started = useRef(false);
  const back = `/network/business/${encodeURIComponent(bid)}`;

  async function run(addr: string) {
    setPhase('verifying'); setErr(null);
    try {
      const r = await completeEmailLink(bid, addr, window.location.href);
      setResult(r); setPhase('success');
      window.history.replaceState(null, '', window.location.pathname);
    } catch (e) {
      const x = contactErrorText(e);
      setErr(x.text); setPhase(x.notEnabled ? 'not_enabled' : 'error');
    }
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      let link = false;
      try { link = await isEmailLink(window.location.href); } catch { link = false; }
      if (!link) { setPhase('not_link'); return; }
      const saved = storedEmail();
      if (saved) { setEmail(saved); void run(saved); } else setPhase('need_email');
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="narrow stack">
      <PageHead eyebrow="Business contact" title="Confirm business email" />
      <p className="small muted">{PROVES_TEXT}</p>
      {phase === 'checking' && <p className="small muted">Checking the link…</p>}
      {phase === 'verifying' && <p className="small muted">Confirming {email || 'your email'}…</p>}
      {phase === 'not_link' && <Callout tone="neutral">This page finishes an email confirmation link. Start from your business page to send one.</Callout>}
      {phase === 'not_enabled' && <Callout tone="neutral">{NOT_ENABLED_TEXT}. This check stays pending.</Callout>}
      {(phase === 'need_email' || phase === 'error') && (
        <>
          {phase === 'need_email' && <p className="small">You opened the link on a different device or browser. Enter the business email the link was sent to.</p>}
          <label className="field">
            <span>Business email</span>
            <input className="input" type="email" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          {err && <Callout tone="bad">{err}</Callout>}
          <Button block disabled={!email.trim()} onClick={() => run(email)}>{phase === 'error' ? 'Try again' : 'Confirm'}</Button>
        </>
      )}
      {phase === 'success' && result && <ContactResult r={result} />}
      <ButtonLink href={back} variant="secondary">Back to your business</ButtonLink>
    </div>
  );
}
