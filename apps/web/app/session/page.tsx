import type { Metadata } from 'next';
import { SessionFlow } from './SessionFlow';

export const metadata: Metadata = { title: 'Laptop session' };

export default function Page() {
  return <SessionFlow />;
}
