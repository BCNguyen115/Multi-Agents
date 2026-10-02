'use client';

import React, { useState, useRef } from 'react';
import { UploadCloud, FileSpreadsheet, CheckCircle, Loader2, AlertCircle, X } from 'lucide-react';
import { processCSVWithDuckDB } from '../lib/duckdb';
import { CSVMetadata } from '../lib/types';
import { getLang, t, useLang } from '../lib/i18n';

interface CSVUploaderProps {
  onCSVProcessed: (csvData: { file: File; metadata: CSVMetadata; tableName: string }) => void;
}

export const CSVUploader: React.FC<CSVUploaderProps> = ({ onCSVProcessed }) => {
  const [lang] = useLang();
  const [isProcessing, setIsProcessing] = useState(false);
  const [activeMetadata, setActiveMetadata] = useState<CSVMetadata | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setErrorMessage(null);
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setErrorMessage(t(getLang(), 'csv.invalidType'));
      return;
    }

    setIsProcessing(true);
    try {
      const { metadata, tableName } = await processCSVWithDuckDB(file);
      setActiveMetadata(metadata);
      onCSVProcessed({ file, metadata, tableName });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error('Error processing CSV via DuckDB-Wasm:', msg);
      setErrorMessage(t(getLang(), 'csv.parseFailed', { error: msg }));
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  return (
    <div className="bg-surface rounded-xl border border-border p-4 mb-4" data-testid="csv-upload-dropzone">
      {/* File input persistent in DOM to eliminate dead click issues */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv"
        id="csv-file-input"
        onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        className="hidden"
      />

      {/* Non-blocking inline error alert */}
      {errorMessage && (
        <div className="mb-3 p-3 bg-accent-error/10 border border-accent-error/20 rounded-lg text-accent-error text-xs flex items-center justify-between animate-fade-in">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMessage}</span>
          </div>
          <button
            type="button"
            onClick={() => setErrorMessage(null)}
            className="hover:opacity-80 p-0.5 rounded focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-error/50"
            aria-label={t(lang, 'csv.closeError')}
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {!activeMetadata ? (
        <div
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-xl p-8 text-center transition-all duration-200 cursor-pointer ${
            dragActive
              ? 'border-accent-primary bg-accent-primary/5 scale-[0.99]'
              : 'border-border hover:border-accent-primary/50 bg-surface-raised/30 hover:bg-surface-raised/60'
          }`}
        >
          <div className="flex flex-col items-center justify-center space-y-3">
            {isProcessing ? (
              <>
                <Loader2 className="w-8 h-8 text-accent-primary animate-spin" />
                <p className="text-sm font-semibold text-foreground">{t(lang, 'csv.loading')}</p>
              </>
            ) : (
              <>
                <div className="p-3 bg-accent-primary/10 text-accent-primary rounded-full shadow-xs">
                  <UploadCloud className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground">{t(lang, 'csv.drop')}</p>
                  <p className="text-xs text-foreground-muted mt-1">
                    {t(lang, 'csv.safe')} <span className="font-semibold text-accent-primary">DuckDB-Wasm Engine</span>
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between bg-surface-raised/50 border border-border rounded-xl p-3.5 shadow-xs">
          <div className="flex items-center space-x-3 min-w-0">
            <div className="p-2.5 bg-accent-verifier text-white rounded-lg shadow-xs shrink-0">
              <FileSpreadsheet className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center space-x-2">
                <span className="font-semibold text-foreground text-sm truncate">{activeMetadata.filename}</span>
                <span className="bg-accent-verifier/10 text-accent-verifier border border-accent-verifier/20 text-xs font-bold px-2 py-0.5 rounded-full flex items-center gap-1 shrink-0">
                  <CheckCircle className="w-3 h-3" /> {t(lang, 'csv.ready')}
                </span>
              </div>
              <p className="text-xs text-foreground-muted mt-0.5 font-mono tabular-nums truncate">
                {t(lang, 'csv.stats', { rows: activeMetadata.totalRows.toLocaleString(), cols: activeMetadata.totalCols, numeric: activeMetadata.numericCols.length, categorical: activeMetadata.categoricalCols.length })}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="text-xs bg-surface hover:bg-accent-primary/10 text-accent-primary border border-accent-primary/20 px-3.5 py-1.5 rounded-lg cursor-pointer transition-colors font-medium shrink-0 ml-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
          >
            {t(lang, 'csv.change')}
          </button>
        </div>
      )}
    </div>
  );
};
