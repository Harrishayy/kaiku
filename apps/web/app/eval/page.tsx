import type { Metadata } from 'next';
import { TeamShell } from '@/components/TeamShell';
import { EvalView } from './EvalView';

export const metadata: Metadata = { title: 'Evaluation' };

export default function EvalPage() {
  return (
    <TeamShell>
      <EvalView />
    </TeamShell>
  );
}
