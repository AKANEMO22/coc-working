"use client";

import { useState } from "react";
import { User, GraduationCap } from "lucide-react";

interface GuestModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (studentId: string, name: string) => void;
}

export function GuestModal({ isOpen, onClose, onSubmit }: GuestModalProps) {
  const [studentId, setStudentId] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!studentId.trim() || !name.trim()) return;
    setLoading(true);
    await onSubmit(studentId.trim(), name.trim());
    setLoading(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative glass-card p-8 max-w-md w-full animate-in fade-in zoom-in duration-300">
        {/* Header */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-[var(--coc-primary)] to-[var(--coc-accent)] mb-4">
            <GraduationCap className="w-8 h-8 text-white" />
          </div>
          <h2 className="text-xl font-bold text-[var(--text-primary)]">
            Chào mừng đến Cóc Đi Làm! 🐸
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mt-2">
            Nhập thông tin để bắt đầu luyện phỏng vấn OJT
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text-secondary)] mb-1.5">
              Mã số sinh viên (MSSV)
            </label>
            <div className="relative">
              <GraduationCap className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]" />
              <input
                type="text"
                value={studentId}
                onChange={(e) => setStudentId(e.target.value)}
                placeholder="VD: HE180000"
                className="w-full pl-10 pr-4 py-3 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)]
                  text-[var(--text-primary)] placeholder:text-[var(--text-muted)]
                  focus:border-[var(--coc-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--coc-primary)]/20
                  transition-all duration-200"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text-secondary)] mb-1.5">
              Họ và tên
            </label>
            <div className="relative">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]" />
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="VD: Nguyễn Văn A"
                className="w-full pl-10 pr-4 py-3 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)]
                  text-[var(--text-primary)] placeholder:text-[var(--text-muted)]
                  focus:border-[var(--coc-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--coc-primary)]/20
                  transition-all duration-200"
                required
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || !studentId.trim() || !name.trim()}
            className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <>Bắt đầu</>
            )}
          </button>
        </form>

        <p className="text-xs text-[var(--text-muted)] text-center mt-4">
          Chế độ Demo — Dữ liệu phục vụ luyện tập
        </p>
      </div>
    </div>
  );
}
