'use client';

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { apiFetch } from '../lib/apiFetch';
import {
  NO_AUTH,
  fetchAuthConfig,
  fetchMe,
  logoutRequest,
  setAuthRequiredHandler,
  LOGIN_PATH,
  type AuthConfig,
  type Me,
} from '../lib/authClient';
import { clearLocalConversations } from '../lib/conversationSync';
import { useLang, type Lang } from '../lib/i18n';

export type Theme = 'dark' | 'light' | 'system';
export type UserRole = 'admin' | 'approver' | 'member' | 'guest';
export type AuthTab = 'signin' | 'signup';

export interface AuthUser {
  id: string;
  /** Display name; empty for a guest (the UI shows its own word for it). */
  name: string;
  role: UserRole;
}

export interface RegisterData {
  username: string;
  password: string;
  displayName?: string;
}

export interface ResetData {
  username: string;
  recoveryKey: string;
  newPassword: string;
}

interface AuthContextValue {
  user: AuthUser;
  isAuthenticated: boolean;
  isGuest: boolean;
  /** True until the first answer of the backend about the session. */
  loading: boolean;
  /** The raw answer of `/api/auth/me`, for code that needs roles and tenant (`null` for a guest). */
  me: Me | null;
  config: AuthConfig;
  theme: Theme;
  resolvedTheme: 'dark' | 'light';
  language: Lang;
  login: (username: string, password: string) => Promise<void>;
  /** Creates the account (the browser is now signed in). Resolves with the recovery key, which must be shown before `finishSignIn`. */
  register: (data: RegisterData) => Promise<{ recoveryKey: string }>;
  /** Forgot password: new password from the recovery key. Resolves with the NEW recovery key (the old one is spent). */
  resetPassword: (data: ResetData) => Promise<{ recoveryKey: string }>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  /** Reload with the new session, after the recovery key has been seen. */
  finishSignIn: () => void;
  logout: () => Promise<void>;
  setTheme: (theme: Theme) => void;
  setLanguage: (language: Lang) => void;
  authModal: { open: boolean; tab: AuthTab };
  openAuthModal: (tab?: AuthTab) => void;
  closeAuthModal: () => void;
  changePasswordOpen: boolean;
  openChangePassword: () => void;
  closeChangePassword: () => void;
  approvalsOpen: boolean;
  openApprovals: () => void;
  closeApprovals: () => void;
}

export const THEME_KEY = 'theme';
const GUEST: AuthUser = { id: 'guest', name: '', role: 'guest' };

const AuthContext = createContext<AuthContextValue | null>(null);

function readTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    return saved === 'light' || saved === 'system' ? saved : 'dark';
  } catch {
    return 'dark';
  }
}

function resolve(theme: Theme): 'dark' | 'light' {
  if (theme !== 'system') return theme;
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

/** Puts the resolved theme on <html> the way the rest of the app (CSS variables, `useIsDark`) reads it. */
function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  const next = resolve(theme);
  root.classList.toggle('dark', next === 'dark');
  root.classList.toggle('light', next === 'light');
  root.setAttribute('data-theme', next);
}

function roleOf(me: Me): UserRole {
  if (me.roles.includes('admin')) return 'admin';
  return me.can_approve ? 'approver' : 'member';
}

/** The message of a failed auth call: what the backend said, else the status. */
async function failure(response: Response): Promise<Error> {
  const data = await response.json().catch(() => ({}));
  return new Error(typeof data.detail === 'string' && data.detail ? data.detail : `HTTP ${response.status}`);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguageState] = useLang();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<AuthConfig>(NO_AUTH);
  const [theme, setThemeState] = useState<Theme>('dark');
  const [authModal, setAuthModal] = useState<{ open: boolean; tab: AuthTab }>({ open: false, tab: 'signin' });

  const openAuthModal = useCallback((tab: AuthTab = 'signin') => setAuthModal({ open: true, tab }), []);
  const closeAuthModal = useCallback(() => setAuthModal((prev) => ({ ...prev, open: false })), []);
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);
  const openChangePassword = useCallback(() => setChangePasswordOpen(true), []);
  const closeChangePassword = useCallback(() => setChangePasswordOpen(false), []);
  const [approvalsOpen, setApprovalsOpen] = useState(false);
  const openApprovals = useCallback(() => setApprovalsOpen(true), []);
  const closeApprovals = useCallback(() => setApprovalsOpen(false), []);

  // Who is signed in, and what the dialog may offer. A 401 (backend needs a login) makes the visitor a guest and asks for one.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchAuthConfig(),
      fetchMe().catch((error) => {
        console.warn('Could not check the session', error);
        return undefined;
      }),
    ]).then(([cfg, current]) => {
      if (cancelled) return;
      setConfig(cfg);
      if (current !== undefined) setMe(current);
      setLoading(false);
      if (current === null && window.location.pathname !== LOGIN_PATH) {
        if (cfg.login_enabled) openAuthModal('signin');
        else if (window.location.pathname !== LOGIN_PATH) window.location.assign(LOGIN_PATH); // identity provider: its own login page
      }
    });
    return () => {
      cancelled = true;
    };
  }, [openAuthModal]);

  // Any API call that comes back 401 later asks for a sign-in the same way.
  useEffect(() => {
    setAuthRequiredHandler(() => {
      if (window.location.pathname === LOGIN_PATH) return; // the full-page login is already what is on screen
      setMe(null);
      if (config.login_enabled) openAuthModal('signin');
      else if (window.location.pathname !== LOGIN_PATH) window.location.assign(LOGIN_PATH);
    });
    return () => setAuthRequiredHandler(null);
  }, [config.login_enabled, openAuthModal]);

  // Theme: remembered in the browser, "system" follows the OS live.
  useEffect(() => {
    const saved = readTheme();
    setThemeState(saved);
    applyTheme(saved);
  }, []);

  useEffect(() => {
    if (theme !== 'system') return undefined;
    const query = window.matchMedia('(prefers-color-scheme: light)');
    const onChange = () => applyTheme('system');
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* private mode: the choice lasts for this page only */
    }
    applyTheme(next);
  }, []);

  const setLanguage = useCallback(
    (next: Lang) => {
      if (next !== language) setLanguageState(next);
    },
    [language, setLanguageState]
  );

  // A new session (or none) changes whose chats this browser may show, so the page starts clean instead of patching its state.
  const login = useCallback(async (username: string, password: string) => {
    const response = await apiFetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
    if (!response.ok) throw await failure(response);
    window.location.reload();
  }, []);

  // Sign-up and reset sign the browser in too, but the recovery key is shown once: the reload waits for `finishSignIn`.
  const register = useCallback(async ({ username, password, displayName }: RegisterData) => {
    const response = await apiFetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, display_name: displayName ?? '' }),
    });
    if (!response.ok) throw await failure(response);
    const data = await response.json();
    return { recoveryKey: String(data.recovery_key ?? '') };
  }, []);

  const resetPassword = useCallback(async ({ username, recoveryKey, newPassword }: ResetData) => {
    const response = await apiFetch('/api/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, recovery_key: recoveryKey, new_password: newPassword }),
    });
    if (!response.ok) throw await failure(response);
    const data = await response.json();
    return { recoveryKey: String(data.recovery_key ?? '') };
  }, []);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    const response = await apiFetch('/api/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    if (!response.ok) throw await failure(response);
  }, []);

  const finishSignIn = useCallback(() => window.location.reload(), []);

  const logout = useCallback(async () => {
    if (me?.authenticated) clearLocalConversations(me.user); // the next person on this browser must not see these chats
    await logoutRequest();
    window.location.reload();
  }, [me]);

  const user: AuthUser = useMemo(
    () => (me?.authenticated ? { id: me.user, name: me.name || me.user, role: roleOf(me) } : GUEST),
    [me]
  );

  // Memoised: every consumer re-renders when this object changes, so it only changes when something it holds does
  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: Boolean(me?.authenticated),
      isGuest: !me?.authenticated,
      loading,
      me,
      config,
      theme,
      resolvedTheme: resolve(theme),
      language,
      login,
      register,
      resetPassword,
      changePassword,
      finishSignIn,
      logout,
      setTheme,
      setLanguage,
      authModal,
      openAuthModal,
      closeAuthModal,
      changePasswordOpen,
      openChangePassword,
      closeChangePassword,
      approvalsOpen,
      openApprovals,
      closeApprovals,
    }),
    [
      user, me, loading, config, theme, language, login, register, resetPassword, changePassword, finishSignIn, logout,
      setTheme, setLanguage, authModal, openAuthModal, closeAuthModal, changePasswordOpen, openChangePassword, closeChangePassword,
      approvalsOpen, openApprovals, closeApprovals,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>');
  return context;
}
