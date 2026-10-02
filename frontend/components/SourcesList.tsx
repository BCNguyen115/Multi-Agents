'use client';

import React, { useState } from 'react';
import { BookOpen, ChevronDown, ChevronUp, FileText, Globe, ExternalLink } from 'lucide-react';
import { SourceItem } from '../lib/types';
import { t, useLang } from '../lib/i18n';
import { PageViewer } from './PageViewer';

function extractDomain(urlStr?: string): string {
  if (!urlStr) return 'web.src';
  try {
    const url = new URL(urlStr);
    return url.hostname.replace(/^www\./, '');
  } catch {
    return urlStr.replace(/^https?:\/\//, '').split('/')[0] || 'web.src';
  }
}

export function SourcesList({ sources }: { sources: SourceItem[] }) {
  const [lang] = useLang();
  const [isOpen, setIsOpen] = useState(true);
  const [viewing, setViewing] = useState<SourceItem | null>(null);

  if (!sources || sources.length === 0) return null;

  const webSources: SourceItem[] = [];
  const docSources: SourceItem[] = [];

  sources.forEach((src) => {
    const isWeb = Boolean(
      src.url ||
      (src.file && (src.file.startsWith('http://') || src.file.startsWith('https://'))) ||
      src.category === 'web' ||
      src.category === 'search'
    );
    if (isWeb) {
      webSources.push(src);
    } else {
      docSources.push(src);
    }
  });

  return (
    <div className="mt-4 border-t border-border pt-3 text-xs text-foreground-secondary">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between font-semibold mb-2.5 text-foreground hover:text-accent-primary transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 rounded-lg p-1"
      >
        <span className="flex items-center gap-1.5 text-xs font-bold">
          <BookOpen className="w-4 h-4 text-accent-primary" />
          {t(lang, 'sources.title', { count: sources.length })}
        </span>
        <span className="text-foreground-muted">
          {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </span>
      </button>

      {isOpen && (
        <div className="space-y-3 mt-2 animate-fade-in">
          {/* Web Sources Grid */}
          {webSources.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
              {webSources.map((src, idx) => {
                const targetUrl = src.url || (src.file.startsWith('http') ? src.file : '#');
                const title = src.title || src.section || src.file || t(lang, 'sources.webArticle');
                const domain = src.domain || extractDomain(targetUrl);

                return (
                  <a
                    key={`web-${idx}`}
                    href={targetUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group relative flex flex-col justify-between p-3 bg-surface-raised border border-border rounded-xl hover:border-accent-primary hover:shadow-enterprise transition-all duration-200 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <div className="w-4 h-4 rounded-full bg-accent-primary/10 flex items-center justify-center shrink-0">
                          <Globe className="w-2.5 h-2.5 text-accent-primary" />
                        </div>
                        <span className="text-xs font-semibold text-foreground-muted truncate">
                          {domain}
                        </span>
                      </div>
                      <ExternalLink className="w-3.5 h-3.5 text-foreground-muted group-hover:text-accent-primary transition-colors shrink-0" />
                    </div>

                    <h4 className="text-xs font-semibold text-foreground group-hover:text-accent-primary transition-colors line-clamp-2 leading-snug">
                      {title}
                    </h4>

                    {src.snippet && (
                      <p className="mt-1 text-xs text-foreground-muted line-clamp-2 leading-relaxed">
                        {src.snippet}
                      </p>
                    )}
                  </a>
                );
              })}
            </div>
          )}

          {/* Document Sources */}
          {docSources.length > 0 && (
            <div className="space-y-2">
              {docSources.map((src, idx) => {
                const fileName = src.file || t(lang, 'sources.citedDocument');
                const canPreview = Boolean(src.page && src.category && /\.pdf$/i.test(src.file));
                const category = (src.category || 'GENERAL').toUpperCase();

                let categoryBadgeStyle = 'bg-accent-primary/10 text-accent-primary border-accent-primary/20';
                if (category.includes('NDA')) categoryBadgeStyle = 'bg-accent-error/10 text-accent-error border-accent-error/20';
                else if (category.includes('MSA')) categoryBadgeStyle = 'bg-accent-planner/10 text-accent-planner border-accent-planner/20';
                else if (category.includes('SOW')) categoryBadgeStyle = 'bg-accent-verifier/10 text-accent-verifier border-accent-verifier/20';

                return (
                  <div key={`doc-${idx}`} className="p-2.5 bg-surface-raised border border-border rounded-lg text-xs hover:bg-surface-overlay/30 transition-colors">
                    <div className="flex items-center justify-between font-medium text-foreground gap-2 mb-1">
                      <span className="truncate flex items-center gap-1.5 font-semibold" title={fileName}>
                        {src.cite !== undefined && (
                          <span className="shrink-0 rounded bg-accent-primary/10 px-1.5 py-0.5 font-mono text-2xs font-bold text-accent-primary" data-testid="source-cite">
                            [{src.cite}]
                          </span>
                        )}
                        <FileText className="w-3.5 h-3.5 text-accent-primary shrink-0" />
                        {fileName}
                      </span>
                      <span className={`px-2 py-0.5 border rounded-md text-xs font-bold tracking-wider shrink-0 ${categoryBadgeStyle}`}>
                        {category}
                      </span>
                    </div>
                    {(src.section || src.page) && (
                      <p className="flex items-center gap-2 text-2xs text-foreground-muted">
                        <span>{[src.section, src.page ? t(lang, 'sources.page', { page: src.page }) : ''].filter(Boolean).join(' · ')}</span>
                        {canPreview && (
                          <button
                            type="button"
                            onClick={() => setViewing(src)}
                            className="rounded px-1.5 py-0.5 font-semibold text-accent-primary hover:bg-accent-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
                          >
                            {t(lang, 'source.viewPage', { page: src.page as number })}
                          </button>
                        )}
                      </p>
                    )}
                    {src.snippet && (
                      <p className="mt-1 text-foreground-muted italic border-l border-border-strong pl-2.5 py-0.5 line-clamp-3 bg-surface/50 rounded-r-md text-xs leading-relaxed">
                        &quot;{src.snippet}&quot;
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      {viewing && (
        <PageViewer
          docKey={`${viewing.category}/${viewing.file}`}
          fileName={viewing.file}
          page={viewing.page as number}
          snippet={viewing.snippet}
          onClose={() => setViewing(null)}
        />
      )}
    </div>
  );
}
