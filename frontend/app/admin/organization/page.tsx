'use client';

import { AdminOrg } from '../../../components/admin/AdminOrg';
import { AdminPageHeader } from '../../../components/admin/AdminPageHeader';
import { AdminPolicies } from '../../../components/admin/AdminPolicies';
import { t, useLang } from '../../../lib/i18n';

export default function OrganizationPage() {
  const [lang] = useLang();
  return (
    <>
      <AdminPageHeader title={t(lang, 'admin.org.title')} description={t(lang, 'admin.org.subtitle')} />
      <AdminOrg />
      <AdminPolicies />
    </>
  );
}
