import type { Metadata } from 'next';
import { PatientList } from './PatientList';

export const metadata: Metadata = { title: 'Clinician' };

export default function ClinicianPage() {
  return <PatientList />;
}
