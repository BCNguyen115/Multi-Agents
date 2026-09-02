'use client';

import React, { useState } from 'react';
import { UploadCloud, FileSpreadsheet, CheckCircle, Database, Table, Loader2 } from 'lucide-react';
import { processCSVWithDuckDB } from '../lib/duckdb';
import { CSVMetadata } from '../lib/types';

interface CSVUploaderProps {
  onCSVProcessed: (csvData: { file: File; metadata: CSVMetadata; tableName: string }) => void;
}

export const CSVUploader: React.FC<CSVUploaderProps> = ({ onCSVProcessed }) => {
  const [isProcessing, setIsProcessing] = useState(false);
  const [activeMetadata, setActiveMetadata] = useState<CSVMetadata | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleFile = async (file: File) => {
    if (!file.name.endsWith('.csv')) {
      alert('Vui lòng chọn file đúng định dạng CSV');
      return;
    }

    setIsProcessing(true);
    try {
      const { metadata, tableName } = await processCSVWithDuckDB(file);
      setActiveMetadata(metadata);
      onCSVProcessed({ file, metadata, tableName });
    } catch (err: any) {
      console.error('Lỗi khi xử lý CSV qua DuckDB-Wasm:', err);
      alert(`Lỗi khi đọc file CSV: ${err.message || err}`);
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
    <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-xs mb-4">
      {!activeMetadata ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer ${
            dragActive
              ? 'border-brand-500 bg-brand-50/50'
              : 'border-slate-300 hover:border-brand-400 bg-slate-50/50'
          }`}
        >
          <input
            type="file"
            accept=".csv"
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
            className="hidden"
            id="csv-file-input"
          />
          <label htmlFor="csv-file-input" className="cursor-pointer flex flex-col items-center justify-center space-y-2">
            {isProcessing ? (
              <>
                <Loader2 className="w-10 h-10 text-brand-600 animate-spin" />
                <p className="text-sm font-semibold text-slate-700">DuckDB-Wasm đang nạp CSV vào In-Memory Browser Database...</p>
              </>
            ) : (
              <>
                <div className="p-3 bg-brand-100 text-brand-700 rounded-full">
                  <UploadCloud className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-800">Kéo & Thả file CSV vào đây hoặc click để tải lên</p>
                  <p className="text-xs text-slate-500 mt-1">
                    ⚡ Xử lý siêu tốc client-side bằng <span className="font-semibold text-brand-700">DuckDB-Wasm Engine</span>
                  </p>
                </div>
              </>
            )}
          </label>
        </div>
      ) : (
        <div className="flex items-center justify-between bg-white border border-slate-200/90 rounded-xl p-3 shadow-xs">
          <div className="flex items-center space-x-3">
            <div className="p-2.5 bg-emerald-500 text-white rounded-lg shadow-2xs shrink-0">
              <FileSpreadsheet className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-semibold text-[#212529] text-sm">{activeMetadata.filename}</span>
                <span className="bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px] font-bold px-2.5 py-0.5 rounded-full flex items-center gap-1 shadow-2xs">
                  <CheckCircle className="w-3 h-3 text-emerald-600" /> Ready
                </span>
              </div>
              <p className="text-xs text-[#495057] mt-0.5">
                📊 {activeMetadata.totalRows.toLocaleString()} dòng × {activeMetadata.totalCols} cột | Cột số: {activeMetadata.numericCols.length} | Danh mục: {activeMetadata.categoricalCols.length}
              </p>
            </div>
          </div>

          <label
            htmlFor="csv-file-input"
            className="text-xs bg-white text-[#005697] hover:bg-[#F0F7FF] border border-[#005697]/30 px-3.5 py-1.5 rounded-lg cursor-pointer transition-colors font-semibold shrink-0"
          >
            Đổi File CSV Khác
          </label>
        </div>
      )}
    </div>
  );
};
