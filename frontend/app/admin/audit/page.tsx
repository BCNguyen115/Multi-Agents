'use client';

import { AdminAudit } from '../../../components/admin/AdminAudit';
import { AdminPageHeader } from '../../../components/admin/AdminPageHeader';
import { t, useLang } from '../../../lib/i18n';

export default function AuditPage() {
  const [lang] = useLang();
  return (
    <>
      <AdminPageHeader title={t(lang, 'admin.audit.title')} description={t(lang, 'admin.audit.subtitle')} />
      <AdminAudit />
    </>
  );
}
