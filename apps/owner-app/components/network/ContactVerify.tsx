'use client';
// Business contact verification: proves control of the business phone or email with a one-time code
// (phone) or a sign-in link (email). It does not prove authority to act for the business.
import type { ConfirmationResult } from 'firebase/auth';
import { useState } from 'react';
import { ApiError } from '@/lib/api';
import {
  ContactOtpError, NOT_ENABLED_TEXT, confirmPhoneCode, finish, otpAvailable, sendEmailLink, sendPhoneCode,
} from '@/lib/contactOtp';
import type { ContactKind, ContactVerifyResult } from '@/lib/networkRoles';
import { Button, Callout } from '../ui';
import { SegmentedControl, Sheet } from '../ui-client';

export const PROVES_TEXT = 'This shows you control the business phone or email. It does not show legal authority to act for the business; that still needs a document reviewed by a person.';

type Phase = 'idle' | 'sending' | 'sent' | 'verifying' | 'success' | 'error' | 'not_enabled';

/** Server and Firebase errors in plain English. `notEnabled` keeps the check pending. */
export function contactErrorText(e: unknown): { text: string; notEnabled: boolean } {
  if (e instanceof ContactOtpError) return { text: e.message, notEnabled: e.kind === 'not_enabled' };
  if (e instanceof ApiError) {
    const t: Record<string, string> = {
      invalid_contact_token: 'The confirmation could not be checked. Send a new code or link and try again.',
      email_not_verified: 'That email address was not confirmed. Open the link from the email we sent.',
      contact_missing: 'No phone or email came back from the confirmation. Try again.',
      rate_limited: 'Too many attempts for this business. You can try again in an hour.',
      contact_verification_unavailable: NOT_ENABLED_TEXT,
    };
    return { text: t[e.code] || e.message || 'Something went wrong. Try again.', notEnabled: e.code === 'contact_verification_unavailable' };
  }
  return { text: e instanceof Error ? e.message : String(e), notEnabled: false };
}

export function ContactResult({ r }: { r: ContactVerifyResult }) {
  const what = r.contact.kind === 'phone' ? 'phone' : 'email';
  const match = r.contact.declared_match;
  const tone = r.check.status === 'partially_verified' ? 'ok' : 'warn';
  return (
    <Callout tone={tone} title={tone === 'ok' ? `Business ${what} confirmed: ${r.contact.masked}` : `Business ${what} ${r.contact.masked} needs a look`}>
      <span className="stack xs">
        <span>{r.check.summary}</span>
        {match === true && <span className="small">It matches the {what} you gave when you added the business.</span>}
        {match === false && <span className="small">It differs from the {what} you gave when you added the business, so a reviewer will compare them.</span>}
        <span className="small muted">Your representative authority stays pending until a reviewer sees a document.</span>
      </span>
    </Callout>
  );
}

/** The "Confirm business phone or email" action plus its sheet. */
export function ContactVerifyButton({ bid, onDone }: { bid: string; onDone?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>Confirm phone or email</Button>
      <ContactVerify bid={bid} open={open} onClose={() => setOpen(false)} onDone={onDone} />
    </>
  );
}

export function ContactVerify({ bid, open, onClose, onDone }: { bid: string; open: boolean; onClose: () => void; onDone?: () => void }) {
  const [kind, setKind] = useState<ContactKind>('phone');
  const [phase, setPhase] = useState<Phase>('idle');
  const [value, setValue] = useState('');
  const [code, setCode] = useState('');
  const [conf, setConf] = useState<ConfirmationResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<ContactVerifyResult | null>(null);
  const busy = phase === 'sending' || phase === 'verifying';
  const enabled = otpAvailable();

  function reset(k: ContactKind = kind) {
    setKind(k); setPhase('idle'); setCode(''); setConf(null); setErr(null); setResult(null);
  }
  function fail(e: unknown, back: Phase) {
    const x = contactErrorText(e);
    setErr(x.text);
    setPhase(x.notEnabled ? 'not_enabled' : back === 'sent' ? 'sent' : 'error');
  }
  async function send() {
    setPhase('sending'); setErr(null);
    try {
      if (kind === 'phone') setConf(await sendPhoneCode(value, 'contact-recaptcha'));
      else await sendEmailLink(bid, value);
      setPhase('sent');
    } catch (e) { fail(e, 'error'); }
  }
  async function verify() {
    if (!conf) return;
    setPhase('verifying'); setErr(null);
    try {
      const r = await confirmPhoneCode(bid, conf, code);
      setResult(r); setPhase('success'); onDone?.();
    } catch (e) {
      const bad = e instanceof ContactOtpError && e.kind === 'bad_code';
      fail(e, bad ? 'sent' : 'error');
      if (!bad) setConf(null);
    }
  }
  function close() {
    if (busy) return;
    void finish();
    reset();
    onClose();
  }

  return (
    <Sheet open={open} onClose={close} title="Confirm the business phone or email">
      <p className="small muted">{PROVES_TEXT}</p>
      {!enabled && <Callout tone="neutral">{NOT_ENABLED_TEXT}. This check stays pending.</Callout>}
      {enabled && (
        <>
          <SegmentedControl<ContactKind> label="Contact type" value={kind} onChange={(k) => { if (!busy) { setValue(''); reset(k); } }}
            options={[{ value: 'phone', label: 'Phone' }, { value: 'email', label: 'Email' }]} />

          {phase === 'not_enabled' && <Callout tone="neutral">{NOT_ENABLED_TEXT}. This check stays pending; you can still upload an authorisation letter.</Callout>}

          {phase === 'success' && result && <ContactResult r={result} />}

          {(phase === 'idle' || phase === 'sending' || phase === 'error') && (
            <>
              <label className="field">
                <span>{kind === 'phone' ? 'Business mobile number' : 'Business email'} <span className="hint">· {kind === 'phone' ? 'we send a 6-digit code by SMS' : 'we email a sign-in link'}</span></span>
                <input className="input" inputMode={kind === 'phone' ? 'tel' : 'email'} type={kind === 'phone' ? 'tel' : 'email'} autoComplete={kind === 'phone' ? 'tel' : 'email'}
                  placeholder={kind === 'phone' ? '98765 43210' : 'accounts@yourshop.in'} value={value} onChange={(e) => setValue(e.target.value)} disabled={busy} />
              </label>
              {err && phase === 'error' && <Callout tone="bad">{err}</Callout>}
              <Button block busy={phase === 'sending'} busyLabel={kind === 'phone' ? 'Sending code…' : 'Sending link…'} disabled={!value.trim()} onClick={send}>
                {phase === 'error' ? 'Try again' : kind === 'phone' ? 'Send code' : 'Send link'}
              </Button>
            </>
          )}

          {kind === 'phone' && (phase === 'sent' || phase === 'verifying') && (
            <>
              <p className="small">Code sent to the number ending {value.replace(/\D/g, '').slice(-4)}.</p>
              <label className="field">
                <span>6-digit code</span>
                <input className="input num" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} disabled={phase === 'verifying'} />
              </label>
              {err && <Callout tone="bad">{err}</Callout>}
              <Button block busy={phase === 'verifying'} busyLabel="Checking…" disabled={code.length !== 6} onClick={verify}>Confirm code</Button>
              <Button variant="ghost" block disabled={phase === 'verifying'} onClick={() => reset('phone')}>Use a different number</Button>
            </>
          )}

          {kind === 'email' && phase === 'sent' && (
            <>
              <Callout tone="info" title="Check your inbox">Open the link we sent to {value.trim()} on this device. It brings you back here to finish.</Callout>
              <Button variant="ghost" block onClick={() => reset('email')}>Use a different email</Button>
            </>
          )}
        </>
      )}
      <div id="contact-recaptcha" />
      <p className="xs muted">Sauda keeps only a masked copy and a keyed fingerprint of the phone or email, never the number or address itself, and never the code.</p>
      <Button variant="ghost" block onClick={close} disabled={busy}>{phase === 'success' ? 'Done' : 'Cancel'}</Button>
    </Sheet>
  );
}
