"use client";

import Link from "next/link";
import { FileText, Mic, BarChart3, ArrowRight, Sparkles, Shield, Brain, Zap } from "lucide-react";

export default function HomePage() {
  return (
    <div className="relative overflow-hidden">
      {/* Background Orbs */}
      <div className="orb w-96 h-96 bg-[var(--coc-primary)] top-20 -left-48" />
      <div className="orb w-80 h-80 bg-[var(--coc-accent)] top-60 right-0" />
      <div className="orb w-64 h-64 bg-purple-500 bottom-40 left-1/3" />

      {/* Hero Section */}
      <section className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-20 pb-32">
        <div className="text-center">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-[var(--coc-primary)]/10 border border-[var(--coc-primary)]/20 mb-8">
            <Sparkles className="w-4 h-4 text-[var(--coc-primary)]" />
            <span className="text-sm font-medium text-[var(--coc-primary)]">
              AI Voice Interview Practice
            </span>
          </div>

          {/* Title */}
          <h1 className="text-5xl sm:text-6xl lg:text-7xl font-bold tracking-tight mb-6">
            <span className="gradient-text">Cóc Đi Làm</span>
            <br />
            <span className="text-[var(--text-primary)]">
              Phòng Lab Phỏng Vấn
            </span>
            <br />
            <span className="text-[var(--text-secondary)] text-3xl sm:text-4xl lg:text-5xl">
              OJT Thực Chiến
            </span>
          </h1>

          {/* Subtitle */}
          <p className="text-lg sm:text-xl text-[var(--text-secondary)] max-w-2xl mx-auto mb-10 leading-relaxed">
            Đồng hành từ <strong className="text-[var(--text-primary)]">tối ưu CV</strong> đến{" "}
            <strong className="text-[var(--text-primary)]">phỏng vấn 1-1 bằng giọng nói</strong> thời gian thực.
            Phản hồi chi tiết giúp bạn bịt mọi lỗ hổng trước phỏng vấn thật.
          </p>

          {/* CTA Buttons */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link href="/cv-lab" className="btn-primary flex items-center gap-2 text-base">
              <FileText className="w-5 h-5" />
              Tối ưu CV ngay
              <ArrowRight className="w-4 h-4" />
            </Link>
            <Link href="/interview" className="btn-secondary flex items-center gap-2 text-base">
              <Mic className="w-5 h-5" />
              Bắt đầu phỏng vấn thử
            </Link>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-24">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-bold text-[var(--text-primary)] mb-4">
            Hai Phân Hệ Hoàn Chỉnh
          </h2>
          <p className="text-[var(--text-secondary)] max-w-xl mx-auto">
            Từ chuẩn bị hồ sơ đến thực chiến phỏng vấn — tất cả trong một nền tảng
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-6 max-w-5xl mx-auto">
          {/* Module 1: CV Lab */}
          <Link href="/cv-lab" className="glass-card p-8 group cursor-pointer">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center">
                <FileText className="w-6 h-6 text-white" />
              </div>
              <div>
                <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                  Phân hệ 1
                </span>
                <h3 className="text-xl font-bold text-[var(--text-primary)]">
                  Lab Tối ưu CV
                </h3>
              </div>
            </div>
            <p className="text-[var(--text-secondary)] leading-relaxed mb-4">
              Rà soát CV theo chuẩn ATS, đánh giá Google XYZ Formula,
              phân tích khoảng cách kỹ năng so với JD thực tế.
            </p>
            <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--coc-primary)]" />
                Hỗ trợ PDF, DOCX, ảnh CV (OCR)
              </li>
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--coc-primary)]" />
                So khớp kỹ năng với JD doanh nghiệp
              </li>
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--coc-primary)]" />
                Gợi ý viết lại từng câu theo chuẩn
              </li>
            </ul>
            <div className="mt-6 flex items-center gap-2 text-[var(--coc-primary)] font-medium text-sm
              group-hover:translate-x-1 transition-transform duration-200">
              Bắt đầu tối ưu <ArrowRight className="w-4 h-4" />
            </div>
          </Link>

          {/* Module 2: Interview Room */}
          <Link href="/interview" className="glass-card p-8 group cursor-pointer">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-[var(--coc-primary)] to-emerald-400 flex items-center justify-center pulse-glow">
                <Mic className="w-6 h-6 text-white" />
              </div>
              <div>
                <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                  Phân hệ 2
                </span>
                <h3 className="text-xl font-bold text-[var(--text-primary)]">
                  Phỏng vấn Voice 1-1
                </h3>
              </div>
            </div>
            <p className="text-[var(--text-secondary)] leading-relaxed mb-4">
              Phỏng vấn thực chiến bằng giọng nói với AI,
              4 vòng đánh giá toàn diện, phản hồi chi tiết theo bằng chứng.
            </p>
            <ul className="space-y-2 text-sm text-[var(--text-secondary)]">
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--coc-primary)]" />
                Giọng nói realtime Edge AI (không upload audio)
              </li>
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--coc-primary)]" />
                4 vòng: HR → STAR → Chuyên môn → Case Study
              </li>
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--coc-primary)]" />
                Báo cáo Radar 4 trục + lộ trình cải thiện
              </li>
            </ul>
            <div className="mt-6 flex items-center gap-2 text-[var(--coc-primary)] font-medium text-sm
              group-hover:translate-x-1 transition-transform duration-200">
              Vào phòng phỏng vấn <ArrowRight className="w-4 h-4" />
            </div>
          </Link>
        </div>
      </section>

      {/* Tech Highlights */}
      <section className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-24">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            {
              icon: Brain,
              title: "Edge AI Voice",
              desc: "VAD + STT + TTS chạy 100% trên trình duyệt, không upload audio",
            },
            {
              icon: Shield,
              title: "Privacy First",
              desc: "Raw audio không bao giờ rời thiết bị trong interview path",
            },
            {
              icon: BarChart3,
              title: "Evidence-Based",
              desc: "Chấm điểm theo bằng chứng, không suy đoán chủ quan",
            },
            {
              icon: Zap,
              title: "Realtime",
              desc: "WebSocket streaming, phản hồi dưới giây, chen ngang thông minh",
            },
          ].map((item, i) => (
            <div key={i} className="glass-card p-6 text-center">
              <div className="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-[var(--coc-primary)]/10 mb-3">
                <item.icon className="w-5 h-5 text-[var(--coc-primary)]" />
              </div>
              <h3 className="font-semibold text-[var(--text-primary)] mb-1">{item.title}</h3>
              <p className="text-xs text-[var(--text-secondary)]">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
