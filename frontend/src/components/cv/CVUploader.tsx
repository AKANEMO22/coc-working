"use client";

import React, { useState, useRef } from "react";
import { Upload, FileText, AlertCircle, Loader2, X } from "lucide-react";

interface CVUploaderProps {
  onFileSelected: (file: File) => void;
  isAnalyzing: boolean;
  selectedFile: File | null;
  onClearFile: () => void;
}

export function CVUploader({
  onFileSelected,
  isAnalyzing,
  selectedFile,
  onClearFile,
}: CVUploaderProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const validateAndSelect = (file: File) => {
    setErrorMsg(null);
    const validExtensions = [".pdf", ".docx", ".doc", ".txt"];
    const fileExt = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();

    if (!validExtensions.includes(fileExt)) {
      setErrorMsg("Hệ thống chỉ hỗ trợ định dạng PDF, DOCX, hoặc TXT");
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      setErrorMsg("Dung lượng file tối đa là 10MB");
      return;
    }

    onFileSelected(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndSelect(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndSelect(e.target.files[0]);
    }
  };

  return (
    <div className="w-full">
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleChange}
        accept=".pdf,.docx,.doc,.txt"
        className="hidden"
      />

      {!selectedFile ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragOver(true);
          }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all duration-300 ${
            isDragOver
              ? "border-[var(--coc-primary)] bg-[var(--coc-primary)]/10 scale-[1.01]"
              : "border-[var(--border-color)] hover:border-[var(--coc-primary)] bg-[var(--bg-secondary)]/50 hover:bg-[var(--bg-secondary)]"
          }`}
        >
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-[var(--coc-primary)]/20 to-[var(--coc-accent)]/20 flex items-center justify-center text-[var(--coc-primary)]">
            <Upload className="w-8 h-8" />
          </div>
          <h3 className="text-base font-semibold text-[var(--text-primary)] mb-1">
            Kéo thả CV của bạn vào đây hoặc bấm để chọn file
          </h3>
          <p className="text-xs text-[var(--text-muted)] mb-4">
            Hỗ trợ PDF, DOCX hoặc TXT (tối đa 10MB)
          </p>
          <button
            type="button"
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] text-white text-xs font-semibold shadow-md hover:shadow-lg transition-all"
          >
            Tải lên từ thiết bị
          </button>
        </div>
      ) : (
        <div className="p-4 rounded-2xl border border-[var(--border-color)] bg-[var(--bg-secondary)] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-[var(--coc-primary)]/10 flex items-center justify-center text-[var(--coc-primary)]">
              <FileText className="w-6 h-6" />
            </div>
            <div>
              <p className="text-sm font-semibold text-[var(--text-primary)] truncate max-w-xs sm:max-w-sm">
                {selectedFile.name}
              </p>
              <p className="text-xs text-[var(--text-muted)]">
                {(selectedFile.size / 1024 / 1024).toFixed(2)} MB • Sẵn sàng phân tích
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isAnalyzing ? (
              <div className="flex items-center gap-2 text-xs text-[var(--coc-primary)] font-medium">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Đang đọc CV để chuẩn bị phỏng vấn...</span>
              </div>
            ) : (
              <button
                type="button"
                onClick={onClearFile}
                className="p-1.5 rounded-lg hover:bg-[var(--border-color)] text-[var(--text-muted)] hover:text-red-400 transition-all"
                title="Xóa file"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>
        </div>
      )}

      {errorMsg && (
        <div className="mt-3 flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 px-3 py-2 rounded-xl">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}
    </div>
  );
}
