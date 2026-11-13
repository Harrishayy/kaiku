import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import { Nav } from '@/components/Nav';
import './globals.css';

export const metadata: Metadata = {
  title: { default: 'Kaiku', template: '%s · Kaiku' },
  description: 'Kaiku — three independent sources, one consensus, for the months after TMS treatment. Research prototype.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f7f3ec' },
    { media: '(prefers-color-scheme: dark)', color: '#16181b' },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <Nav />
        <main id="main" className="container">
          {children}
        </main>
        <footer className="footer">
          <div className="container">
            <p>
              <strong>Research prototype</strong> built at Junction 2026. Kaiku is not a medical device, does not diagnose,
              and is not a crisis service. In a crisis call the MIELI Crisis Helpline <a href="tel:+358925250111">09 2525 0111</a>{' '}
              (24/7) or <a href="tel:112">112</a>.
            </p>
            <p className="muted">
              Data marked SIMULATED is synthetic. <a href="/consent/">Consent &amp; privacy</a> · MIT licensed.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
