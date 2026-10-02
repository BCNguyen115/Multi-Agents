'use client';

import React from 'react';
import { t, useLang } from '../lib/i18n';

/** First focusable element of every page: lets keyboard and screen-reader users jump past the sidebar to `#main-content`. */
export const SkipLink: React.FC = () => {
  const [lang] = useLang();
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:px-3 focus:py-2 focus:rounded-lg focus:bg-accent-primary focus:text-white focus:text-sm focus:font-medium"
    >
      {t(lang, 'app.skip')}
    </a>
  );
};
