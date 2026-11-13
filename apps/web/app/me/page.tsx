import type { Metadata } from 'next';
import { MeView } from './MeView';

export const metadata: Metadata = { title: 'My week' };

export default function Page() {
  return <MeView />;
}
