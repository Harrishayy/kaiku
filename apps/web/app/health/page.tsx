import type { Metadata } from 'next';
import { TeamShell } from '@/components/TeamShell';
import { HealthView } from './HealthView';

export const metadata: Metadata = { title: 'System health' };

export default function HealthPage() {
  return (
    <TeamShell>
      <HealthView />
    </TeamShell>
  );
}
