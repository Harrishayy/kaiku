import type { Metadata } from 'next';
import { FireflyGame } from './FireflyGame';

export const metadata: Metadata = { title: 'Firefly' };

export default function Page() {
  return <FireflyGame />;
}
