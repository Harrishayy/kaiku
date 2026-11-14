import type { Metadata } from 'next';
import { Dashboard } from '@/components/dash/Dashboard';

export const metadata: Metadata = { title: 'Practitioner dashboard' };

export default function Home() {
  return <Dashboard />;
}
