'use client';

import { AdminOperations } from '../../../components/admin/AdminOperations';
import { AdminPageHeader } from '../../../components/admin/AdminPageHeader';
import { t, useLang } from '../../../lib/i18n';

export default function OperationsPage() {
  const [lang] = useLang();
  return (
    <>
      <AdminPageHeader title={t(lang, 'admin.ops.title')} description={t(lang, 'admin.ops.subtitle')} />
      <AdminOperations />
    </>
  );
}
