"use client";

import React from "react";
import { CheckCircle2, AlertTriangle, ArrowRight, Zap, Target, Award, Sparkles } from "lucide-react";

interface GapAnalysisCardProps {
  atsScore: number; // 0 - 100
  xyzScore: number; // 0 - 100
  matchScore: number; // 0 - 100
  matchedSkills: string[];
  missingSkills: string[];
  interviewSeeds: string[];
  onStartInterviewWithSeeds: () => void;
}

export function GapAnalysisCard({
  atsScore,
  xyzScore,
  matchScore,
  matchedSkills,
  missingSkills,
  interviewSeeds,
  onStartInterviewWithSeeds,
}: GapAnalysisCardProps) {
  return (
    <div className="rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 backdrop-blur-xl p-6 sm:p-8 space-y-6">
      {/* Header and Scores */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-[var(--border-color)]">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="w-5 h-5 text-[var(--coc-primary)]" />
            <h3 className="text-xl font-bold text-[var(--text-primary)]">
              Kết Quả Phân Tích Khoảng Cách Năng Lực (JD Gap)
            </h3>
          </div>
          <p className="text-xs text-[var(--text-muted)]">
            Đánh giá theo chuẩn ATS quốc tế & công thức định lượng Google XYZ
          </p>
        </div>

        {/* Big Overall Match Score Badge */}
        <div className="flex items-center gap-3 px-5 py-3 rounded-2xl bg-gradient-to-br from-[var(--coc-primary)]/15 to-[var(--coc-accent)]/15 border border-[var(--coc-primary)]/30">
          <Target className="w-6 h-6 text-[var(--coc-primary)]" />
          <div>
            <div className="text-2xl font-black text-[var(--text-primary)] font-mono">
              {matchScore}%
            </div>
            <div className="text-[10px] uppercase tracking-wider font-semibold text-[var(--text-muted)]">
              Độ phù hợp JD
            </div>
          </div>
        </div>
      </div>

      {/* 3 Metric Progress Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* ATS Score */}
        <div className="p-4 rounded-2xl bg-[var(--bg-primary)] border border-[var(--border-color)]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-[var(--text-secondary)]">Điểm chuẩn ATS</span>
            <span className="text-sm font-bold text-[var(--coc-primary)] font-mono">{atsScore}/100</span>
          </div>
          <div className="w-full h-2 rounded-full bg-[var(--border-color)] overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-emerald-500 to-[var(--coc-primary)] rounded-full transition-all duration-700"
              style={{ width: `${atsScore}%` }}
            />
          </div>
          <p className="text-[11px] text-[var(--text-muted)] mt-2">
            Định dạng, cấu trúc và từ khóa đạt chuẩn máy quét ATS.
          </p>
        </div>

        {/* Google XYZ Score */}
        <div className="p-4 rounded-2xl bg-[var(--bg-primary)] border border-[var(--border-color)]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-[var(--text-secondary)]">Định lượng XYZ</span>
            <span className="text-sm font-bold text-cyan-400 font-mono">{xyzScore}/100</span>
          </div>
          <div className="w-full h-2 rounded-full bg-[var(--border-color)] overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-blue-500 to-cyan-400 rounded-full transition-all duration-700"
              style={{ width: `${xyzScore}%` }}
            />
          </div>
          <p className="text-[11px] text-[var(--text-muted)] mt-2">
            Thực hiện [X], đo lường bằng [Y], thông qua [Z].
          </p>
        </div>

        {/* Overall Match */}
        <div className="p-4 rounded-2xl bg-[var(--bg-primary)] border border-[var(--border-color)]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-[var(--text-secondary)]">Tương thích JD</span>
            <span className="text-sm font-bold text-amber-400 font-mono">{matchScore}%</span>
          </div>
          <div className="w-full h-2 rounded-full bg-[var(--border-color)] overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-amber-500 to-orange-400 rounded-full transition-all duration-700"
              style={{ width: `${matchScore}%` }}
            />
          </div>
          <p className="text-[11px] text-[var(--text-muted)] mt-2">
            Tỷ lệ phủ kỹ năng trọng tâm theo yêu cầu tuyển dụng.
          </p>
        </div>
      </div>

      {/* Skills Matrix */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Matched Skills */}
        <div className="p-4 rounded-2xl bg-[var(--bg-primary)] border border-[var(--border-color)]">
          <div className="flex items-center gap-2 mb-3 text-emerald-400">
            <CheckCircle2 className="w-4 h-4" />
            <h4 className="text-xs font-bold uppercase tracking-wider">
              Kỹ năng đã đáp ứng ({matchedSkills.length})
            </h4>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {matchedSkills.length > 0 ? (
              matchedSkills.map((skill, idx) => (
                <span
                  key={idx}
                  className="px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                >
                  ✓ {skill}
                </span>
              ))
            ) : (
              <span className="text-xs text-[var(--text-muted)]">Chưa nhận diện được kỹ năng khớp.</span>
            )}
          </div>
        </div>

        {/* Missing Skills (Gaps) */}
        <div className="p-4 rounded-2xl bg-[var(--bg-primary)] border border-[var(--border-color)]">
          <div className="flex items-center gap-2 mb-3 text-amber-400">
            <AlertTriangle className="w-4 h-4" />
            <h4 className="text-xs font-bold uppercase tracking-wider">
              Kỹ năng còn thiếu / Cần đào sâu ({missingSkills.length})
            </h4>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {missingSkills.length > 0 ? (
              missingSkills.map((skill, idx) => (
                <span
                  key={idx}
                  className="px-2.5 py-1 rounded-lg text-xs font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20"
                >
                  ! {skill}
                </span>
              ))
            ) : (
              <span className="text-xs text-[var(--text-muted)]">Không có khoảng cách lớn phát hiện.</span>
            )}
          </div>
        </div>
      </div>

      {/* Bridge to Phân hệ 2: Interview Seeds */}
      {interviewSeeds.length > 0 && (
        <div className="p-5 rounded-2xl bg-gradient-to-br from-[var(--coc-primary)]/10 via-[var(--bg-primary)] to-[var(--coc-accent)]/10 border border-[var(--coc-primary)]/30">
          <div className="flex items-center gap-2 mb-2 text-[var(--coc-primary)]">
            <Zap className="w-4 h-4" />
            <h4 className="text-sm font-bold">
              Cầu nối phỏng vấn (Interview Seeds Bridge §19)
            </h4>
          </div>
          <p className="text-xs text-[var(--text-secondary)] mb-3">
            Hệ thống đã tự động chuyển các khoảng cách năng lực thành câu hỏi trọng tâm cho phiên phỏng vấn:
          </p>
          <ul className="space-y-2 mb-4">
            {interviewSeeds.map((seed, idx) => (
              <li
                key={idx}
                className="flex items-start gap-2 text-xs text-[var(--text-primary)] bg-[var(--bg-secondary)]/70 p-2.5 rounded-xl border border-[var(--border-color)]"
              >
                <span className="text-[var(--coc-primary)] font-bold font-mono">Q{idx + 1}.</span>
                <span>{seed}</span>
              </li>
            ))}
          </ul>

          <button
            onClick={onStartInterviewWithSeeds}
            className="w-full py-3.5 px-6 rounded-2xl bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] hover:from-[var(--coc-primary-light)] hover:to-[var(--coc-accent)] text-white font-bold text-sm flex items-center justify-center gap-2 shadow-[var(--shadow-glow)] hover:shadow-lg transition-all"
          >
            <span>Bắt đầu phiên phỏng vấn với các trọng tâm này</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
