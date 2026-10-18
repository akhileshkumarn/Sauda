'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { AUTH_MODE, onUser, signInWithGoogle } from '@/lib/auth';
import { MOCK } from '@/lib/api';
import { Button, Callout, Icon, Skeleton, type IconName } from './ui';
import { Wordmark } from './BrandMark';

const POINTS: { icon: IconName; title: string; body: string }[] = [
  { icon: 'mic', title: 'Talk your restock', body: 'Say or type what you need in English, Hindi, Telugu, Tamil and other Indian languages. Sauda turns it into a draft you can edit.' },
  { icon: 'lock', title: 'Negotiates inside limits you sign', body: 'Only with registered suppliers, and never above the budget and prices you set.' },
  { icon: 'shield', title: 'Nothing is bought until you approve', body: 'Every step lands on a signed record that anyone can verify.' },
];

const EXPLORE: { href: string; label: string; hint: string }[] = [
  { href: '/trust/latest', label: 'See the signed record', hint: 'Every step of a real run' },
  { href: '/attack', label: 'Try to trick Sauda', hint: 'Send a hostile supplier message' },
  { href: '/savings/demo', label: 'Savings', hint: 'What negotiation saved' },
  { href: '/', label: 'What is Sauda?', hint: 'The product page' },
];

/** Where to go after sign-in: an explicit same-site ?next= path, else stay on the page that asked. */
function nextPath(): string | null {
  if (typeof window === 'undefined') return null;
  const n = new URLSearchParams(window.location.search).get('next');
  return n && n.startsWith('/') && !n.startsWith('//') && !n.startsWith('/\\') ? n : null;
}

/** Decorative product preview, drawn with CSS. Hidden from assistive tech. */
function IntroArt() {
  const lines: [string, string][] = [['Aashirvaad Atta 5 kg', '× 10'], ['Fortune Sunflower Oil 1 L', '× 20'], ['Tata Salt 1 kg', '× 30']];
  return (
    <div className="intro-art" aria-hidden>
      <div className="intro-device">
        <div className="intro-dev-head">
          <span className="intro-dev-title">Diwali restock</span>
          <span className="pill ok"><span className="dot" /><span>Limits signed</span></span>
        </div>
        <div className="intro-said">
          <span className="intro-bubble">दस आटा, बीस सनफ्लावर तेल, नमक</span>
          <span className="intro-said-meta"><Icon name="mic" size={12} /> Hindi, by voice</span>
        </div>
        <ul className="intro-lines">
          {lines.map(([n, q]) => <li key={n}><span>{n}</span><span className="num">{q}</span></li>)}
        </ul>
        <div className="intro-neg">
          <div className="intro-neg-row"><span>Sharma Traders</span><span className="num">Round 2 of 3</span></div>
          <div className="intro-rounds"><i className="on" /><i className="cur" /><i /></div>
        </div>
        <div className="intro-limit">
          <div className="intro-neg-row"><span>Within your limit</span><span className="num">₹17,840 of ₹24,000</span></div>
          <div className="meter"><span style={{ width: '74%' }} /></div>
        </div>
        <div className="intro-dev-foot">
          <span className="intro-fake-btn">Approve cart</span>
          <span className="intro-hash"><Icon name="check" size={12} /> signed · 9f2c…41a0</span>
        </div>
      </div>
    </div>
  );
}

function SignedOut({ busy, err, onSignIn }: { busy: boolean; err: string | null; onSignIn: () => void }) {
  return (
    <div className="intro-wrap">
      <section className="intro" aria-labelledby="intro-h">
        <div className="intro-copy">
          <Wordmark height={30} />
          <div className="intro-head">
            <h1 id="intro-h">Restock within your limits</h1>
            <p className="intro-lede">Sauda drafts your shop’s restock, bargains with suppliers for you, and orders only when you say yes.</p>
          </div>
          <ul className="intro-points">
            {POINTS.map((p) => (
              <li key={p.title}>
                <span className="intro-ico"><Icon name={p.icon} size={16} /></span>
                <span className="intro-pt"><b>{p.title}</b><span>{p.body}</span></span>
              </li>
            ))}
          </ul>
          <div className="intro-cta">
            <Button block busy={busy} busyLabel="Opening Google…" onClick={onSignIn}>Continue with Google</Button>
            <p className="intro-cta-note">The restock flow needs sign-in: your limits are signed with your Google identity, so nobody else can change them.</p>
            {err && <Callout tone="bad" title="Sign-in did not finish.">{err}</Callout>}
          </div>
          <nav className="intro-explore" aria-label="Explore without signing in">
            <span className="intro-explore-h">Explore without signing in</span>
            <ul>
              {EXPLORE.map((l) => (
                <li key={l.href}>
                  <Link href={l.href}>
                    <span className="intro-ex-t"><b>{l.label}</b><span>{l.hint}</span></span>
                    <Icon name="arrow" size={16} />
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <p className="intro-note"><span className="dot neutral" aria-hidden />Sample shop with real product prices; suppliers are simulated.</p>
        </div>
        <IntroArt />
      </section>
    </div>
  );
}

/** Owner pages only. Judge pages (/trust, /attack, /savings) never use this. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<{ name: string; email: string } | null | undefined>(undefined);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  useEffect(() => {
    if (MOCK || AUTH_MODE === 'demo') { setUser({ name: 'Shop owner', email: '' }); return; }
    let off = () => {};
    onUser(setUser).then((f) => { off = f; }).catch((e) => { setErr(String(e?.message || e)); setUser(null); });
    return () => off();
  }, []);
  if (user === undefined) return <div className="narrow" aria-busy="true" aria-label="Checking sign-in"><Skeleton lines={3} /></div>;
  if (!user) {
    const signIn = () => { setBusy(true); setErr(null); signInWithGoogle().then(() => { const n = nextPath(); if (n) router.replace(n); }).catch((e) => setErr(String(e?.message || e))).finally(() => setBusy(false)); };
    return <SignedOut busy={busy} err={err} onSignIn={signIn} />;
  }
  return (
    <>
      {children}
    </>
  );
}
