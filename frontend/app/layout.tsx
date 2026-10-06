import React from 'react';
// Self-hosted from npm (no request to Google at build or run time); each file carries latin, latin-ext and vietnamese
// faces with unicode-range, so a page only downloads the ones its text needs. Only the weights the UI uses.
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-sans/700.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import '@fontsource/ibm-plex-mono/700.css';
import './globals.css';
import { SkipLink } from '../components/SkipLink';
import { AuthProvider } from '../context/AuthContext';
import { AuthModal } from '../components/auth/AuthModal';
import { ChangePasswordDialog } from '../components/auth/ChangePasswordDialog';
import { ApprovalInbox } from '../components/ApprovalInbox';

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
          <ApprovalInbox />
        </AuthProvider>
      </body>
    </html>
  );
}
