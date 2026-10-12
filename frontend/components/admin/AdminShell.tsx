'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Activity, ArrowLeft, BookOpen, Building2, LayoutDashboard, ScrollText, ShieldCheck, ThumbsUp, Users, Wallet, Wrench } from 'lucide-react';
import { FptLogo } from '../ui/FptLogo';
import { useAuth } from '../../context/AuthContext';
import { ADMIN_NAV, NAV_GROUPS, isActiveNav } from '../../lib/adminConsole';
import { t, useLang } from '../../lib/i18n';

const ICONS: Record<string, typeof Users> = {
  '/admin': LayoutDashboard,
  '/admin/monitoring': Activity,
  '/admin/operations': Wrench,
  '/admin/audit': ScrollText,
  '/admin/accounts': Users,
  '/admin/organization': Building2,
  '/admin/knowledge': BookOpen,
  '/admin/approvals': ShieldCheck,
  '/admin/costs': Wallet,
  '/admin/quality': ThumbsUp,
};

const LINK =
  'flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary';
const IDLE = 'text-foreground-secondary hover:bg-surface-raised hover:text-foreground';

/**
 * The frame of the administration console: the FPT logo, the menu of its sections (a rail on the left; a scrolling strip on a phone)
 * and the content area, which is the `#main-content` the skip link jumps to. Anyone who is not an administrator sees a notice instead
 * of the section; the backend answers 403 to them in any case.
 */
export function AdminShell({ children }: { children: React.ReactNode }) {
  const [lang] = useLang();
  const pathname = usePathname() ?? '';
  const { me, loading } = useAuth();

  return (
    <div className="min-h-[100dvh] bg-background text-foreground md:grid md:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="border-b border-border bg-surface md:sticky md:top-0 md:flex md:h-[100dvh] md:flex-col md:self-start md:overflow-y-auto md:border-b-0 md:border-r">
        <div className="flex items-center gap-3 px-4 py-3 md:py-5">
          <FptLogo className="h-7" />
          <span className="text-sm font-bold text-foreground-secondary">{t(lang, 'admin.shell.title')}</span>
        </div>
        <nav aria-label={t(lang, 'admin.nav.label')} className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-1 md:flex-col md:overflow-visible md:pb-3">
          {NAV_GROUPS.map((group) => (
            <React.Fragment key={group.id}>
              {group.label && <p className="hidden px-3 pb-1 pt-4 text-xs font-semibold text-foreground-muted md:block">{t(lang, group.label)}</p>}
              {ADMIN_NAV.filter((item) => item.group === group.id).map((item) => {
                const Icon = ICONS[item.href] ?? LayoutDashboard;
                const active = isActiveNav(pathname, item);
                return (
                  <Link key={item.href} href={item.href} aria-current={active ? 'page' : undefined} className={`${LINK} ${active ? 'bg-surface-raised text-foreground' : IDLE}`}>
                    <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                    {t(lang, item.label)}
                  </Link>
                );
              })}
            </React.Fragment>
          ))}
          <Link href="/" className={`${LINK} ${IDLE} md:mt-auto`}>
            <ArrowLeft className="h-4 w-4 shrink-0" aria-hidden="true" />
            {t(lang, 'admin.back')}
          </Link>
        </nav>
      </aside>
      <main id="main-content" tabIndex={-1} className="mx-auto w-full min-w-0 max-w-6xl space-y-6 px-4 py-6 focus:outline-none sm:px-6">
        {loading ? null : me?.can_admin ? (
          children
        ) : (
          <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.forbidden')}</p>
        )}
      </main>
    </div>
  );
}
