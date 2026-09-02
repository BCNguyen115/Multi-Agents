import React from 'react';
import './globals.css';

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
    <html lang="vi">
      <body className="bg-slate-50 min-h-screen font-sans antialiased text-slate-900 max-w-full overflow-x-hidden">
        {children}
      </body>
    </html>
  );
}
