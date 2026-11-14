import type { Metadata } from 'next';
import { TeamShell } from '@/components/TeamShell';
import { DebugView } from '@/components/debug/DebugView';

export const metadata: Metadata = { title: 'Debug day' };

/** Team only: one day of one home through the pipeline (`/debug/?id=<home>&date=<YYYY-MM-DD>`). */
export default function DebugPage() {
  return (
    <TeamShell>
      <DebugView />
    </TeamShell>
  );
}
