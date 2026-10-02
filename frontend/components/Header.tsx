'use client';

import React, { useState, useEffect } from 'react';
import { Sun, Moon, Search, LogOut } from 'lucide-react';
import { t, useLang } from '../lib/i18n';

interface HeaderProps {
  currentAgent?: string;
  onOpenCommandPalette?: () => void;
  /** Signed-in user (only when the backend requires a login) and the sign-out action. */
  userName?: string | null;
  onLogout?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  onOpenCommandPalette,
  userName,
  onLogout,
}) => {
  const [isDark, setIsDark] = useState(true);
  const [lang, setLang] = useLang();

  useEffect(() => {
    const savedTheme = localStorage.getItem('theme');
    const dark = savedTheme !== 'light';
    setIsDark(dark);
  }, []);

  const toggleTheme = () => {
    const next = !isDark;
    setIsDark(next);
    if (next) {
      document.documentElement.classList.add('dark');
      document.documentElement.classList.remove('light');
      document.documentElement.setAttribute('data-theme', 'dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      document.documentElement.classList.add('light');
      document.documentElement.setAttribute('data-theme', 'light');
      localStorage.setItem('theme', 'light');
    }
  };

  return (
    <header className="glass-header sticky top-0 z-40 h-12 flex items-center justify-between px-4 sm:px-5 shrink-0 select-none border-b border-border bg-surface/80 backdrop-blur-md">
      {/* Left side: Clean & Uncluttered Workspace Brand */}
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="font-semibold text-sm tracking-tight text-foreground">
          
        </span>
      </div>

      {/* Right controls: Command Palette, Theme Toggle */}
      <div className="flex items-center gap-1.5 sm:gap-2">
        {/* Command Palette Trigger Pill */}
        <button
          type="button"
          onClick={onOpenCommandPalette}
          className="flex items-center gap-2 px-2.5 py-1 text-xs text-foreground-muted hover:text-foreground bg-surface-raised hover:bg-surface-overlay border border-border rounded-lg transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
          title={t(lang, 'header.commandPalette')}
        >
          <Search className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">{t(lang, 'header.searchCommands')}</span>
          <kbd className="px-1.5 py-0.2 text-2xs font-mono rounded bg-surface border border-border text-foreground-muted">
            ⌘K
          </kbd>
        </button>

        {/* Theme Toggle with Rotation Effect */}
        <button
          type="button"
          onClick={toggleTheme}
          className="p-1.5 rounded-lg hover:bg-surface-raised text-foreground-muted hover:text-foreground transition-all duration-200 cursor-pointer group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
          title={isDark ? t(lang, 'header.themeLight') : t(lang, 'header.themeDark')}
          aria-label={isDark ? t(lang, 'header.themeLight') : t(lang, 'header.themeDark')}
        >
          {isDark ? (
            <Sun className="w-4 h-4 transition-transform duration-300 group-hover:rotate-45 text-foreground-secondary" />
          ) : (
            <Moon className="w-4 h-4 transition-transform duration-300 group-hover:-rotate-12 text-foreground-secondary" />
          )}
        </button>

        <button
          type="button"
          onClick={() => setLang(lang === 'vi' ? 'en' : 'vi')}
          className="px-2 py-1 rounded-lg text-xs font-semibold text-foreground-muted hover:text-foreground hover:bg-surface-raised transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
          title={t(lang, 'lang.switch')}
          aria-label={t(lang, 'lang.switch')}
        >
          {lang === 'vi' ? 'EN' : 'VI'}
        </button>

        {userName && (
          <div className="flex items-center gap-1.5 pl-2 ml-0.5 border-l border-border">
            <span className="hidden sm:inline text-xs font-medium text-foreground-secondary max-w-32 truncate" title={userName}>
              {userName}
            </span>
            <button
              type="button"
              onClick={onLogout}
              className="p-1.5 rounded-lg hover:bg-surface-raised text-foreground-muted hover:text-foreground transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
              title={t(lang, 'header.logout')}
              aria-label={t(lang, 'header.logout')}
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
