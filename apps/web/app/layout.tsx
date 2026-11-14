import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import tokens from '@design/tokens.json';
// design/ is the ground truth: tokens are imported from the generated file, never copied.
import '../../../design/generated/tokens.css';
import './globals.css';
import './dashboard.css';

export const metadata: Metadata = {
  title: { default: 'Kaiku', template: '%s · Kaiku' },
  description: 'Kaiku practitioner dashboard: staying well at home after TMS treatment. Research prototype.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: tokens.color.light.bg },
    { media: '(prefers-color-scheme: dark)', color: tokens.color.dark.bg },
  ],
};

// The font stylesheet URL is a token too.
const FONTS = tokens.type['google-fonts'];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link rel="stylesheet" href={FONTS} />
      </head>
      <body>{children}</body>
    </html>
  );
}
