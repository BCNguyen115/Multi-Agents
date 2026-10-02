import React from 'react';
import './globals.css';
import { SkipLink } from '../components/SkipLink';
import { AuthProvider } from '../context/AuthContext';
import { AuthModal } from '../components/auth/AuthModal';
import { ChangePasswordDialog } from '../components/auth/ChangePasswordDialog';

export const metadata = {
  title: 'Multi-Agent Enterprise System',
  description: 'Enterprise Multi-Agent System Layer 1 Next.js App Router Frontend',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi" className="dark" suppressHydrationWarning>
      <head>
        {/* Prevent FOUC: apply dark class before paint */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var theme = localStorage.getItem('theme');
                  var light = theme === 'light' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: light)').matches);
                  if (light) {
                    document.documentElement.classList.remove('dark');
                    document.documentElement.classList.add('light');
                    document.documentElement.setAttribute('data-theme', 'light');
                  } else {
                    document.documentElement.classList.add('dark');
                    document.documentElement.classList.remove('light');
                    document.documentElement.setAttribute('data-theme', 'dark');
                  }
                } catch(e) {}
              })();
            `,
          }}
        />
      </head>
      <body className="bg-background min-h-screen font-sans antialiased text-foreground max-w-full overflow-x-hidden">
        <SkipLink />
        <AuthProvider>
          {children}
          <AuthModal />
          <ChangePasswordDialog />
        </AuthProvider>
      </body>
    </html>
  );
}
