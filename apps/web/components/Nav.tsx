'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const LINKS = [
  { href: '/clinician/', label: 'Clinician' },
  { href: '/me/', label: 'My week' },
  { href: '/session/', label: 'Laptop session' },
  { href: '/phq9/', label: 'PHQ-9' },
  { href: '/live/', label: 'Live' },
  { href: '/health/', label: 'System health' },
  { href: '/eval/', label: 'Evaluation' },
  { href: '/tune/', label: 'Tune' },
];

export function Nav() {
  const path = usePathname() ?? '/';
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="brand" aria-label="Kaiku home">
          <span className="brand-mark" aria-hidden="true" />
          Kaiku
        </Link>
        <nav aria-label="Main">
          <ul className="nav-list">
            {LINKS.map((l) => {
              const active = path === l.href || path.startsWith(l.href);
              return (
                <li key={l.href}>
                  <Link href={l.href} className={active ? 'nav-link active' : 'nav-link'} aria-current={active ? 'page' : undefined}>
                    {l.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}
