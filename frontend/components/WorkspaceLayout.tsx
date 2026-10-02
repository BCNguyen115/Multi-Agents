'use client';

import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Columns,
  Maximize2,
  Minimize2,
  X,
  LayoutDashboard,
  Database,
  FileText,
  GripVertical,
  RotateCcw,
  Sparkles,
} from 'lucide-react';
import { DynamicDashboard } from './dashboard/DynamicDashboard';
import { DashboardSpec, CSVMetadata, SourceItem } from '../lib/types';
import { SourcesList } from './SourcesList';
import { t, useLang } from '../lib/i18n';

interface WorkspaceLayoutProps {
  children: React.ReactNode;
  activeDashboardSpec?: DashboardSpec | null;
  activeCSV?: { file?: File; metadata: CSVMetadata; tableName?: string } | null;
  activeSources?: SourceItem[];
  isOpen: boolean;
  onToggleOpen: (open?: boolean) => void;
  onExportPDF?: () => void;
  onExportPPTX?: () => void;
  onGenerateDashboard?: (prompt?: string) => void;
}

export function WorkspaceLayout({
  children,
  activeDashboardSpec,
  activeCSV,
  activeSources = [],
  isOpen,
  onToggleOpen,
  onExportPDF,
  onExportPPTX,
  onGenerateDashboard,
}: WorkspaceLayoutProps) {
  const [lang] = useLang();
  // Left column width percentage (between 30% and 70%)
  const [splitRatio, setSplitRatio] = useState<number>(48);
  const [isFocusMode, setIsFocusMode] = useState(false);
  const [activeTab, setActiveTab] = useState<'dashboard' | 'duckdb' | 'citations'>('dashboard');
  const [isDragging, setIsDragging] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);

  // Auto switch to dashboard tab when a dashboard spec arrives
  useEffect(() => {
    if (activeDashboardSpec) {
      setActiveTab('dashboard');
    }
  }, [activeDashboardSpec]);

  // Handle Dragging Divider
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const newRatio = (x / rect.width) * 100;
      // Clamp ratio between 30% and 70%
      const clamped = Math.min(70, Math.max(30, newRatio));
      setSplitRatio(clamped);
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  // Double click resets ratio to 50%
  const handleDoubleClickDivider = () => {
    setSplitRatio(50);
  };

  return (
    <div ref={containerRef} className="flex-1 flex w-full h-full min-h-0 min-w-0 overflow-hidden relative">
      {/* ── LEFT PANEL: Chat Stream & ChatInput ── */}
      <div
        style={{
          width: !isOpen
            ? '100%'
            : isFocusMode
            ? '0%'
            : `${splitRatio}%`,
          display: isFocusMode && isOpen ? 'none' : 'flex',
        }}
        className="flex-col h-full min-h-0 min-w-0 transition-[width] duration-150 ease-out overflow-hidden"
      >
        {children}
      </div>

      {/* ── DRAGGABLE DIVIDER (Desktop >= 1024px) ── */}
      {isOpen && !isFocusMode && (
        <div
          onMouseDown={handleMouseDown}
          onDoubleClick={handleDoubleClickDivider}
          title={t(lang, 'ws.dividerHint')}
          className={`
            hidden lg:flex w-2.5 hover:w-2.5 -mx-1 shrink-0 z-30 cursor-col-resize
            items-center justify-center group select-none transition-colors
            ${isDragging ? 'bg-accent-primary/20' : 'hover:bg-accent-primary/10'}
          `}
        >
          <div
            className={`
              w-1 h-8 rounded-full transition-all duration-150 flex items-center justify-center
              ${isDragging ? 'bg-accent-primary h-12 shadow-sm' : 'bg-border group-hover:bg-accent-primary group-hover:h-12'}
            `}
          >
            <GripVertical className="w-2.5 h-2.5 text-foreground-muted opacity-0 group-hover:opacity-100" />
          </div>
        </div>
      )}

      {/* ── RIGHT PANEL: Executive Workspace ── */}
      {isOpen && (
        <div
          style={{
            width: isFocusMode ? '100%' : `${100 - splitRatio}%`,
          }}
          className="flex-1 flex flex-col h-full min-h-0 min-w-0 border-l border-border bg-background-secondary/60  overflow-hidden animate-fade-in"
        >
          {/* Workspace Top Toolbar */}
          <div className="h-11 px-4 border-b border-border bg-surface/80 backdrop-blur-sm flex items-center justify-between shrink-0 select-none">
            {/* Left: Tab Switcher */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setActiveTab('dashboard')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                  activeTab === 'dashboard'
                    ? 'bg-surface-raised text-accent-primary shadow-xs border border-border'
                    : 'text-foreground-secondary hover:text-foreground hover:bg-surface-raised/50'
                }`}
              >
                <LayoutDashboard className="w-3.5 h-3.5" />
                <span>Executive Dashboard</span>
                {activeDashboardSpec && (
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-verifier animate-pulse" />
                )}
              </button>

              <button
                type="button"
                onClick={() => setActiveTab('duckdb')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                  activeTab === 'duckdb'
                    ? 'bg-surface-raised text-accent-primary shadow-xs border border-border'
                    : 'text-foreground-secondary hover:text-foreground hover:bg-surface-raised/50'
                }`}
              >
                <Database className="w-3.5 h-3.5" />
                <span>DuckDB WASM</span>
                {activeCSV && (
                  <span className="px-1.5 py-0.2 text-2xs font-mono font-semibold rounded bg-accent-primary/10 text-accent-primary">
                    {(activeCSV.metadata.totalRows || activeCSV.metadata.rowCount || 0).toLocaleString()}
                  </span>
                )}
              </button>

              <button
                type="button"
                onClick={() => setActiveTab('citations')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                  activeTab === 'citations'
                    ? 'bg-surface-raised text-accent-primary shadow-xs border border-border'
                    : 'text-foreground-secondary hover:text-foreground hover:bg-surface-raised/50'
                }`}
              >
                <FileText className="w-3.5 h-3.5" />
                <span>{t(lang, 'ws.tabCitations')}</span>
                {activeSources.length > 0 && (
                  <span className="px-1.5 py-0.2 text-2xs font-mono font-semibold rounded bg-accent-planner/10 text-accent-planner">
                    {activeSources.length}
                  </span>
                )}
              </button>
            </div>

            {/* Right: Window Controls */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setSplitRatio(50)}
                className="p-1.5 text-foreground-muted hover:text-foreground hover:bg-surface-raised rounded-md transition-colors cursor-pointer"
                title={t(lang, 'ws.resetRatio')}
                aria-label={t(lang, 'ws.resetRatio')}
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>

              <button
                type="button"
                onClick={() => setIsFocusMode(!isFocusMode)}
                className="p-1.5 text-foreground-muted hover:text-foreground hover:bg-surface-raised rounded-md transition-colors cursor-pointer"
                title={isFocusMode ? t(lang, 'ws.focusOff') : t(lang, 'ws.focusOn')}
                aria-label={isFocusMode ? t(lang, 'ws.focusOff') : t(lang, 'ws.focusOn')}
              >
                {isFocusMode ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
              </button>

              <button
                type="button"
                onClick={() => onToggleOpen(false)}
                className="p-1.5 text-foreground-muted hover:text-foreground hover:bg-surface-raised rounded-md transition-colors cursor-pointer"
                title={t(lang, 'ws.close')}
                aria-label={t(lang, 'ws.close')}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Workspace Content Body */}
          <div className="flex-1 min-h-0 overflow-y-auto p-4">
            {activeTab === 'dashboard' && (
              activeDashboardSpec ? (
                <div className="w-full">
                  <DynamicDashboard spec={activeDashboardSpec} />
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-20 px-6 text-center space-y-4">
                  <div className="w-14 h-14 rounded-2xl bg-surface-raised flex items-center justify-center text-accent-primary border border-border">
                    <LayoutDashboard className="w-7 h-7" />
                  </div>
                  <div className="max-w-md">
                    <h3 className="text-base font-semibold text-foreground mb-1">
                      {t(lang, 'ws.dashReady')}
                    </h3>
                    <p className="text-xs text-foreground-muted leading-relaxed">
                      {t(lang, 'ws.dashReadyHint')}
                    </p>
                  </div>
                  {activeCSV && onGenerateDashboard && (
                    <button
                      type="button"
                      onClick={() => onGenerateDashboard(t(lang, 'ws.dashPrompt'))}
                      className="flex items-center gap-2 px-4 py-2 rounded-xl bg-accent-primary hover:bg-accent-primary-hover text-white text-xs font-semibold transition-colors cursor-pointer"
                    >
                      <Sparkles className="w-4 h-4" />
                      <span>{t(lang, 'ws.dashButton', { rows: (activeCSV.metadata.totalRows || activeCSV.metadata.rowCount || 0).toLocaleString() })}</span>
                    </button>
                  )}
                </div>
              )
            )}

            {activeTab === 'duckdb' && (
              activeCSV ? (
                <div className="space-y-4">
                  <div className="p-4 bg-surface rounded-xl border border-border space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Database className="w-4 h-4 text-accent-primary" />
                        <span className="text-sm font-semibold text-foreground">{activeCSV.file?.name || t(lang, 'ws.dataFile')}</span>
                      </div>
                      <span className="px-2 py-0.5 rounded-full text-2xs font-mono font-semibold bg-accent-verifier/10 text-accent-verifier border border-accent-verifier/20">
                        {t(lang, 'ws.loaded')}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
                      <div className="p-3 bg-surface-raised rounded-lg border border-border">
                        <p className="text-2xs text-foreground-muted">{t(lang, 'ws.totalRows')}</p>
                        <p className="text-base font-mono font-bold tabular-nums text-foreground mt-0.5">
                          {(activeCSV.metadata.totalRows || activeCSV.metadata.rowCount || 0).toLocaleString()}
                        </p>
                      </div>
                      <div className="p-3 bg-surface-raised rounded-lg border border-border">
                        <p className="text-2xs text-foreground-muted">{t(lang, 'ws.columns')}</p>
                        <p className="text-base font-mono font-bold tabular-nums text-foreground mt-0.5">
                          {activeCSV.metadata.columns?.length || 0}
                        </p>
                      </div>
                      <div className="p-3 bg-surface-raised rounded-lg border border-border">
                        <p className="text-2xs text-foreground-muted">{t(lang, 'ws.tableName')}</p>
                        <p className="text-xs font-mono font-bold text-accent-primary mt-1 truncate">
                          {activeCSV.tableName || 'uploaded_data'}
                        </p>
                      </div>
                      <div className="p-3 bg-surface-raised rounded-lg border border-border">
                        <p className="text-2xs text-foreground-muted">{t(lang, 'ws.status')}</p>
                        <p className="text-xs font-medium text-accent-verifier mt-1">{t(lang, 'ws.ready')}</p>
                      </div>
                    </div>
                  </div>

                  {/* Column Schema Table */}
                  <div className="p-4 bg-surface rounded-xl border border-border space-y-3">
                    <h4 className="text-xs font-semibold text-foreground uppercase tracking-wider font-mono">
                      {t(lang, 'ws.schema')}
                    </h4>
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead>
                          <tr className="border-b border-border text-foreground-muted text-2xs uppercase">
                            <th className="py-2 px-3">{t(lang, 'ws.colName')}</th>
                            <th className="py-2 px-3">{t(lang, 'ws.colType')}</th>
                            <th className="py-2 px-3">{t(lang, 'ws.colRole')}</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-border font-mono text-2xs">
                          {activeCSV.metadata.columns?.map((col, idx) => (
                            <tr key={idx} className="hover:bg-surface-raised/50">
                              <td className="py-2 px-3 font-semibold text-foreground">{col.name}</td>
                              <td className="py-2 px-3 text-accent-primary">{col.type}</td>
                              <td className="py-2 px-3 text-foreground-muted">{col.role || 'feature'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-20 px-6 text-center space-y-3">
                  <div className="w-12 h-12 rounded-2xl bg-surface-raised flex items-center justify-center text-accent-primary border border-border">
                    <Database className="w-6 h-6" />
                  </div>
                  <p className="text-sm font-semibold text-foreground">{t(lang, 'ws.noFile')}</p>
                  <p className="text-xs text-foreground-muted max-w-sm">
                    {t(lang, 'ws.noFileHint')}
                  </p>
                </div>
              )
            )}

            {activeTab === 'citations' && (
              activeSources.length > 0 ? (
                <div className="space-y-4">
                  <SourcesList sources={activeSources} />
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-20 px-6 text-center space-y-3">
                  <div className="w-12 h-12 rounded-2xl bg-surface-raised flex items-center justify-center text-accent-planner border border-border">
                    <FileText className="w-6 h-6" />
                  </div>
                  <p className="text-sm font-semibold text-foreground">{t(lang, 'ws.noSources')}</p>
                  <p className="text-xs text-foreground-muted max-w-sm">
                    {t(lang, 'ws.noSourcesHint')}
                  </p>
                </div>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}
