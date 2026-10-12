'use client';

import { AdminPageHeader } from '../../../components/admin/AdminPageHeader';
import { AdminQuality } from '../../../components/admin/AdminQuality';
import { t, useLang } from '../../../lib/i18n';

export default function QualityPage() {
  const [lang] = useLang();
  return (
    <>
      <AdminPageHeader title={t(lang, 'admin.quality.title')} description={t(lang, 'admin.quality.subtitle')} />
      <AdminQuality />
    </>
  );
}
