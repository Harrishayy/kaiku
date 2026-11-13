import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import tokens from '@design/tokens.json';
import { Nav } from '@/components/Nav';
import { LangProvider } from '@/lib/i18n';
// design/ is the ground truth: tokens are imported from the generated file, never copied.
import '../../../design/generated/tokens.css';
import './globals.css';
import './kaiku.css';

export const metadata: Metadata = {
  title: { default: 'Kaiku', template: '%s · Kaiku' },
  description: 'Kaiku helps people stay well at home after TMS treatment. Research prototype.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: tokens.color.light.bg },
    { media: '(prefers-color-scheme: dark)', color: tokens.color.dark.bg },
  ],
};

// Font families come from tokens (type.web); this is the stylesheet URL the generator prints in tokens.css.
const FONTS =
  'https://fonts.googleapis.com/css2?family=Fredoka:wght@400;500;600&family=Nunito:wght@400;600;700;800&family=DM+Mono:wght@400;500&display=swap';

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link rel="stylesheet" href={FONTS} />
      </head>
      <body>
        <LangProvider>
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
                <strong>Research prototype</strong> built at Junction 2026. Kaiku is not a medical device and is not a crisis
                service. In a crisis call the MIELI Crisis Helpline <a href="tel:+358925250111">09 2525 0111</a> (24/7) or{' '}
                <a href="tel:112">112</a>.
              </p>
              <p className="muted">
                Data marked SIMULATED is synthetic. <a href="/consent/">Consent &amp; privacy</a> · MIT licensed.
              </p>
            </div>
          </footer>
        </LangProvider>
      </body>
    </html>
  );
}
