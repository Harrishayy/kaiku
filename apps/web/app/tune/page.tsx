import type { Metadata } from 'next';
import { TuneView } from './TuneView';

export const metadata: Metadata = { title: 'Tune consensus (admin)', robots: { index: false } };

export default function Page() {
  return <TuneView />;
}
