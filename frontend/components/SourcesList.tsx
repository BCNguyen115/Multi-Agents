'use client';

import React, { useState } from 'react';
import { BookOpen, ChevronDown, ChevronUp, FileText, Globe, ExternalLink } from 'lucide-react';
import { SourceItem } from '../lib/types';

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
  const [isOpen, setIsOpen] = useState(true);

  if (!sources || sources.length === 0) return null;

  // Separate document sources vs web sources
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
    <div className="mt-4 border-t border-slate-200 dark:border-slate-800 pt-3 text-xs text-slate-700 dark:text-slate-300">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between font-semibold mb-2.5 text-slate-800 dark:text-slate-200 hover:text-blue-600 dark:hover:text-blue-400 transition-colors cursor-pointer"
      >
        <span className="flex items-center gap-1.5 text-xs font-bold text-slate-800 dark:text-slate-200">
          <BookOpen className="w-4 h-4 text-[#005697] dark:text-blue-400" />
          Nguồn tham khảo ({sources.length}):
        </span>
        <span className="text-slate-500 dark:text-slate-400">
          {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </span>
      </button>

      {isOpen && (
        <div className="space-y-3 mt-2">
          {/* A. Web Sources Grid (Search Agent Cards UI like Perplexity) */}
          {webSources.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
              {webSources.map((src, idx) => {
                const targetUrl = src.url || (src.file.startsWith('http') ? src.file : '#');
                const title = src.title || src.section || src.file || 'Bài viết web';
                const domain = src.domain || extractDomain(targetUrl);

                return (
                  <a
                    key={`web-${idx}`}
                    href={targetUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group relative flex flex-col justify-between p-3 bg-slate-50/90 dark:bg-slate-800/80 border border-slate-200/90 dark:border-slate-700/80 rounded-xl hover:border-blue-500 dark:hover:border-blue-400 hover:shadow-md hover:bg-white dark:hover:bg-slate-800 transition-all duration-200 cursor-pointer"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <div className="w-4 h-4 rounded-full bg-blue-100 dark:bg-blue-900/60 flex items-center justify-center shrink-0">
                          <Globe className="w-2.5 h-2.5 text-blue-600 dark:text-blue-400" />
                        </div>
                        <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 truncate">
                          {domain}
                        </span>
                      </div>
                      <ExternalLink className="w-3.5 h-3.5 text-slate-400 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors shrink-0" />
                    </div>

                    <h4 className="text-xs font-semibold text-slate-800 dark:text-slate-200 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors line-clamp-2 leading-snug">
                      {title}
                    </h4>

                    {src.snippet && (
                      <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400 line-clamp-2 leading-relaxed">
                        {src.snippet}
                      </p>
                    )}
                  </a>
                );
              })}
            </div>
          )}

          {/* B. Enterprise Document Sources (RAG Contract Badges) */}
          {docSources.length > 0 && (
            <div className="space-y-2">
              {docSources.map((src, idx) => {
                const fileName = src.file || 'Tài liệu trích dẫn';
                const category = (src.category || 'GENERAL').toUpperCase();

                let categoryBadgeStyle = 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950/60 dark:text-blue-300 dark:border-blue-800';
                if (category.includes('NDA')) categoryBadgeStyle = 'bg-rose-100 text-rose-800 border-rose-200 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800';
                else if (category.includes('MSA')) categoryBadgeStyle = 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800';
                else if (category.includes('SOW')) categoryBadgeStyle = 'bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800';

                return (
                  <div key={`doc-${idx}`} className="p-2.5 bg-slate-50/90 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 rounded-lg text-xs shadow-2xs hover:bg-slate-100/80 dark:hover:bg-slate-800 transition-colors">
                    <div className="flex items-center justify-between font-medium text-slate-800 dark:text-slate-200 gap-2 mb-1">
                      <span className="truncate flex items-center gap-1.5 font-semibold text-slate-900 dark:text-slate-100">
                        <FileText className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400 shrink-0" />
                        📄 {fileName}
                      </span>
                      <span className={`px-2 py-0.5 border rounded-md text-[10px] font-bold tracking-wider shrink-0 ${categoryBadgeStyle}`}>
                        {category}
                      </span>
                    </div>
                    {src.section && (
                      <p className="mt-1 text-slate-600 dark:text-slate-300 italic border-l-2 border-blue-400 dark:border-blue-500 pl-2.5 py-0.5 line-clamp-3 bg-white/70 dark:bg-slate-900/60 rounded-r-md text-[11px] leading-relaxed">
                        "{src.section}"
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
