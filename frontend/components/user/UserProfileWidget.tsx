'use client';

import React, { useCallback, useRef, useState } from 'react';
import { Settings } from 'lucide-react';
import { useAuth, type UserRole } from '../../context/AuthContext';
import { t, useLang, type MessageKey } from '../../lib/i18n';
import { SettingsMenu } from './SettingsMenu';

interface UserProfileWidgetProps {
  /** The sidebar is collapsed: settings and avatar are stacked and centered instead of laid out in a row. */
  isCollapsed?: boolean;
}

const ROLE_LABEL: Record<UserRole, MessageKey> = {
  admin: 'user.role.admin',
  approver: 'user.role.approver',
  member: 'user.role.member',
  guest: 'user.guestStatus',
};

/** Avatar, name, status and the settings button at the foot of the sidebar. */
export function UserProfileWidget({ isCollapsed = false }: UserProfileWidgetProps) {
  const [lang] = useLang();
  const { user, isGuest } = useAuth();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const gearRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    gearRef.current?.focus();
  }, []);

  const displayName = isGuest ? t(lang, 'user.guest') : user.name;
  const status = t(lang, ROLE_LABEL[user.role]);
  const initial = (displayName.trim()[0] ?? '?').toUpperCase();

  const avatar = (
    <div
      aria-hidden="true"
      className={`w-8 h-8 shrink-0 rounded-full flex items-center justify-center text-sm font-semibold select-none ${
        isGuest ? 'bg-surface-overlay text-foreground-secondary' : 'bg-accent-primary text-white'
      }`}
    >
      {initial}
    </div>
  );

  const gear = (
    <button
      ref={gearRef}
      type="button"
      onClick={() => setOpen((v) => !v)}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-label={t(lang, 'user.settings')}
      title={t(lang, 'user.settings')}
      className="w-9 h-9 shrink-0 rounded-full flex items-center justify-center text-foreground-secondary hover:text-foreground hover:bg-surface-raised transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
    >
      <Settings className="w-[18px] h-[18px]" aria-hidden="true" />
    </button>
  );

  return (
    <div ref={containerRef} data-testid="user-profile-widget">
      {isCollapsed ? (
        <div className="flex flex-col items-center gap-2 py-1">
          {gear}
          <span title={`${displayName} · ${status}`}>{avatar}</span>
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-2xl px-2 py-1.5">
          {avatar}
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground" title={displayName}>
              {displayName}
            </p>
            <p className="truncate text-xs text-foreground-muted">{status}</p>
          </div>
          {gear}
        </div>
      )}
      {open && <SettingsMenu anchor={containerRef.current} placement={isCollapsed ? 'right' : 'top'} onClose={close} />}
    </div>
  );
}
