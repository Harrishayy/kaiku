import type { Metadata } from 'next';
import { EvalView } from './EvalView';

export const metadata: Metadata = { title: 'Evaluation' };

export default function EvalPage() {
  return <EvalView />;
}
