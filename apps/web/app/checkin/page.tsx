import type { Metadata } from 'next';
import { Redirect } from './Redirect';

export const metadata: Metadata = { title: 'Moved to PHQ-9' };

/** v1 weekly check-in was replaced by /phq9/ (every 14 days) + /session/ (daily-optional). */
export default function CheckinMoved() {
  return <Redirect to="/phq9/" />;
}
