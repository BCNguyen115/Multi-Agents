'use client';

import { AdminApprovals } from '../../../components/admin/AdminApprovals';
import { AdminPageHeader } from '../../../components/admin/AdminPageHeader';
import { t, useLang } from '../../../lib/i18n';

export default function ApprovalsPage() {
  const [lang] = useLang();
  return (
    <>
      <AdminPageHeader title={t(lang, 'admin.approvals.title')} description={t(lang, 'admin.approvals.subtitle')} />
      <AdminApprovals />
    </>
  );
}
