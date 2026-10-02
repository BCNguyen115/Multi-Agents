'use client';

import React from 'react';
import { LayoutDashboard, Loader2 } from 'lucide-react';
import { t, useLang } from '../../lib/i18n';

export const DashboardSkeleton: React.FC = () => {
  const [lang] = useLang();
  return (
    <div
      data-testid="dashboard-container"
      className="dynamic-dashboard-container w-full my-4 p-5 bg-surface rounded-2xl border border-border space-y-6 min-h-dashboard transition-colors select-none"
    >
      {/* Header Skeleton synchronized 1:1 with DynamicDashboard */}
      <div className="flex items-center justify-between border-b border-border pb-4">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 bg-accent-primary/10 text-accent-primary rounded-xl">
            <LayoutDashboard className="w-5 h-5 animate-pulse" />
          </div>
          <div className="space-y-1.5">
            <div className="h-4 w-64 rounded-md animate-shimmer" />
            <div className="h-3 w-80 rounded-md animate-shimmer" style={{ animationDelay: '150ms' }} />
          </div>
        </div>
        <div className="flex items-center gap-2 bg-accent-primary/10 text-accent-primary px-3 py-1.5 rounded-lg text-xs font-medium border border-accent-primary/20">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-accent-primary" />
          <span className="font-sans">{t(lang, 'dash.loading')}</span>
        </div>
      </div>

      {/* KPI Cards Skeleton (4 Columns, exactly 112px height matching real KPI cards) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((idx) => (
          <div
            key={idx}
            className="p-4 bg-surface-raised/40 border border-border rounded-xl space-y-2 h-kpi min-h-kpi flex flex-col justify-between"
          >
            <div className="flex justify-between items-center">
              <div className="h-3 w-24 rounded animate-shimmer" />
              <div className="h-6 w-6 rounded-lg animate-shimmer" />
            </div>
            <div className="h-7 w-32 rounded animate-shimmer" style={{ animationDelay: `${idx * 100}ms` }} />
            <div className="h-3 w-20 rounded animate-shimmer" />
          </div>
        ))}
      </div>

      {/* Filter Slicers Skeleton */}
      <div className="flex items-center gap-2 p-3 bg-surface-raised/30 rounded-xl border border-border h-12">
        <div className="h-3 w-16 rounded animate-shimmer" />
        <div className="h-7 w-28 rounded-lg animate-shimmer" />
        <div className="h-7 w-32 rounded-lg animate-shimmer" />
      </div>

      {/* Charts Skeleton (2 Columns, exactly 380px height matching real charts) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-chart">
        <div className="col-span-12 lg:col-span-7 p-4 bg-surface-raised/40 border border-border rounded-xl h-chart min-h-chart flex flex-col justify-between">
          <div className="h-4 w-40 rounded mb-3 animate-shimmer" />
          <div className="flex-1 rounded-lg flex items-end justify-around p-4 gap-2 bg-surface-raised/20">
            {[33, 66, 100, 50, 80].map((h, i) => (
              <div
                key={i}
                className="w-10 rounded-t animate-shimmer"
                style={{ height: `${h}%`, animationDelay: `${i * 100}ms` }}
              />
            ))}
          </div>
        </div>

        <div className="col-span-12 lg:col-span-5 p-4 bg-surface-raised/40 border border-border rounded-xl h-chart min-h-chart flex flex-col justify-between">
          <div className="h-4 w-40 rounded mb-3 animate-shimmer" />
          <div className="flex-1 rounded-lg flex items-center justify-center bg-surface-raised/20">
            <div className="relative w-36 h-36 rounded-full border-4 border-surface-raised flex items-center justify-center animate-shimmer">
              <div className="w-20 h-20 rounded-full bg-surface" />
            </div>
          </div>
        </div>
      </div>

      {/* Table Skeleton (min-h-table) */}
      <div className="p-4 bg-surface-raised/40 border border-border rounded-xl min-h-table space-y-3">
        <div className="h-4 w-48 rounded animate-shimmer" />
        <div className="space-y-2 pt-2">
          <div className="h-9 rounded-lg animate-shimmer" />
          <div className="h-7 rounded-md animate-shimmer" />
          <div className="h-7 rounded-md animate-shimmer" />
          <div className="h-7 rounded-md animate-shimmer" />
        </div>
      </div>
    </div>
  );
};
