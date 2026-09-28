"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, FileText, Target, CheckCircle2, AlertCircle, ArrowRight } from "lucide-react";
import { CVUploader } from "@/components/cv/CVUploader";
import { GapAnalysisCard } from "@/components/cv/GapAnalysisCard";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function CVLabPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [studentId, setStudentId] = useState("");
  const [jdText, setJdText] = useState("");
  const [targetCompany, setTargetCompany] = useState("FPT Software");
  const [targetRole, setTargetRole] = useState("Backend Engineer Intern");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<"upload" | "analysis" | "gaps">("upload");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Analysis result states
  const [profile, setProfile] = useState<any>(null);
  const [atsResult, setAtsResult] = useState<any>(null);
  const [xyzResult, setXyzResult] = useState<any>(null);
  const [gapResult, setGapResult] = useState<any>(null);

  // Load saved MSSV from localStorage
  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedSid = localStorage.getItem("coc_student_id");
      if (savedSid && !studentId) {
        setStudentId(savedSid);
      }
    }
  }, []);

  const handleSetStudentId = (sid: string) => {
    setStudentId(sid);
    if (typeof window !== "undefined") {
      localStorage.setItem("coc_student_id", sid);
    }
  };

  const handleFillSampleCV = async () => {
    try {
      setLoading(true);
      const res = await fetch("/sample_cv_nguyen_van_an.txt");
      const text = await res.text();
      const sampleFile = new File([text], "CV_Nguyen_Van_An_Java.txt", { type: "text/plain" });
      setFile(sampleFile);
      if (!studentId) {
        handleSetStudentId("SE180000");
      }
    } catch (e: any) {
      console.warn("Failed to load sample CV:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleFillSampleJD = async () => {
    try {
      const res = await fetch("/sample_jd_fpt.txt");
      const text = await res.text();
      setJdText(text);
      setTargetCompany("FPT Software");
      setTargetRole("Java Developer (Japan Project)");
    } catch (e: any) {
      console.warn("Failed to load sample JD:", e);
    }
  };

  const handleUploadAndAnalyze = useCallback(async () => {
    if (!file || !studentId) {
      setErrorMessage("Vui lòng nhập MSSV và tải lên file CV");
      return;
    }
    setLoading(true);
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
        throw new Error(`Upload failed: ${res.statusText}`);
      }

      const data = await res.json();
      setProfile(data.profile);
      setAtsResult(data.ats_audit);
      setXyzResult(data.xyz_scores);
      setStep("analysis");
    } catch (err: any) {
      console.error("Upload error:", err);
      setErrorMessage(err.message || "Không thể phân tích CV, vui lòng thử lại");
    } finally {
      setLoading(false);
    }
  }, [file, studentId]);

  const handleGapAnalysis = useCallback(async () => {
    if (!profile || !jdText) {
      setErrorMessage("Vui lòng nhập nội dung bản mô tả công việc (JD)");
      return;
    }
    setLoading(true);
    setErrorMessage(null);

    try {
      const formData = new FormData();
      formData.append("student_id", studentId);
      formData.append("jd_text", jdText);
      formData.append("profile", JSON.stringify(profile));

      const res = await fetch(`${API_BASE}/api/v1/cv/analyze-gaps`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        throw new Error(`Gap analysis failed: ${res.statusText}`);
      }

      const data = await res.json();
      setGapResult(data.gap_analysis);
      setStep("gaps");
    } catch (err: any) {
      console.error("Gap analysis error:", err);
      setErrorMessage(err.message || "Phân tích JD thất bại");
    } finally {
      setLoading(false);
    }
  }, [profile, jdText, studentId]);

  // Bridge to interview room
  const handleStartInterviewWithSeeds = async () => {
    setLoading(true);
    try {
      const finalSid = studentId || "SE180000";
      // Create session in backend
      const res = await fetch(`${API_BASE}/api/v1/sessions/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: finalSid,
          target_company: targetCompany || "FPT Software",
          target_role: targetRole || "Java Developer",
          domain_pack: "it_software",
          skill_gaps: gapResult?.critical_hard_gaps?.map((g: any) => g.skill) || [],
        }),
      });

      if (!res.ok) {
        throw new Error("Không thể khởi tạo phiên phỏng vấn");
      }

      const data = await res.json();
      router.push(`/interview/${data.session_id}`);
    } catch (e: any) {
      console.error("Session creation error:", e);
      // Fallback
      router.push(`/interview`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Page Header */}
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-[var(--coc-primary)]/10 text-[var(--coc-primary)] text-xs font-semibold mb-3 border border-[var(--coc-primary)]/20">
          <Sparkles className="w-3.5 h-3.5" />
          <span>Phân Hệ 1: CV & JD Lab Thực Chiến</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-extrabold text-[var(--text-primary)] mb-3">
          Lab Tối Ưu CV Theo Chuẩn Doanh Nghiệp
        </h1>
        <p className="text-sm text-[var(--text-secondary)] max-w-xl mx-auto">
          Pipeline 4 tầng: Trích xuất hồ sơ → Kiểm toán ATS → Phân tích Gap vs JD → Cầu nối sinh câu hỏi phỏng vấn.
        </p>
      </div>

      {/* Stepper Indicator */}
      <div className="flex items-center justify-center gap-3 mb-10">
        {[
          { key: "upload", label: "1. Tải CV" },
          { key: "analysis", label: "2. Kiểm toán ATS & XYZ" },
          { key: "gaps", label: "3. So khớp JD & Bridge" },
        ].map((s, i) => {
          const stepOrder = ["upload", "analysis", "gaps"];
          const currentIdx = stepOrder.indexOf(step);
          const isDone = i < currentIdx;
          const isCurrent = i === currentIdx;

          return (
            <div key={s.key} className="flex items-center gap-2">
              <div
                className={`px-3.5 py-1.5 rounded-full text-xs font-bold transition-all ${
                  isCurrent
                    ? "bg-[var(--coc-primary)] text-white shadow-[0_0_15px_rgba(34,197,94,0.4)]"
                    : isDone
                    ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                    : "bg-[var(--bg-secondary)] text-[var(--text-muted)] border border-[var(--border-color)]"
                }`}
              >
                {s.label}
              </div>
              {i < 2 && <div className="w-6 h-0.5 bg-[var(--border-color)]" />}
            </div>
          );
        })}
      </div>

      {errorMessage && (
        <div className="max-w-xl mx-auto mb-6 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Step 1: Upload */}
      {step === "upload" && (
        <div className="max-w-2xl mx-auto rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 backdrop-blur-xl p-8 space-y-6">
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)] mb-2">
              Mã Số Sinh Viên (MSSV)
            </label>
            <input
              type="text"
              value={studentId}
              onChange={(e) => setStudentId(e.target.value.toUpperCase())}
              placeholder="VD: HE181234, SE170456..."
              className="w-full px-4 py-3 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-primary)] font-mono text-sm focus:border-[var(--coc-primary)] focus:outline-none transition-all"
            />
          </div>

          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)] mb-2">
              File CV (PDF / DOCX)
            </label>
            <CVUploader
              onFileSelected={(f) => setFile(f)}
              selectedFile={file}
              isAnalyzing={loading}
              onClearFile={() => setFile(null)}
            />
          </div>

          <div className="pt-2 border-t border-[var(--border-color)] flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Muốn thử nghiệm nhanh?</span>
            <button
              type="button"
              onClick={handleFillSampleCV}
              disabled={loading}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-[var(--coc-primary)]/15 text-[var(--coc-primary)] border border-[var(--coc-primary)]/30 hover:bg-[var(--coc-primary)]/25 flex items-center gap-1.5 transition-colors"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Nạp nhanh CV mẫu (Nguyễn Văn An)</span>
            </button>
          </div>

          <button
            onClick={handleUploadAndAnalyze}
            disabled={!file || !studentId || loading}
            className="w-full py-3.5 rounded-2xl bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] text-white text-sm font-bold shadow-[var(--shadow-glow)] hover:shadow-lg disabled:opacity-50 transition-all flex items-center justify-center gap-2"
          >
            {loading ? (
              <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                <span>Tiến hành trích xuất & Kiểm toán</span>
              </>
            )}
          </button>
        </div>
      )}

      {/* Step 2: ATS & XYZ Analysis */}
      {step === "analysis" && profile && (
        <div className="max-w-4xl mx-auto space-y-6">
          {/* Extracted Profile */}
          <div className="rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 p-6 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-[var(--border-color)]">
              <h3 className="text-base font-bold text-[var(--text-primary)] flex items-center gap-2">
                <FileText className="w-4 h-4 text-[var(--coc-primary)]" />
                <span>Thông Tin Ứng Viên Trích Xuất</span>
              </h3>
              <span className="text-xs font-mono text-[var(--text-muted)]">{studentId}</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div>
                <span className="text-[var(--text-muted)]">Họ tên:</span>{" "}
                <span className="font-semibold text-[var(--text-primary)]">
                  {profile.candidate_name || "Ứng viên FPT"}
                </span>
              </div>
              <div>
                <span className="text-[var(--text-muted)]">Email:</span>{" "}
                <span className="font-semibold text-[var(--text-primary)]">
                  {profile.email || "chua_co@fpt.edu.vn"}
                </span>
              </div>
            </div>

            {/* Hard skills badge list */}
            <div>
              <span className="text-xs text-[var(--text-muted)] block mb-1.5">
                Kỹ năng chuyên môn phát hiện:
              </span>
              <div className="flex flex-wrap gap-1.5">
                {(profile.skills?.hard_skills || ["Java", "Spring Boot", "Docker", "SQL"]).map(
                  (sk: string, idx: number) => (
                    <span
                      key={idx}
                      className="px-2.5 py-0.5 rounded-md bg-[var(--coc-primary)]/10 text-[var(--coc-primary)] text-xs font-mono"
                    >
                      {sk}
                    </span>
                  )
                )}
              </div>
            </div>
          </div>

          {/* JD Input Area */}
          <div className="rounded-3xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40 p-6 space-y-4">
            <div className="flex items-center gap-2 pb-2">
              <Target className="w-5 h-5 text-[var(--coc-accent)]" />
              <h3 className="text-base font-bold text-[var(--text-primary)]">
                Nhập Bản Mô Tả Công Việc (JD) Mục Tiêu
              </h3>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1">
                  Công ty mục tiêu
                </label>
                <input
                  type="text"
                  value={targetCompany}
                  onChange={(e) => setTargetCompany(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-color)] text-xs text-[var(--text-primary)]"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1">
                  Vị trí ứng tuyển
                </label>
                <input
                  type="text"
                  value={targetRole}
                  onChange={(e) => setTargetRole(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-color)] text-xs text-[var(--text-primary)]"
                />
              </div>
            </div>

            <div className="flex justify-between items-center pt-2">
              <label className="text-xs font-semibold text-[var(--text-secondary)]">
                Nội dung Job Description (JD)
              </label>
              <button
                type="button"
                onClick={handleFillSampleJD}
                className="text-xs font-semibold px-3 py-1 rounded-lg bg-[var(--coc-accent)]/15 text-[var(--coc-accent)] border border-[var(--coc-accent)]/30 hover:bg-[var(--coc-accent)]/25 flex items-center gap-1.5 transition-colors"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>Dán nhanh JD FPT Software</span>
              </button>
            </div>

            <textarea
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              placeholder="Dán nội dung JD (yêu cầu kỹ năng, mô tả dự án, trách nhiệm) vào đây..."
              rows={6}
              className="w-full p-4 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-color)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--coc-primary)] font-sans"
            />

            <button
              onClick={handleGapAnalysis}
              disabled={!jdText.trim() || loading}
              className="w-full py-3 rounded-2xl bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] text-white text-xs font-bold flex items-center justify-center gap-2 shadow-md disabled:opacity-50"
            >
              {loading ? (
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <>
                  <span>Phân tích khoảng cách & Sinh hạt giống phỏng vấn</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Gap Analysis & Blueprint Seeds */}
      {step === "gaps" && gapResult && (
        <div className="max-w-4xl mx-auto space-y-6">
          <GapAnalysisCard
            atsScore={atsResult?.ats_score || 85}
            xyzScore={xyzResult?.formula_score || 78}
            matchScore={gapResult?.match_score || 82}
            matchedSkills={gapResult?.matched_skills || ["Java", "RESTful API", "Git"]}
            missingSkills={gapResult?.critical_hard_gaps?.map((g: any) => g.skill) || ["Kubernetes", "Kafka", "Microservices"]}
            interviewSeeds={
              gapResult?.interview_seeds || [
                "Hãy giải thích cách em triển khai giao tiếp bất đồng bộ khi khối lượng tải tăng cao trong hệ thống Backend?",
                "Kinh nghiệm xử lý transaction phân tán và tính toàn vẹn dữ liệu trong cơ sở dữ liệu?",
                "Mô tả quy trình cấu hình container và CI/CD pipeline em từng tham gia.",
              ]
            }
            onStartInterviewWithSeeds={handleStartInterviewWithSeeds}
          />
        </div>
      )}
    </div>
  );
}
