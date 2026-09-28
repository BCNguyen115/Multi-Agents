'use client';

import React, { useState, useEffect } from 'react';
import { Sun, Moon, Cpu } from 'lucide-react';

interface HeaderProps {
  currentAgent?: string;
}

export const Header: React.FC<HeaderProps> = ({
  currentAgent = 'Multi-Agent Swarm',
}) => {
  const [isDark, setIsDark] = useState(true);

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
    <header className="glass-header sticky top-0 z-40 h-12 flex items-center justify-between px-5 shrink-0 select-none border-b border-border">
      {/* Left side: Active Agent & Live Gateway Health Indicator */}
      <div className="flex items-center gap-2.5">
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-raised border border-border text-xs text-foreground-secondary font-medium">
          <Cpu className="w-3.5 h-3.5 text-accent-primary" />
          <span className="font-semibold text-foreground">{currentAgent}</span>
        </div>
        <div className="hidden sm:flex items-center gap-1.5 text-xs font-mono text-foreground-muted">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>Gateway Active</span>
        </div>
      </div>

      {/* Right side: Theme Toggle */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={toggleTheme}
          className="p-1.5 rounded-lg hover:bg-surface-raised text-foreground-muted hover:text-foreground transition-colors duration-150 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
          title={isDark ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối'}
          aria-label="Toggle theme"
        >
          {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </div>
    </header>
  );
};

