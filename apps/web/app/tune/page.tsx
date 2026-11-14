import type { Metadata } from 'next';
import { TeamShell } from '@/components/TeamShell';
import { TuneView } from './TuneView';

export const metadata: Metadata = { title: 'Tune consensus (admin)' };

export default function TunePage() {
  return (
    <TeamShell>
      <TuneView />
    </TeamShell>
  );
}
