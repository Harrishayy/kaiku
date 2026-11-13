import type { Metadata } from 'next';
import { PatientDetail } from './PatientDetail';

export const metadata: Metadata = { title: 'Patient' };

export default function PatientPage() {
  return <PatientDetail />;
}
