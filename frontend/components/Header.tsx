'use client';

import React from 'react';
import { useAuth } from '../context/AuthContext';
import { t, useLang } from '../lib/i18n';

interface HeaderProps {
  currentAgent?: string;
}

/** There is no header bar: the page starts at the top. The only thing that lives up here is the Sign in pill, floating in the
 *  top-right corner for a guest who can sign in (<main> in app/page.tsx is the positioned parent). Theme, language and
 *  sign-out live in the settings menu at the foot of the sidebar (components/user); the command palette opens with
 *  Cmd/Ctrl+K. */
export const Header: React.FC<HeaderProps> = () => {
  const [lang] = useLang();
  const { isGuest, config, openAuthModal } = useAuth();

  if (!isGuest || !config.login_enabled) return null;

  return (
    <div className="absolute right-0 top-0 z-40 flex h-12 items-center px-4 sm:px-5 select-none">
      <button
        type="button"
        onClick={() => openAuthModal('signin')}
        className="rounded-full bg-accent-primary/10 px-5 py-2 text-sm font-medium text-accent-primary hover:bg-accent-primary/20 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
      >
        {t(lang, 'user.signIn')}
      </button>
    </div>
  );
};
