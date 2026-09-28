"use client";

import { useState, useEffect } from "react";
import { Mic, Building2, Briefcase, ArrowRight, Users, FileText, Sparkles, AlertCircle } from "lucide-react";
import { GuestModal } from "@/components/common/GuestModal";
import { CVUploader } from "@/components/cv/CVUploader";
import { OrchestratorConsole } from "@/components/interview/OrchestratorConsole";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const COMPANIES = [
  { name: "FPT Software", logo: "🏢", roles: ["Java Backend Intern", "React Frontend Intern", ".NET Developer Intern", "Data Analyst Intern"] },
  { name: "VNG Corporation", logo: "🎮", roles: ["Backend Go Intern", "Mobile Developer Intern", "QA Engineer Intern"] },
  { name: "Tiki", logo: "🛒", roles: ["Full-Stack Intern", "Product Management Intern", "Data Science Intern"] },
  { name: "Shopee Vietnam", logo: "🛍️", roles: ["Backend Engineer Intern", "Frontend Engineer Intern"] },
  { name: "Khác", logo: "➕", roles: [] },
];

export default function InterviewSetupPage() {
  const router = useRouter();
  const [showLogin, setShowLogin] = useState(false);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [candidateName, setCandidateName] = useState<string>("");
  const [hasProfile, setHasProfile] = useState(false);
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [isUploadingCv, setIsUploadingCv] = useState(false);

  const [selectedCompany, setSelectedCompany] = useState<typeof COMPANIES[0] | null>(null);
  const [selectedRole, setSelectedRole] = useState("");
  const [customCompany, setCustomCompany] = useState("");
  const [customRole, setCustomRole] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Load saved credentials from localStorage
  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedSid = localStorage.getItem("coc_student_id");
      const savedName = localStorage.getItem("coc_candidate_name");
      if (savedSid) setStudentId(savedSid);
      if (savedName) setCandidateName(savedName);
    }
  }, []);

  // Check candidate profile when studentId is available
  useEffect(() => {
    async function checkProfile() {
      if (!studentId) return;
      try {
        const res = await fetch(`${API_BASE}/api/v1/cv/profile/${studentId}`);
        if (res.ok) {
          const data = await res.json();
          setHasProfile(data.has_profile);
        }
      } catch (err) {
        console.warn("Could not check candidate profile:", err);
      }
    }

    checkProfile();
  }, [studentId]);

  const handleLogin = async (sid: string, name: string) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("coc_student_id", sid);
      localStorage.setItem("coc_candidate_name", name);
    }
    try {
      await fetch(`${API_BASE}/api/v1/sessions/guest-login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id: sid, candidate_name: name }),
      });
      setStudentId(sid);
      setCandidateName(name);
      setShowLogin(false);
    } catch {
      setStudentId(sid);
      setCandidateName(name);
      setShowLogin(false);
    }
  };

  const handleUploadCvMin = async (file: File) => {
    if (!studentId) {
      setShowLogin(true);
      return;
    }

    setCvFile(file);
    setIsUploadingCv(true);
    setErrorMessage(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("student_id", studentId);

      const res = await fetch(`${API_BASE}/api/v1/cv/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        throw new Error("Không thể tải lên và phân tích CV");
      }

      setHasProfile(true);
    } catch (err: any) {
      setErrorMessage(err.message || "Tải lên CV thất bại");
    } finally {
      setIsUploadingCv(false);
    }
  };

  const handleUseSampleCv = async () => {
    if (!studentId) {
      setShowLogin(true);
      return;
    }
    try {
      setIsUploadingCv(true);
      const res = await fetch("/sample_cv_nguyen_van_an.txt");
      const text = await res.text();
      const sampleFile = new File([text], "CV_Nguyen_Van_An_Java.txt", { type: "text/plain" });
      await handleUploadCvMin(sampleFile);
    } catch (err: any) {
      setErrorMessage("Không thể tải CV mẫu: " + err.message);
      setIsUploadingCv(false);
    }
  };

  const handleStart = async () => {
    setErrorMessage(null);
    if (!studentId) {
      setShowLogin(true);
      return;
    }

    if (!hasProfile) {
      setErrorMessage("Vui lòng tải lên CV để hệ thống nạp Candidate Profile trước khi phỏng vấn (§1).");
      return;
    }

    const company = selectedCompany?.name === "Khác" ? customCompany : selectedCompany?.name;
    const role = selectedRole || customRole;
    if (!company || !role) {
      setErrorMessage("Vui lòng chọn hoặc nhập công ty và vị trí ứng tuyển.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/sessions/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: studentId,
          target_company: company,
          target_role: role,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Không thể khởi tạo phiên phỏng vấn trên máy chủ.");
      }

      const data = await res.json();
      router.push(`/interview/${data.session_id}`);
    } catch (err: any) {
      console.error("Session creation error:", err);
      setErrorMessage(err.message || "Lỗi tạo phiên phỏng vấn");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <GuestModal
        isOpen={showLogin}
        onClose={() => setShowLogin(false)}
        onSubmit={handleLogin}
      />

      {/* Header */}
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--coc-primary)]/10 text-[var(--coc-primary)] text-xs font-semibold mb-3 border border-[var(--coc-primary)]/20">
          <Sparkles className="w-3.5 h-3.5" />
          <span>Phân Hệ 2: Phòng Phỏng Vấn Giọng Nói 1-1 Realtime</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-extrabold text-[var(--text-primary)] mb-3">
          Thiết Lập Phiên Phỏng Vấn OJT Thực Chiến
        </h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Chọn doanh nghiệp và vị trí mục tiêu để bắt đầu luyện phỏng vấn áp lực thực tế với AI Interviewer
        </p>

        {!studentId ? (
          <button onClick={() => setShowLogin(true)} className="btn-secondary mt-4 inline-flex items-center gap-2">
            <Users className="w-4 h-4" />
            Đăng nhập MSSV để tiếp tục
          </button>
        ) : (
          <div className="flex items-center justify-center gap-2 mt-3 text-xs">
            <span className="text-[var(--coc-primary)] font-semibold">
              ✅ Ứng viên: {candidateName || studentId} ({studentId})
            </span>
            <button
              onClick={() => setShowLogin(true)}
              className="text-[var(--text-muted)] hover:underline ml-2"
            >
              (Đổi tài khoản)
            </button>
          </div>
        )}
      </div>

      {errorMessage && (
        <div className="max-w-2xl mx-auto mb-6 p-3.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Prerequisite: Candidate Profile / CV (§1) */}
      {studentId && !hasProfile && (
        <div className="rounded-3xl border border-amber-500/30 bg-amber-500/5 p-6 mb-8 max-w-3xl mx-auto">
          <div className="flex items-center gap-2 mb-2 text-amber-400">
            <FileText className="w-5 h-5" />
            <h3 className="text-sm font-bold">
              Yêu cầu tiên quyết (§1): Nạp CV cho Candidate Profile
            </h3>
          </div>
          <p className="text-xs text-[var(--text-secondary)] mb-4">
            Để câu hỏi phỏng vấn bám sát kinh nghiệm và kỹ năng của bạn, vui lòng tải lên file CV (hoặc đã phân tích trước đó ở Phân hệ 1).
          </p>
          <CVUploader
            onFileSelected={handleUploadCvMin}
            selectedFile={cvFile}
            isAnalyzing={isUploadingCv}
            onClearFile={() => setCvFile(null)}
          />

          <div className="mt-4 pt-3 border-t border-amber-500/20 flex flex-col sm:flex-row items-center justify-between gap-2">
            <span className="text-xs text-[var(--text-muted)]">
              Chưa có file CV sẵn trên máy?
            </span>
            <button
              type="button"
              onClick={handleUseSampleCv}
              disabled={isUploadingCv}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-[var(--coc-primary)]/15 text-[var(--coc-primary)] border border-[var(--coc-primary)]/30 hover:bg-[var(--coc-primary)]/25 flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Dùng ngay CV mẫu (Nguyễn Văn An — Java Software Engineer)</span>
            </button>
          </div>
        </div>
      )}

      {studentId && hasProfile && (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-4 mb-8 max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2.5 text-emerald-400">
            <FileText className="w-5 h-5" />
            <span className="text-xs font-semibold">
              Hồ sơ ứng viên (Candidate Profile) đã sẵn sàng cho phỏng vấn
            </span>
          </div>
          <button
            onClick={() => setHasProfile(false)}
            className="text-xs text-[var(--text-muted)] hover:text-white underline"
          >
            Tải lên CV khác
          </button>
        </div>
      )}

      {/* Company Selection */}
      <div className="mb-8">
        <h2 className="text-base font-bold text-[var(--text-primary)] mb-3 flex items-center gap-2">
          <Building2 className="w-5 h-5 text-[var(--coc-primary)]" />
          <span>1. Chọn Doanh Nghiệp Mục Tiêu</span>
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {COMPANIES.map((company) => (
            <button
              key={company.name}
              onClick={() => {
                setSelectedCompany(company);
                setSelectedRole("");
              }}
              className={`glass-card p-4 text-center transition-all cursor-pointer rounded-2xl ${
                selectedCompany?.name === company.name
                  ? "border-[var(--coc-primary)] shadow-[var(--shadow-glow)] bg-[var(--coc-primary)]/10"
                  : "hover:border-[var(--coc-primary)]/50"
              }`}
            >
              <span className="text-3xl block mb-2">{company.logo}</span>
              <span className="text-xs font-semibold text-[var(--text-primary)]">{company.name}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Custom Company Input */}
      {selectedCompany?.name === "Khác" && (
        <div className="glass-card p-5 mb-6 rounded-2xl">
          <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
            Nhập tên công ty tùy chọn
          </label>
          <input
            type="text"
            value={customCompany}
            onChange={(e) => setCustomCompany(e.target.value)}
            placeholder="Ví dụ: Viettel, Techcombank, One Mount..."
            className="w-full px-4 py-2.5 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] text-sm text-[var(--text-primary)] focus:border-[var(--coc-primary)] focus:outline-none"
          />
          <label className="block text-xs font-semibold text-[var(--text-secondary)] mt-3 mb-1">
            Vị trí ứng tuyển
          </label>
          <input
            type="text"
            value={customRole}
            onChange={(e) => setCustomRole(e.target.value)}
            placeholder="Ví dụ: Data Engineer Intern, Mobile Flutter..."
            className="w-full px-4 py-2.5 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] text-sm text-[var(--text-primary)] focus:border-[var(--coc-primary)] focus:outline-none"
          />
        </div>
      )}

      {/* Role Selection */}
      {selectedCompany && selectedCompany.roles.length > 0 && (
        <div className="mb-8">
          <h2 className="text-base font-bold text-[var(--text-primary)] mb-3 flex items-center gap-2">
            <Briefcase className="w-5 h-5 text-[var(--coc-accent)]" />
            <span>2. Chọn Vị Trí Tuyển Dụng OJT</span>
          </h2>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {selectedCompany.roles.map((role) => (
              <button
                key={role}
                onClick={() => setSelectedRole(role)}
                className={`glass-card p-4 text-left transition-all cursor-pointer rounded-2xl ${
                  selectedRole === role
                    ? "border-[var(--coc-primary)] shadow-[var(--shadow-glow)] bg-[var(--coc-primary)]/10"
                    : "hover:border-[var(--coc-primary)]/50"
                }`}
              >
                <span className="text-xs font-bold text-[var(--text-primary)]">{role}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Real-time Model Orchestrator & MCP Web Search Console */}
      {selectedCompany && (
        <OrchestratorConsole
          company={selectedCompany.name === "Khác" ? customCompany : selectedCompany.name}
          role={selectedRole || customRole || ""}
          studentId={studentId}
        />
      )}

      {/* Start Button */}
      {(selectedRole || (selectedCompany?.name === "Khác" && customRole)) && (
        <div className="text-center mt-10">
          <button
            onClick={handleStart}
            disabled={loading}
            className="btn-primary text-base px-10 py-4 rounded-2xl inline-flex items-center gap-3 shadow-[var(--shadow-glow)] disabled:opacity-50"
          >
            {loading ? (
              <span className="w-6 h-6 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <>
                <Mic className="w-6 h-6" />
                <span>Bắt Đầu Phiên Phỏng Vấn</span>
                <ArrowRight className="w-5 h-5" />
              </>
            )}
          </button>
          <p className="text-xs text-[var(--text-muted)] mt-3">
            Phiên phỏng vấn 20-25 phút • Pipeline 4 giai đoạn • Đánh giá theo rubric chuẩn hóa
          </p>
        </div>
      )}
    </div>
  );
}
