'use client';

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronLeft, ChevronRight, Globe, KeyRound, LogIn, LogOut, Monitor, Moon, Palette, Sun, UserPlus } from 'lucide-react';
import { useAuth, type Theme } from '../../context/AuthContext';
import { t, useLang, type Lang, type MessageKey } from '../../lib/i18n';

interface SettingsMenuProps {
  /** The button that opened the menu: the menu sits next to it and clicks on it do not count as "outside". */
  anchor: HTMLElement | null;
  /** `top` opens above the anchor (expanded sidebar), `right` beside it (collapsed sidebar). */
  placement: 'top' | 'right';
  onClose: () => void;
}

type View = 'root' | 'theme' | 'language';

const THEMES: { id: Theme; label: MessageKey; Icon: typeof Sun }[] = [
  { id: 'dark', label: 'user.theme.dark', Icon: Moon },
  { id: 'light', label: 'user.theme.light', Icon: Sun },
  { id: 'system', label: 'user.theme.system', Icon: Monitor },
];
const LANGUAGES: { id: Lang; label: MessageKey }[] = [
  { id: 'vi', label: 'user.lang.vi' },
  { id: 'en', label: 'user.lang.en' },
];

const ITEM =
  'flex items-center gap-3 w-full px-3 py-2.5 rounded-xl text-sm text-foreground text-left transition-colors cursor-pointer hover:bg-surface-raised focus-visible:outline-none focus-visible:bg-surface-raised focus-visible:ring-2 focus-visible:ring-accent-primary/40';
const ICON = 'w-[18px] h-[18px] shrink-0 text-foreground-secondary';

export function SettingsMenu({ anchor, placement, onClose }: SettingsMenuProps) {
  const [lang] = useLang();
  const { theme, setTheme, language, setLanguage, isGuest, isAuthenticated, config, openAuthModal, openChangePassword, logout } = useAuth();
  const [view, setView] = useState<View>('root');
  const [position, setPosition] = useState<{ left: number; bottom: number } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Next to the anchor; fixed positioning because the sidebar clips anything inside it.
  const place = useCallback(() => {
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    setPosition(
      placement === 'right'
        ? { left: rect.right + 8, bottom: window.innerHeight - rect.bottom }
        : { left: rect.left, bottom: window.innerHeight - rect.top + 8 }
    );
  }, [anchor, placement]);

  useLayoutEffect(() => {
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [place]);

  // Close on a click outside and on Escape (back to the anchor so keyboard users keep their place).
  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !anchor?.contains(target)) onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        if (view !== 'root') setView('root');
        else {
          onClose();
          anchor?.focus();
        }
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [anchor, onClose, view]);

  // Focus the first item whenever the view changes.
  useEffect(() => {
    menuRef.current?.querySelector<HTMLElement>('[role^="menuitem"]')?.focus();
  }, [view, position]);

  const onMenuKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? []);
    if (!items.length) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next = event.key === 'ArrowDown' ? (index + 1) % items.length : (index - 1 + items.length) % items.length;
    items[next].focus();
  };

  if (typeof document === 'undefined' || !position) return null;

  const currentTheme = THEMES.find((x) => x.id === theme) ?? THEMES[0];
  const currentLanguage = LANGUAGES.find((x) => x.id === language) ?? LANGUAGES[0];
  const ThemeIcon = currentTheme.Icon;

  const back = (
    <button type="button" role="menuitem" className={`${ITEM} font-medium`} onClick={() => setView('root')}>
      <ChevronLeft className={ICON} aria-hidden="true" />
      {t(lang, 'user.back')}
    </button>
  );

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      aria-label={t(lang, 'user.settings')}
      onKeyDown={onMenuKeyDown}
      style={{ position: 'fixed', left: position.left, bottom: position.bottom }}
      className="z-[70] w-64 max-w-[calc(100vw-1rem)] rounded-2xl border border-border-strong bg-surface p-1.5 shadow-lg animate-fade-in-scale"
    >
      {view === 'root' && (
        <>
          <button type="button" role="menuitem" className={ITEM} onClick={() => setView('theme')} aria-haspopup="menu">
            <Palette className={ICON} aria-hidden="true" />
            <span className="flex-1">{t(lang, 'user.menu.theme')}</span>
            <span className="flex items-center gap-1 text-xs text-foreground-muted">
              <ThemeIcon className="w-3.5 h-3.5" aria-hidden="true" />
              {t(lang, currentTheme.label)}
            </span>
            <ChevronRight className="w-4 h-4 text-foreground-muted" aria-hidden="true" />
          </button>
          <button type="button" role="menuitem" className={ITEM} onClick={() => setView('language')} aria-haspopup="menu">
            <Globe className={ICON} aria-hidden="true" />
            <span className="flex-1">{t(lang, 'user.menu.language')}</span>
            <span className="text-xs text-foreground-muted">{t(lang, currentLanguage.label)}</span>
            <ChevronRight className="w-4 h-4 text-foreground-muted" aria-hidden="true" />
          </button>

          {(config.login_enabled || isAuthenticated) && <div role="separator" className="my-1.5 h-px bg-border" />}

          {isGuest && config.login_enabled && (
            <>
              <button type="button" role="menuitem" className={ITEM} onClick={() => { onClose(); openAuthModal('signin'); }}>
                <LogIn className={ICON} aria-hidden="true" />
                {t(lang, 'user.signIn')}
              </button>
              <button type="button" role="menuitem" className={ITEM} onClick={() => { onClose(); openAuthModal('signup'); }}>
                <UserPlus className={ICON} aria-hidden="true" />
                {t(lang, 'user.register')}
              </button>
            </>
          )}
          {isAuthenticated && config.registration_enabled && (
            <button type="button" role="menuitem" className={ITEM} onClick={() => { onClose(); openChangePassword(); }}>
              <KeyRound className={ICON} aria-hidden="true" />
              {t(lang, 'user.changePassword')}
            </button>
          )}
          {isAuthenticated && (
            <button type="button" role="menuitem" className={ITEM} onClick={() => { onClose(); void logout(); }}>
              <LogOut className={ICON} aria-hidden="true" />
              {t(lang, 'user.signOut')}
            </button>
          )}
        </>
      )}

      {view === 'theme' && (
        <>
          {back}
          <div role="separator" className="my-1.5 h-px bg-border" />
          {THEMES.map(({ id, label, Icon }) => (
            <button key={id} type="button" role="menuitemradio" aria-checked={theme === id} className={ITEM} onClick={() => setTheme(id)}>
              <Icon className={ICON} aria-hidden="true" />
              <span className="flex-1">{t(lang, label)}</span>
              {theme === id && <Check className="w-4 h-4 text-accent-primary" aria-hidden="true" />}
            </button>
          ))}
        </>
      )}

      {view === 'language' && (
        <>
          {back}
          <div role="separator" className="my-1.5 h-px bg-border" />
          {LANGUAGES.map(({ id, label }) => (
            <button key={id} type="button" role="menuitemradio" aria-checked={language === id} className={ITEM} onClick={() => setLanguage(id)}>
              <span className="flex-1 pl-[30px]">{t(lang, label)}</span>
              {language === id && <Check className="w-4 h-4 text-accent-primary" aria-hidden="true" />}
            </button>
          ))}
        </>
      )}
    </div>,
    document.body
  );
}
