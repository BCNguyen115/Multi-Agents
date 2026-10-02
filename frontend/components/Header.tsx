'use client';

import React from 'react';
import { Search } from 'lucide-react';
import { t, useLang } from '../lib/i18n';

interface HeaderProps {
  currentAgent?: string;
  onOpenCommandPalette?: () => void;
}

/** Theme, language and sign-out live in the settings menu at the foot of the sidebar (components/user). */
export const Header: React.FC<HeaderProps> = ({ onOpenCommandPalette }) => {
  const [lang] = useLang();

  return (
    <header className="glass-header sticky top-0 z-40 h-12 flex items-center justify-between px-4 sm:px-5 shrink-0 select-none border-b border-border bg-surface/80 backdrop-blur-md">
      {/* Left side: Clean & Uncluttered Workspace Brand */}
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="font-semibold text-sm tracking-tight text-foreground"></span>
      </div>

      {/* Right controls: Command Palette */}
      <div className="flex items-center gap-1.5 sm:gap-2">
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
      </div>
    </header>
  );
};
