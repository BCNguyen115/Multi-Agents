'use client';

import { AdminPageHeader } from '../../../components/admin/AdminPageHeader';
import { AdminUsers } from '../../../components/admin/AdminUsers';
import { t, useLang } from '../../../lib/i18n';

export default function AccountsPage() {
  const [lang] = useLang();
  return (
    <>
      <AdminPageHeader title={t(lang, 'admin.title')} description={t(lang, 'admin.subtitle')} />
      <AdminUsers />
    </>
  );
}
