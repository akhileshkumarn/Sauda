'use client';
// Business contact verification through a SECONDARY Firebase app instance.
// The owner's Google session lives on the default app and is never touched here: every sign-in below
// happens on the "sauda-contact-verify" app, which is signed out as soon as its ID token has been sent.
import type { Auth, ConfirmationResult, RecaptchaVerifier } from 'firebase/auth';
import { AUTH_MODE } from './auth';
import { submitContactToken, type ContactKind, type ContactVerifyResult } from './networkRoles';

const APP_NAME = 'sauda-contact-verify';
const EMAIL_KEY = 'sauda.contactVerify.email';
const NOT_ENABLED = new Set(['auth/operation-not-allowed', 'auth/configuration-not-found', 'auth/admin-restricted-operation']);

export const NOT_ENABLED_TEXT = "Phone/email verification isn't switched on yet";

export class ContactOtpError extends Error {
  constructor(public kind: 'not_enabled' | 'bad_code' | 'invalid_input' | 'too_many' | 'other', message: string, public code?: string) { super(message); }
}

export function otpAvailable(): boolean { return AUTH_MODE === 'firebase'; }

let authP: Promise<Auth> | null = null;
function secondaryAuth(): Promise<Auth> {
  if (!authP) {
    authP = (async () => {
      const { initializeApp, getApps } = await import('firebase/app');
      const { getAuth, inMemoryPersistence, setPersistence } = await import('firebase/auth');
      const app = getApps().find((a) => a.name === APP_NAME) || initializeApp({
        apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
        authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
        projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
        appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
      }, APP_NAME);
      const auth = getAuth(app);
      await setPersistence(auth, inMemoryPersistence).catch(() => { /* default persistence is still a separate app */ });
      return auth;
    })();
  }
  return authP;
}

/** Turn a Firebase error into a plain-English, typed error. */
export function mapFirebaseError(e: unknown): ContactOtpError {
  if (e instanceof ContactOtpError) return e;
  const code = (e as { code?: string })?.code || '';
  if (NOT_ENABLED.has(code)) return new ContactOtpError('not_enabled', NOT_ENABLED_TEXT, code);
  if (code === 'auth/invalid-verification-code' || code === 'auth/code-expired') return new ContactOtpError('bad_code', 'That code did not work. Check it, or send a new one.', code);
  if (code === 'auth/invalid-phone-number' || code === 'auth/missing-phone-number') return new ContactOtpError('invalid_input', 'Enter a 10-digit Indian mobile number.', code);
  if (code === 'auth/invalid-email' || code === 'auth/missing-email') return new ContactOtpError('invalid_input', 'Enter a valid email address.', code);
  if (code === 'auth/invalid-action-code' || code === 'auth/expired-action-code') return new ContactOtpError('bad_code', 'This sign-in link has expired or was already used. Send a new one.', code);
  if (code === 'auth/too-many-requests' || code === 'auth/quota-exceeded') return new ContactOtpError('too_many', 'Too many attempts. Wait a while and try again.', code);
  return new ContactOtpError('other', (e as Error)?.message || 'Something went wrong. Try again.', code || undefined);
}

export function toE164(raw: string): string | null {
  const d = raw.replace(/\D/g, '');
  const ten = d.length === 12 && d.startsWith('91') ? d.slice(2) : d.length === 11 && d.startsWith('0') ? d.slice(1) : d;
  return /^[6-9]\d{9}$/.test(ten) ? `+91${ten}` : null;
}

// ---------------------------------------------------------------- phone
let verifier: RecaptchaVerifier | null = null;

export async function sendPhoneCode(phone: string, containerId: string): Promise<ConfirmationResult> {
  const e164 = toE164(phone);
  if (!e164) throw new ContactOtpError('invalid_input', 'Enter a 10-digit Indian mobile number.');
  try {
    const auth = await secondaryAuth();
    const { RecaptchaVerifier, signInWithPhoneNumber } = await import('firebase/auth');
    verifier?.clear();
    verifier = new RecaptchaVerifier(auth, containerId, { size: 'invisible' });
    return await signInWithPhoneNumber(auth, e164, verifier);
  } catch (e) {
    verifier?.clear(); verifier = null;
    throw mapFirebaseError(e);
  }
}

export async function confirmPhoneCode(bid: string, conf: ConfirmationResult, code: string): Promise<ContactVerifyResult> {
  let token: string;
  try {
    const cred = await conf.confirm(code.trim());
    token = await cred.user.getIdToken();
  } catch (e) {
    await finish();
    throw mapFirebaseError(e);
  }
  return submitAndSignOut(bid, 'phone', token);
}

// ---------------------------------------------------------------- email link
export function returnUrl(bid: string): string {
  return `${window.location.origin}/network/business/${encodeURIComponent(bid)}/verify-contact`;
}

export async function sendEmailLink(bid: string, email: string): Promise<void> {
  const e = email.trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e)) throw new ContactOtpError('invalid_input', 'Enter a valid email address.');
  try {
    const auth = await secondaryAuth();
    const { sendSignInLinkToEmail } = await import('firebase/auth');
    await sendSignInLinkToEmail(auth, e, { url: returnUrl(bid), handleCodeInApp: true });
    try { localStorage.setItem(EMAIL_KEY, e); } catch { /* the return page asks for the email again */ }
  } catch (err) {
    throw mapFirebaseError(err);
  }
}

export function storedEmail(): string {
  try { return localStorage.getItem(EMAIL_KEY) || ''; } catch { return ''; }
}

export async function isEmailLink(href: string): Promise<boolean> {
  if (!otpAvailable()) return false;
  const auth = await secondaryAuth();
  const { isSignInWithEmailLink } = await import('firebase/auth');
  return isSignInWithEmailLink(auth, href);
}

export async function completeEmailLink(bid: string, email: string, href: string): Promise<ContactVerifyResult> {
  let token: string;
  try {
    const auth = await secondaryAuth();
    const { signInWithEmailLink } = await import('firebase/auth');
    const cred = await signInWithEmailLink(auth, email.trim().toLowerCase(), href);
    token = await cred.user.getIdToken();
  } catch (e) {
    await finish();
    throw mapFirebaseError(e);
  }
  try { localStorage.removeItem(EMAIL_KEY); } catch { /* ignore */ }
  return submitAndSignOut(bid, 'email', token);
}

// ---------------------------------------------------------------- common
async function submitAndSignOut(bid: string, kind: ContactKind, token: string): Promise<ContactVerifyResult> {
  try { return await submitContactToken(bid, kind, token); }
  finally { await finish(); }
}

/** Sign the temporary contact user out of the secondary app. The server deletes that user after checking it. */
export async function finish(): Promise<void> {
  try { verifier?.clear(); } catch { /* ignore */ }
  verifier = null;
  try { const auth = await secondaryAuth(); await auth.signOut(); } catch { /* ignore */ }
}
