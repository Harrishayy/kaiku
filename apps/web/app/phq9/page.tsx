import type { Metadata } from 'next';
import { Phq9Flow } from './Phq9Flow';

export const metadata: Metadata = { title: 'PHQ-9' };

export default function Page() {
  return <Phq9Flow />;
}
