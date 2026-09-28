'use client';

import React from 'react';
import { LayoutDashboard, Loader2 } from 'lucide-react';

export const DashboardSkeleton: React.FC = () => {
  return (
    <div
      data-testid="dashboard-container"
      className="w-full my-4 p-5 bg-surface/90 rounded-2xl border border-border shadow-sm space-y-6 min-h-[500px] transition-colors"
    >
      {/* Header Skeleton synchronized with DynamicDashboard */}
      <div className="flex items-center justify-between border-b border-border pb-4">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 bg-accent-primary/10 text-accent-primary rounded-xl">
            <LayoutDashboard className="w-5 h-5 animate-pulse" />
          </div>
          <div className="space-y-1.5">
            <div className="h-4 w-64 bg-surface-raised rounded-md animate-pulse" />
            <div className="h-3 w-80 bg-surface-raised/60 rounded-md animate-pulse" style={{ animationDelay: '150ms' }} />
          </div>
        </div>
        <div className="flex items-center gap-2 bg-accent-primary/10 text-accent-primary px-3 py-1.5 rounded-lg text-xs font-medium border border-accent-primary/20">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-accent-primary" />
          <span className="font-sans">Đang khởi tạo Dashboard & DuckDB...</span>
        </div>
      </div>

      {/* KPI Cards Skeleton (4 Columns) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((idx) => (
          <div
            key={idx}
            className="p-4 bg-surface-raised/40 border border-border rounded-xl space-y-3"
          >
            <div className="flex justify-between items-center">
              <div className="h-3 w-24 bg-surface-raised rounded animate-pulse" />
              <div className="h-6 w-6 bg-surface-raised rounded-lg animate-pulse" />
            </div>
            <div className="h-7 w-32 bg-surface-raised rounded animate-pulse" style={{ animationDelay: `${idx * 100}ms` }} />
            <div className="h-3 w-20 bg-surface-raised/60 rounded animate-pulse" />
          </div>
        ))}
      </div>

      {/* Filter Slicers Skeleton */}
      <div className="flex items-center gap-2 p-3 bg-surface-raised/30 rounded-xl border border-border">
        <div className="h-3 w-16 bg-surface-raised rounded animate-pulse" />
        <div className="h-7 w-28 bg-surface-raised rounded-lg animate-pulse" />
        <div className="h-7 w-32 bg-surface-raised rounded-lg animate-pulse" />
      </div>

      {/* Charts Skeleton (2 Columns) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[360px]">
        <div className="col-span-12 lg:col-span-7 p-4 bg-surface-raised/40 border border-border rounded-2xl min-h-[360px] flex flex-col justify-between">
          <div className="h-4 w-40 bg-surface-raised rounded mb-3 animate-pulse" />
          <div className="h-64 bg-surface-raised/20 rounded-lg flex items-end justify-around p-4 gap-2">
            {[33, 66, 100, 50, 80].map((h, i) => (
              <div
                key={i}
                className="w-8 bg-surface-raised rounded-t animate-pulse"
                style={{ height: `${h}%`, animationDelay: `${i * 100}ms` }}
              />
            ))}
          </div>
        </div>

        <div className="col-span-12 lg:col-span-5 p-4 bg-surface-raised/40 border border-border rounded-2xl min-h-[360px] flex flex-col justify-between">
          <div className="h-4 w-40 bg-surface-raised rounded mb-3 animate-pulse" />
          <div className="h-64 bg-surface-raised/20 rounded-lg flex items-center justify-center">
            <div className="relative w-36 h-36 rounded-full border-8 border-surface-raised flex items-center justify-center animate-pulse">
              <div className="w-20 h-20 rounded-full bg-surface" />
            </div>
          </div>
        </div>
      </div>

      {/* Table Skeleton */}
      <div className="p-4 bg-surface-raised/40 border border-border rounded-xl min-h-[300px] space-y-3">
        <div className="h-4 w-48 bg-surface-raised rounded animate-pulse" />
        <div className="space-y-2">
          <div className="h-8 bg-surface-raised rounded animate-pulse" />
          <div className="h-6 bg-surface-raised/60 rounded animate-pulse" />
          <div className="h-6 bg-surface-raised/60 rounded animate-pulse" />
          <div className="h-6 bg-surface-raised/60 rounded animate-pulse" />
        </div>
      </div>
    </div>
  );
};
