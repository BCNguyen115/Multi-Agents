'use client';

import { useSyncExternalStore } from 'react';
import { en } from './locales/en';
import { vi } from './locales/vi';
import type { MessageKey } from './locales/vi';

/**
 * Interface language (Vietnamese or English) for the application chrome: sign-in, header, chat box, upload and streaming
 * messages. The dashboards have their own dictionary (lib/uiText.ts, driven by the data's language); answers come in the
 * language of the question. Add a string by adding the same key to BOTH dictionaries (the type forces it).
 */
export type Lang = 'vi' | 'en';

export type { MessageKey };

const DICTIONARIES: Record<Lang, Record<MessageKey, string>> = { vi, en };
export const LANG_KEY = 'lang';

/** A chat that still carries the default title, in whichever language it was created (the title is then replaced by the first question). */
export const isDefaultChatTitle = (title: string): boolean =>
  title === vi['chat.newTitle'] || title === en['chat.newTitle'] || title === 'New chat';

/** Text for ``key`` in ``lang`` with ``{name}`` placeholders filled in. */
export function t(lang: Lang, key: MessageKey, vars: Record<string, string | number> = {}): string {
  return DICTIONARIES[lang][key].replace(/\{(\w+)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole));
}

export function detectLang(saved: string | null, browserLanguage: string | undefined): Lang {
  if (saved === 'vi' || saved === 'en') return saved;
  return browserLanguage?.toLowerCase().startsWith('en') ? 'en' : 'vi'; // Vietnamese unless the browser clearly asks for English
}

// A tiny external store so every component re-renders together when the language changes.
let current: Lang = 'vi';
let initialised = false;
const listeners = new Set<() => void>();

function init(): void {
  if (initialised || typeof window === 'undefined') return;
  initialised = true;
  try {
    current = detectLang(localStorage.getItem(LANG_KEY), navigator.language);
  } catch {
    current = detectLang(null, navigator.language);
  }
  document.documentElement.lang = current;
}

export function getLang(): Lang {
  init();
  return current;
}

export function setLang(lang: Lang): void {
  init();
  current = lang;
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* the choice just does not persist */
  }
  if (typeof document !== 'undefined') document.documentElement.lang = lang;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** ``[lang, setLang]``; renders in Vietnamese on the server and switches on the client if the user chose otherwise. */
export function useLang(): [Lang, (lang: Lang) => void] {
  const lang = useSyncExternalStore(subscribe, getLang, () => 'vi' as Lang);
  return [lang, setLang];
}
