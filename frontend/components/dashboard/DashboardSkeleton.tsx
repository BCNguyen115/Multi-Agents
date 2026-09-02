'use client';

import React from 'react';
import { LayoutDashboard, Loader2 } from 'lucide-react';

export const DashboardSkeleton: React.FC = () => {
  return (
    <div className="mt-4 p-5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm space-y-6 animate-pulse transition-colors">
      {/* Header Skeleton */}
      <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-4">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 bg-blue-100 dark:bg-blue-950/60 text-[#005697] dark:text-blue-400 rounded-xl">
            <LayoutDashboard className="w-5 h-5 animate-spin" />
          </div>
          <div>
            <div className="h-4 w-64 bg-slate-200 dark:bg-slate-700 rounded-md mb-1.5" />
            <div className="h-3 w-96 bg-slate-100 dark:bg-slate-800 rounded-md" />
          </div>
        </div>
        <div className="flex items-center space-x-2 bg-blue-50 dark:bg-blue-950/60 text-[#005697] dark:text-blue-300 px-3 py-1.5 rounded-full text-xs font-semibold">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>Đang tạo Dashboard...</span>
        </div>
      </div>

      {/* KPI Cards Skeleton (4 Columns) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((idx) => (
          <div key={idx} className="p-4 bg-slate-50 dark:bg-slate-800/80 border border-slate-200/80 dark:border-slate-700/80 rounded-xl space-y-2">
            <div className="flex justify-between items-center">
              <div className="h-3 w-24 bg-slate-200 dark:bg-slate-700 rounded" />
              <div className="h-4 w-4 bg-slate-200 dark:bg-slate-700 rounded-full" />
            </div>
            <div className="h-7 w-32 bg-slate-300 dark:bg-slate-600 rounded" />
            <div className="h-2.5 w-20 bg-slate-200 dark:bg-slate-700 rounded" />
          </div>
        ))}
      </div>

      {/* Filter Slicers Skeleton */}
      <div className="flex items-center gap-2 p-3 bg-slate-50/80 dark:bg-slate-800/50 rounded-xl border border-slate-100 dark:border-slate-800">
        <div className="h-3 w-16 bg-slate-300 dark:bg-slate-700 rounded" />
        <div className="h-7 w-28 bg-slate-200 dark:bg-slate-700 rounded-lg" />
        <div className="h-7 w-32 bg-slate-200 dark:bg-slate-700 rounded-lg" />
      </div>

      {/* Charts Skeleton (2 Columns with exact min-h-[360px]) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[360px]">
        <div className="col-span-12 lg:col-span-7 p-4 bg-slate-50 dark:bg-slate-800/80 border border-slate-200/80 dark:border-slate-700/80 rounded-2xl min-h-[360px] flex flex-col justify-between">
          <div className="h-4 w-40 bg-slate-200 dark:bg-slate-700 rounded mb-3" />
          <div className="h-64 bg-slate-200/60 dark:bg-slate-700/60 rounded-lg flex items-end justify-around p-4 gap-2">
            <div className="h-1/3 w-8 bg-slate-300/80 dark:bg-slate-600/80 rounded-t" />
            <div className="h-2/3 w-8 bg-slate-300/80 dark:bg-slate-600/80 rounded-t" />
            <div className="h-full w-8 bg-slate-300/80 dark:bg-slate-600/80 rounded-t" />
            <div className="h-1/2 w-8 bg-slate-300/80 dark:bg-slate-600/80 rounded-t" />
            <div className="h-4/5 w-8 bg-slate-300/80 dark:bg-slate-600/80 rounded-t" />
          </div>
        </div>

        <div className="col-span-12 lg:col-span-5 p-4 bg-slate-50 dark:bg-slate-800/80 border border-slate-200/80 dark:border-slate-700/80 rounded-2xl min-h-[360px] flex flex-col justify-between">
          <div className="h-4 w-40 bg-slate-200 dark:bg-slate-700 rounded mb-3" />
          <div className="h-64 bg-slate-200/60 dark:bg-slate-700/60 rounded-lg flex items-center justify-center">
            <div className="w-36 h-36 border-8 border-slate-300 dark:border-slate-600 border-t-[#005697] dark:border-t-blue-400 rounded-full animate-spin" />
          </div>
        </div>
      </div>

      {/* Table Skeleton (min-h-[300px]) */}
      <div className="p-4 bg-slate-50 dark:bg-slate-800/80 border border-slate-200/80 dark:border-slate-700/80 rounded-xl min-h-[300px] space-y-3">
        <div className="h-4 w-48 bg-slate-200 dark:bg-slate-700 rounded" />
        <div className="space-y-2">
          <div className="h-8 bg-slate-300/80 dark:bg-slate-600/80 rounded" />
          <div className="h-6 bg-slate-200/60 dark:bg-slate-700/60 rounded" />
          <div className="h-6 bg-slate-200/60 dark:bg-slate-700/60 rounded" />
          <div className="h-6 bg-slate-200/60 dark:bg-slate-700/60 rounded" />
        </div>
      </div>
    </div>
  );
};
