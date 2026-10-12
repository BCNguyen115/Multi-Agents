'use client';

import { AdminKnowledge } from '../../../components/admin/AdminKnowledge';
import { AdminPageHeader } from '../../../components/admin/AdminPageHeader';
import { t, useLang } from '../../../lib/i18n';

export default function KnowledgePage() {
  const [lang] = useLang();
  return (
    <>
      <AdminPageHeader title={t(lang, 'admin.knowledge.title')} description={t(lang, 'admin.knowledge.subtitle')} />
      <AdminKnowledge />
    </>
  );
}
