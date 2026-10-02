'use client';

import { useState, useEffect } from 'react';

export function useIsDark(): boolean {
  const [isDark, setIsDark] = useState<boolean>(true);

  useEffect(() => {
    const check = () => {
      const isDarkMode =
        document.documentElement.classList.contains('dark') ||
        document.documentElement.getAttribute('data-theme') === 'dark';
      setIsDark(isDarkMode);
    };

    check();

    const observer = new MutationObserver(check);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'data-theme'],
    });

    return () => observer.disconnect();
  }, []);

  return isDark;
}
