'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef } from 'react';
import { Mascot } from './Mascot';

/** Person area and clinician area are separate; internal team pages live in a small "Team" menu. */
const MAIN = [
  { href: '/me/', label: 'For you', match: ['/me/', '/play/', '/session/', '/phq9/', '/consent/'] },
  { href: '/clinician/', label: 'Clinician', match: ['/clinician/'] },
];
const TEAM = [
  { href: '/live/', label: 'Live events' },
  { href: '/health/', label: 'System health' },
  { href: '/eval/', label: 'Evaluation' },
  { href: '/tune/', label: 'Tune the consensus' },
];

export function Nav() {
  const path = usePathname() ?? '/';
  const team = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (team.current) team.current.open = false;
  }, [path]);
  const teamActive = TEAM.some((l) => path.startsWith(l.href));
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="brand" aria-label="Kaiku home">
          <span className="brand-mark" aria-hidden="true">
            <Mascot size={34} still tappable={false} />
          </span>
          Kaiku
        </Link>
        <nav aria-label="Main">
          <ul className="nav-list">
            {MAIN.map((l) => {
              const active = l.match.some((m) => path.startsWith(m));
              return (
                <li key={l.href}>
                  <Link href={l.href} className={active ? 'nav-link active' : 'nav-link'} aria-current={active ? 'page' : undefined}>
                    {l.label}
                  </Link>
                </li>
              );
            })}
            <li className="nav-sep" aria-hidden="true" />
            <li>
              <details className="nav-team" ref={team}>
                <summary aria-current={teamActive ? 'page' : undefined}>Team</summary>
                <ul>
                  <li className="team-note">Internal</li>
                  {TEAM.map((l) => (
                    <li key={l.href}>
                      <Link href={l.href}>{l.label}</Link>
                    </li>
                  ))}
                </ul>
              </details>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  );
}
