import type { Metadata } from 'next';
import Link from 'next/link';
import { ButtonLink, Icon } from '@/components/ui';

export const metadata: Metadata = { title: 'Page not found' };

export default function NotFound() {
  return (
    <div className="narrow">
      <section className="nf" aria-labelledby="nf-h">
        <span className="nf-code" aria-hidden>404</span>
        <h1 id="nf-h" className="display">This page doesn’t exist</h1>
        <p className="muted">The link may be old or mistyped. Nothing was ordered or changed by opening it.</p>
        <div className="nf-actions">
          <ButtonLink href="/dashboard" icon="home">Go to your dashboard</ButtonLink>
          <ButtonLink href="/restock" variant="secondary" icon="cart">Your restocks</ButtonLink>
        </div>
        <Link className="nf-link" href="/trust/latest">See the signed record<Icon name="arrow" size={14} /></Link>
      </section>
    </div>
  );
}
