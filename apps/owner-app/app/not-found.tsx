import type { Metadata } from 'next';
import Link from 'next/link';
import { ButtonLink, EmptyState } from '@/components/ui';

export const metadata: Metadata = { title: 'Page not found' };

export default function NotFound() {
  return (
    <div className="narrow">
      <div className="empty-wrap">
        <EmptyState icon="link" title="This page doesn’t exist"
          action={
            <div className="empty-actions">
              <ButtonLink href="/">Go to home</ButtonLink>
              <Link className="textlink" href="/trust/latest">See the signed record</Link>
            </div>
          }>
          The link may be old or mistyped. Nothing was ordered or changed by opening it.
        </EmptyState>
      </div>
    </div>
  );
}
