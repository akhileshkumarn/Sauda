'use client';
// NEXT_PUBLIC_AUTH_MODE=firebase -> Google sign-in, Firebase ID token as Bearer.
// NEXT_PUBLIC_AUTH_MODE=demo     -> Bearer NEXT_PUBLIC_DEMO_OWNER_TOKEN.
import type { Auth, User } from 'firebase/auth';

export const AUTH_MODE = (process.env.NEXT_PUBLIC_AUTH_MODE || 'demo') as 'firebase' | 'demo';
const DEMO_TOKEN = process.env.NEXT_PUBLIC_DEMO_OWNER_TOKEN || '';

let authPromise: Promise<Auth> | null = null;

function firebaseAuth(): Promise<Auth> {
  if (!authPromise) {
    authPromise = (async () => {
      const { initializeApp, getApps } = await import('firebase/app');
      const { getAuth } = await import('firebase/auth');
      const app = getApps()[0] || initializeApp({
        apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
        authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
        projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
        appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
      });
      return getAuth(app);
    })();
  }
  return authPromise;
}

export async function getIdToken(): Promise<string | null> {
  if (AUTH_MODE === 'demo') return DEMO_TOKEN || null;
  const auth = await firebaseAuth();
  if (!auth.currentUser) {
    await (auth as Auth & { authStateReady?: () => Promise<void> }).authStateReady?.();
  }
  return auth.currentUser ? auth.currentUser.getIdToken() : null;
}

export async function signInWithGoogle(): Promise<User | null> {
  if (AUTH_MODE === 'demo') return null;
  const auth = await firebaseAuth();
  const { GoogleAuthProvider, signInWithPopup } = await import('firebase/auth');
  const cred = await signInWithPopup(auth, new GoogleAuthProvider());
  return cred.user;
}

export async function signOut(): Promise<void> {
  if (AUTH_MODE === 'demo') return;
  const auth = await firebaseAuth();
  await auth.signOut();
}

export async function onUser(cb: (u: { name: string; email: string; photo?: string } | null) => void): Promise<() => void> {
  if (AUTH_MODE === 'demo') {
    cb({ name: 'Shop owner', email: '' });
    return () => {};
  }
  const auth = await firebaseAuth();
  const { onAuthStateChanged } = await import('firebase/auth');
  return onAuthStateChanged(auth, (u) => cb(u ? { name: u.displayName || 'Owner', email: u.email || '', photo: u.photoURL || undefined } : null));
}
