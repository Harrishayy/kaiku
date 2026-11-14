import Link from 'next/link';
import type { ReactNode } from 'react';

const TEAM = [
  { href: '/health/', label: 'System health' },
  { href: '/eval/', label: 'Evaluation' },
  { href: '/tune/', label: 'Tuning' },
];

/** Frame for the internal team pages. The practitioner dashboard at `/` has its own full-viewport shell. */
export function TeamShell({ children }: { children: ReactNode }) {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <Link href="/" className="brand" aria-label="Back to the practitioner dashboard">
            Kaiku
          </Link>
          <nav aria-label="Team pages">
            <ul className="nav-list">
              <li>
                <Link href="/" className="nav-link">
                  Practitioner dashboard
                </Link>
              </li>
              <li className="nav-sep" aria-hidden="true" />
              {TEAM.map((l) => (
                <li key={l.href}>
                  <Link href={l.href} className="nav-link">
                    {l.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <main id="main" className="container">
        {children}
      </main>
      <footer className="footer">
        <div className="container">
          <p>
            <strong>Research prototype</strong> built at Junction 2026. Internal team pages. Kaiku is not a medical device.
          </p>
        </div>
      </footer>
    </>
  );
}
