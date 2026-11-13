'use client';

import Link from 'next/link';
import { useEffect } from 'react';

/** Client-side redirect (static export has no server redirects). Keeps the query string (?home=&t=). */
export function Redirect({ to }: { to: string }) {
  useEffect(() => {
    window.location.replace(`${to}${window.location.search}`);
  }, [to]);
  return (
    <p className="state">
      The weekly check-in has moved. <Link href={to}>Go to the PHQ-9 page</Link>.
    </p>
  );
}
