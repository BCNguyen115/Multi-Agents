'use client';

import { AdminPageHeader } from '../../../components/admin/AdminPageHeader';
import { AdminUsage } from '../../../components/admin/AdminUsage';
import { t, useLang } from '../../../lib/i18n';

export default function CostsPage() {
  const [lang] = useLang();
  return (
    <>
      <AdminPageHeader title={t(lang, 'usage.title')} description={t(lang, 'usage.subtitle')} />
      <AdminUsage />
    </>
  );
}
