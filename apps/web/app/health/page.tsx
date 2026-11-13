import type { Metadata } from 'next';
import { HealthView } from './HealthView';

export const metadata: Metadata = { title: 'System health' };

export default function HealthPage() {
  return <HealthView />;
}
