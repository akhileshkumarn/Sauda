import { THEME_BOOT } from '@/lib/theme';
import type { Metadata, Viewport } from 'next';
import { Fraunces, Geist, Geist_Mono } from 'next/font/google';
import './globals.css';
import { Nav } from '@/components/Nav';

const geist = Geist({ subsets: ['latin'], variable: '--font-geist', display: 'swap' });
const geistMono = Geist_Mono({ subsets: ['latin'], variable: '--font-geist-mono', display: 'swap' });
// Display face for page titles and the wordmark only. Variable weight + optical size; UI text stays in Geist.
const fraunces = Fraunces({ subsets: ['latin'], variable: '--font-display', display: 'swap', axes: ['opsz', 'SOFT'] });

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://saudaai.web.app';
const OG_TITLE = 'Sauda — restock within your limits';
const OG_DESC = 'Talk your restock in English, Hindi, Telugu, Tamil and other Indian languages. Sauda negotiates with registered suppliers inside limits you sign, and buys nothing until you approve.';

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: OG_TITLE, template: '%s · Sauda' },
  applicationName: 'Sauda',
  description: 'Sauda drafts your restock, negotiates with registered suppliers inside the limits you sign, and orders only after you approve. Every step is on a verifiable record.',
  openGraph: { type: 'website', siteName: 'Sauda', title: OG_TITLE, description: OG_DESC, locale: 'en_IN' },
  twitter: { card: 'summary_large_image', title: OG_TITLE, description: OG_DESC },
};
export const viewport: Viewport = { width: 'device-width', initialScale: 1, themeColor: [{ media: '(prefers-color-scheme: light)', color: '#f6f5f1' }, { media: '(prefers-color-scheme: dark)', color: '#12110f' }], viewportFit: 'cover' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable} ${fraunces.variable}`} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} /></head>
      <body>
        <div className="shell">
          <Nav />
          <main id="main" tabIndex={-1}>{children}</main>
        </div>
      </body>
    </html>
  );
}
