"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  BarChart3,
  CheckCircle,
  AlertTriangle,
  BookOpen,
  RotateCcw,
  ArrowRight,
  Sparkles,
  Award,
  Loader2,
  FileCheck2,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function ReportPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const [loading, setLoading] = useState(true);
  const [reportData, setReportData] = useState<any>(null);

  useEffect(() => {
    async function fetchReport() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/sessions/${sessionId}/report`);
        if (res.ok) {
          const data = await res.json();
          setReportData(data);
        }
      } catch (e) {
        console.warn("Failed to fetch report:", e);
      } finally {
        setLoading(false);
      }
    }

    if (sessionId) {
      fetchReport();
    }
  }, [sessionId]);

  if (loading) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center gap-3">
        <Loader2 className="w-8 h-8 text-[var(--coc-primary)] animate-spin" />
        <p className="text-sm text-[var(--text-secondary)] font-medium">
          Đang tổng hợp báo cáo đánh giá toàn diện...
        </p>
      </div>
    );
  }

  const radarScores = reportData?.radar_scores || {
    hr_motivation: 0,
    project_defense: 0,
    technical_core: 0,
    case_study: 0,
  };

  const overallScore = reportData?.overall_score ?? 0.0;
  const grade = reportData?.grade || "Chưa hoàn thành lượt phỏng vấn nào";

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Header */}
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--coc-primary)]/10 text-[var(--coc-primary)] text-xs font-semibold mb-3 border border-[var(--coc-primary)]/20">
          <Award className="w-3.5 h-3.5" />
          <span>Báo Cáo Đánh Giá Năng Lực Toàn Diện (§14)</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-extrabold text-[var(--text-primary)] mb-2">
          Kết Quả Phỏng Vấn OJT Thực Chiến
        </h1>
        <p className="text-xs sm:text-sm text-[var(--text-secondary)]">
          Mã phiên: <span className="font-mono text-[var(--coc-primary)]">{sessionId}</span> • Vị trí:{" "}
          <span className="font-semibold text-[var(--text-primary)]">{reportData?.role || "Software Engineer Intern"}</span>
        </p>
      </div>

      {/* Big Overall Score Card */}
      <div className="rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 backdrop-blur-xl p-8 mb-8 text-center relative overflow-hidden">
        <div className="absolute top-0 right-0 w-64 h-64 bg-[var(--coc-primary)]/10 rounded-full blur-3xl pointer-events-none" />

        <div className="inline-flex items-center justify-center w-32 h-32 rounded-full border-4 border-[var(--coc-primary)] shadow-[var(--shadow-glow)] mb-4">
          <span className="text-4xl font-black text-[var(--coc-primary)] font-mono">{overallScore}</span>
          <span className="text-sm text-[var(--text-muted)] font-mono self-end mb-6">/10</span>
        </div>

        <h2 className="text-xl font-bold text-[var(--text-primary)] mb-1">
          {grade}
        </h2>
        <p className="text-xs text-[var(--text-muted)] max-w-md mx-auto">
          Điểm số được tổng hợp trọng số từ 4 trục: Chuyên môn kỹ thuật (45%), Thẩm định dự án STAR (25%), Tình huống Case study (20%) và Động lực OJT (10%).
        </p>
      </div>

      {/* 4 Radar Dimension Cards */}
      <div className="grid sm:grid-cols-2 gap-4 mb-8">
        {[
          { key: "hr_motivation", label: "Động lực & Tinh thần OJT", weight: "10%", icon: "💡", color: "from-blue-500 to-cyan-400" },
          { key: "project_defense", label: "Thẩm định Dự án STAR (Google XYZ)", weight: "25%", icon: "🎯", color: "from-purple-500 to-pink-400" },
          { key: "technical_core", label: "Nền tảng Chuyên môn Kỹ thuật", weight: "45%", icon: "⚙️", color: "from-[var(--coc-primary)] to-emerald-400" },
          { key: "case_study", label: "Tư duy Xử lý Sự cố (Case Study)", weight: "20%", icon: "🧠", color: "from-orange-500 to-yellow-400" },
        ].map((axis) => {
          const score = radarScores[axis.key as keyof typeof radarScores] || 7.0;
          const pct = Math.round(score * 10);
          return (
            <div key={axis.key} className="rounded-2xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/50 p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">{axis.icon}</span>
                  <div>
                    <h3 className="text-xs font-bold text-[var(--text-primary)]">{axis.label}</h3>
                    <span className="text-[10px] text-[var(--text-muted)]">Trọng số: {axis.weight}</span>
                  </div>
                </div>
                <span className="text-xl font-black text-[var(--text-primary)] font-mono">{score}/10</span>
              </div>
              <div className="w-full h-2 rounded-full bg-[var(--border-color)] overflow-hidden">
                <div
                  className={`h-full rounded-full bg-gradient-to-r ${axis.color} transition-all duration-1000`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Strengths & Weaknesses Matrix */}
      <div className="grid md:grid-cols-2 gap-6 mb-8">
        {/* Strengths */}
        <div className="rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 p-6">
          <h3 className="text-base font-bold text-[var(--text-primary)] mb-4 flex items-center gap-2 text-emerald-400">
            <CheckCircle className="w-5 h-5" />
            <span>Điểm Mạnh Nổi Bật</span>
          </h3>
          <ul className="space-y-3">
            {(reportData?.strengths && reportData.strengths.length > 0 ? reportData.strengths : [
              "Chưa ghi nhận điểm mạnh cụ thể trong phiên này.",
            ]).map((s: string, i: number) => (
              <li key={i} className="flex items-start gap-2.5 text-xs text-[var(--text-secondary)] leading-relaxed">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mt-1.5 shrink-0" />
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Weaknesses */}
        <div className="rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 p-6">
          <h3 className="text-base font-bold text-[var(--text-primary)] mb-4 flex items-center gap-2 text-amber-400">
            <AlertTriangle className="w-5 h-5" />
            <span>Lỗ Hổng Cần Đào Sâu Cải Thiện</span>
          </h3>
          <ul className="space-y-3">
            {(reportData?.weaknesses && reportData.weaknesses.length > 0 ? reportData.weaknesses : [
              "Chưa ghi nhận lỗ hổng cụ thể.",
            ]).map((s: string, i: number) => (
              <li key={i} className="flex items-start gap-2.5 text-xs text-[var(--text-secondary)] leading-relaxed">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 shrink-0" />
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Turn Evaluations & Better Answer Examples */}
      {reportData?.turn_evaluations && reportData.turn_evaluations.length > 0 && (
        <div className="rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 p-6 mb-8">
          <div className="flex items-center gap-2 mb-4 text-[var(--coc-accent)]">
            <FileCheck2 className="w-5 h-5" />
            <h3 className="text-base font-bold text-[var(--text-primary)]">
              Chi Tiết Từng Lượt Trả Lời & Gợi Ý Nâng Cấp (Better-Answer Hints)
            </h3>
          </div>
          <div className="space-y-4">
            {reportData.turn_evaluations.map((t: any, idx: number) => (
              <div
                key={idx}
                className="p-4 rounded-2xl bg-[var(--bg-primary)] border border-[var(--border-color)] space-y-2 text-xs"
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-[var(--coc-primary)] font-mono">
                    Lượt {t.turn_number}: {t.stage}
                  </span>
                  <span className="font-bold font-mono px-2 py-0.5 rounded bg-[var(--coc-primary)]/10 text-[var(--coc-primary)]">
                    {t.score}/10
                  </span>
                </div>
                <p className="font-semibold text-[var(--text-primary)]">{t.question}</p>
                <p className="text-[var(--text-secondary)]">
                  <span className="text-[var(--text-muted)]">Nhận xét:</span> {t.candidate_summary}
                </p>
                <div className="p-2.5 rounded-xl bg-[var(--coc-accent)]/10 border border-[var(--coc-accent)]/20 text-cyan-300">
                  <span className="font-semibold">💡 Gợi ý trả lời xuất sắc hơn:</span> {t.better_answer_hint}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Personalized Learning Roadmap */}
      <div className="rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 p-6 mb-8">
        <h3 className="text-base font-bold text-[var(--text-primary)] mb-4 flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-[var(--coc-accent)]" />
          <span>Lộ Trình Học Tập Cá Nhân Hóa (Personalized Roadmap)</span>
        </h3>
        <div className="space-y-3">
          {(reportData?.learning_roadmap && reportData.learning_roadmap.length > 0 ? reportData.learning_roadmap : [
            { skill: "Nền tảng chuyên môn", action: "Hoàn thành các lượt phỏng vấn để hệ thống phân tích lộ trình", estimated_hours: 0, priority: "LOW" },
          ]).map((item: any, i: number) => (
            <div
              key={i}
              className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-color)] gap-2"
            >
              <div>
                <span className="font-semibold text-xs text-[var(--text-primary)]">{item.skill}</span>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">{item.action}</p>
              </div>
              <div className="flex items-center gap-2 self-start sm:self-auto">
                <span className="text-xs font-mono text-[var(--text-muted)]">{item.estimated_hours} giờ</span>
                <span
                  className={`text-[10px] font-bold px-2 py-0.5 rounded-md ${
                    item.priority === "HIGH"
                      ? "bg-red-500/10 text-red-400 border border-red-500/20"
                      : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                  }`}
                >
                  {item.priority}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Retry Questions Queue */}
      <div className="rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 p-6 mb-8">
        <h3 className="text-base font-bold text-[var(--text-primary)] mb-4 flex items-center gap-2">
          <RotateCcw className="w-5 h-5 text-[var(--coc-primary)]" />
          <span>Hàng Đợi Luyện Lại (Candidate Retry Queue §7.3)</span>
        </h3>
        <div className="space-y-2">
          {(reportData?.retry_recommendations && reportData.retry_recommendations.length > 0 ? reportData.retry_recommendations : [
            "Chưa có câu hỏi trong hàng đợi luyện lại.",
          ]).map((q: string, i: number) => (
            <div
              key={i}
              className="p-3 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-color)] text-xs text-[var(--text-secondary)] flex items-center gap-2"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--coc-primary)] shrink-0" />
              <span>{q}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
        <Link
          href="/interview"
          className="w-full sm:w-auto px-6 py-3 rounded-2xl bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] text-white text-xs font-bold shadow-md hover:shadow-lg transition-all flex items-center justify-center gap-2"
        >
          <span>Luyện tập phiên mới với các câu hỏi retry</span>
          <ArrowRight className="w-4 h-4" />
        </Link>
        <Link
          href="/"
          className="w-full sm:w-auto px-6 py-3 rounded-2xl bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-secondary)] text-xs font-bold hover:bg-[var(--border-color)] transition-all text-center"
        >
          Về trang chủ
        </Link>
      </div>
    </div>
  );
}
