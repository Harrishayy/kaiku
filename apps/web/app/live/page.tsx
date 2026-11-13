import type { Metadata } from 'next';
import { LiveFeed } from './LiveFeed';

export const metadata: Metadata = { title: 'Live' };

export default function LivePage() {
  return <LiveFeed />;
}
