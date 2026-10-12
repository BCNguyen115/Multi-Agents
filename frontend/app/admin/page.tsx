'use client';

import { AdminOverview } from '../../components/admin/AdminOverview';

/** `/admin`: the console's front page. The frame (menu, `#main-content`, who may see it) is `app/admin/layout.tsx`; the other sections are the routes below it. */
export default function AdminPage() {
  return <AdminOverview />;
}
