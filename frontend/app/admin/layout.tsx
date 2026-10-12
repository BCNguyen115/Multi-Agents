import type { ReactNode } from 'react';
import { AdminShell } from '../../components/admin/AdminShell';

/** Every page under `/admin` shares the console frame (logo, menu, the `#main-content` area). */
export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
