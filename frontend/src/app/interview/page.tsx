"use client";

import { useEffect, useState } from "react";
import { Mic, Briefcase, ArrowRight, Users, FileText, Sparkles, AlertCircle } from "lucide-react";
import { GuestModal } from "@/components/common/GuestModal";
import { CVUploader } from "@/components/cv/CVUploader";
import { useRouter } from "next/navigation";
import { buildInterviewRequest, matchesFramework, resolveInterviewFramework, jobsMatchingCandidate, jobsMatchingCv, jobsWithFramework, type CandidateChoice, type JobChoice, type FrameworkChoice } from "@/lib/interviewSetup";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type InterviewCatalogEntry = FrameworkChoice & {
  canonical_role_name: string;
  role_family: string;
  target_competencies: string[];
};
type InterviewCatalogResponse = { available: boolean; frameworks: InterviewCatalogEntry[]; message?: string };
type InterviewOptionsResponse = { available: boolean; candidates: CandidateChoice[]; jobs: JobChoice[]; message?: string };
type UploadedCvMatch = { target_role: string | null; experience_level: string | null; resolved_framework_id: string | null };

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

const inputClass = "w-full px-4 py-3 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] text-sm text-[var(--text-primary)] focus:border-[var(--coc-primary)] focus:outline-none disabled:opacity-50";

export default function InterviewSetupPage() {
  const router = useRouter();
  const [showLogin, setShowLogin] = useState(false);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [candidateName, setCandidateName] = useState("");
  const [hasProfile, setHasProfile] = useState(false);
  const [uploadedCvMatch, setUploadedCvMatch] = useState<UploadedCvMatch | null>(null);
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [isUploadingCv, setIsUploadingCv] = useState(false);
  const [useUploadedCv, setUseUploadedCv] = useState(false);
  const [catalog, setCatalog] = useState<InterviewCatalogEntry[]>([]);
  const [candidates, setCandidates] = useState<CandidateChoice[]>([]);
  const [jobs, setJobs] = useState<JobChoice[]>([]);
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [allowCrossRoleCv, setAllowCrossRoleCv] = useState(false);
  const [customCompany, setCustomCompany] = useState("");
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [isStartingDemo, setIsStartingDemo] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function loadOptions() {
      try {
        const [frameworkResponse, optionsResponse] = await Promise.all([
          fetch(API_BASE + "/api/v1/cv/interview-catalog"),
          fetch(API_BASE + "/api/v1/cv/interview-options"),
        ]);
        if (!frameworkResponse.ok || !optionsResponse.ok) throw new Error("Không tải được danh sách framework/CV/JD từ backend.");
        const frameworks = await frameworkResponse.json() as InterviewCatalogResponse;
        const options = await optionsResponse.json() as InterviewOptionsResponse;
        if (cancelled) return;
        setCatalog(frameworks.frameworks || []);
        setCandidates(options.candidates || []);
        setJobs(options.jobs || []);
        setCatalogError(frameworks.available && options.available ? null : options.message || frameworks.message || "Chưa nạp đủ dữ liệu normalized.");
      } catch (error) {
        if (!cancelled) setCatalogError(errorText(error, "Không kết nối được catalog phỏng vấn."));
      }
    }
    void loadOptions();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const sid = localStorage.getItem("coc_student_id");
    const name = localStorage.getItem("coc_candidate_name");
    // Hydrate browser-only identity after the initial render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (sid) setStudentId(sid);
    if (name) setCandidateName(name);
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!studentId) return;
    fetch(API_BASE + "/api/v1/cv/profile/" + encodeURIComponent(studentId))
      .then(async response => response.ok ? response.json() : { has_profile: false })
      .then(data => { if (!cancelled) { setHasProfile(Boolean(data.has_profile)); setUploadedCvMatch(data.interview_match || null); } })
      .catch(() => { if (!cancelled) { setHasProfile(false); setUploadedCvMatch(null); } });
    return () => { cancelled = true; };
  }, [studentId]);

  const candidate = candidates.find(item => item.candidate_id === selectedCandidateId) || null;
  const selectableJobs = jobsWithFramework(jobs);
  const selectableCandidates = candidates.filter(item => jobsMatchingCandidate(selectableJobs, item).length > 0);
  const unmappedJobCount = jobs.length - selectableJobs.length;
  const filteredJobs = useUploadedCv
    ? jobsMatchingCv(selectableJobs, uploadedCvMatch?.resolved_framework_id, uploadedCvMatch?.experience_level)
    : jobsMatchingCandidate(selectableJobs, candidate);
  const job = filteredJobs.find(item => item.job_id === selectedJobId) || null;
  const framework = resolveInterviewFramework(catalog, candidate, job, useUploadedCv);
  const crossRoleCv = !useUploadedCv && candidate !== null && framework !== null && !matchesFramework(candidate, framework);
  const busy = loading || isStartingDemo;
  const ready = Boolean(framework && job && (useUploadedCv ? hasProfile : candidate) && (!crossRoleCv || allowCrossRoleCv));

  async function handleLogin(sid: string, name: string) {
    setErrorMessage(null);
    try {
      const response = await fetch(API_BASE + "/api/v1/sessions/guest-login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id: sid, candidate_name: name }),
      });
      if (!response.ok) throw new Error("Không đăng nhập được trên backend.");
      localStorage.setItem("coc_student_id", sid);
      localStorage.setItem("coc_candidate_name", name);
      if (sid !== studentId) { setHasProfile(false); setUploadedCvMatch(null); setSelectedJobId(""); }
      setStudentId(sid);
      setCandidateName(name);
      setShowLogin(false);
    } catch (error) {
      setErrorMessage(errorText(error, "Đăng nhập thất bại."));
    }
  }

  async function handleUploadCv(file: File) {
    if (!studentId) { setShowLogin(true); return; }
    setCvFile(file);
    setIsUploadingCv(true);
    setHasProfile(false);
    setUploadedCvMatch(null);
    setSelectedJobId("");
    setErrorMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("student_id", studentId);
      const response = await fetch(API_BASE + "/api/v1/cv/upload", { method: "POST", body: form });
      if (!response.ok) throw new Error("Không đọc được CV đã tải lên.");
      const uploaded = await response.json() as { interview_match?: UploadedCvMatch };
      setUploadedCvMatch(uploaded.interview_match || null);
      setHasProfile(true);
    } catch (error) {
      setErrorMessage(errorText(error, "Tải CV thất bại."));
    } finally {
      setIsUploadingCv(false);
    }
  }

  async function createSelectedSession(sid: string, demo: boolean) {
    // Both entry points serialize exactly the selected CV/JD IDs, never sample_pair.
    const request = buildInterviewRequest({
      studentId: sid, framework, candidate, job, useUploadedCv: demo ? false : useUploadedCv,
      hasProfile, allowCrossRoleCv, customCompany,
    });
    const response = await fetch(API_BASE + "/api/v1/sessions/create", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Không thể tạo phiên phỏng vấn.");
    }
    const session = await response.json();
    router.push("/interview/" + session.session_id);
  }

  async function handleStart() {
    if (!studentId) { setShowLogin(true); return; }
    setErrorMessage(null);
    setLoading(true);
    try { await createSelectedSession(studentId, false); }
    catch (error) { setErrorMessage(errorText(error, "Lỗi tạo phiên.")); }
    finally { setLoading(false); }
  }

  async function handleStartDemo() {
    if (!ready || !framework || !candidate || useUploadedCv) return;
    setErrorMessage(null);
    setIsStartingDemo(true);
    const demoId = "DEMO_" + framework.framework_id;
    try {
      const response = await fetch(API_BASE + "/api/v1/sessions/guest-login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id: demoId, candidate_name: candidate.candidate_id }),
      });
      if (!response.ok) throw new Error("Không đăng nhập được tài khoản demo.");
      localStorage.setItem("coc_student_id", demoId);
      localStorage.setItem("coc_candidate_name", candidate.candidate_id);
      setStudentId(demoId);
      setCandidateName(candidate.candidate_id);
      await createSelectedSession(demoId, true);
    } catch (error) { setErrorMessage(errorText(error, "Không tạo được phiên demo.")); }
    finally { setIsStartingDemo(false); }
  }

  return (
    <div className="relative max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <GuestModal isOpen={showLogin} onClose={() => setShowLogin(false)} onSubmit={handleLogin} />
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--coc-primary)]/10 text-[var(--coc-primary)] text-xs font-semibold mb-3 border border-[var(--coc-primary)]/20">
          <Sparkles className="w-3.5 h-3.5" /><span>Luyện Phỏng Vấn Giọng Nói 1-1</span>
        </div>
        <h1 className="text-3xl sm:text-4xl font-extrabold text-[var(--text-primary)] mb-3">Thiết Lập Phiên Phỏng Vấn OJT Thực Chiến</h1>
        <p className="text-sm text-[var(--text-secondary)]">Chọn CV; chuyên môn và cấp độ được lấy từ CV để lọc JD phù hợp. Khung phỏng vấn lấy theo JD đã chọn.</p>
        {!studentId ? (
          <button onClick={() => setShowLogin(true)} className="btn-secondary mt-4 inline-flex items-center gap-2"><Users className="w-4 h-4" />Đăng nhập MSSV để tiếp tục</button>
        ) : (
          <div className="flex items-center justify-center gap-2 mt-3 text-xs">
            <span className="text-[var(--coc-primary)] font-semibold">Ứng viên: {candidateName || studentId} ({studentId})</span>
            <button onClick={() => setShowLogin(true)} className="text-[var(--text-muted)] hover:underline">(Đổi tài khoản)</button>
          </div>
        )}
      </div>

      {errorMessage && <p role="alert" className="mb-6 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">{errorMessage}</p>}

      <section className="glass-card rounded-3xl p-6 mb-8">
        <h2 className="text-base font-bold mb-4 flex items-center gap-2"><FileText className="w-5 h-5 text-[var(--coc-primary)]" />1. Chọn CV và JD</h2>
        {catalogError && <p role="alert" className="text-xs text-amber-300 mb-3">{catalogError}</p>}
        {!useUploadedCv && candidate && <p role="status" className="text-xs text-[var(--text-secondary)] mb-4">
          CV: {candidate.target_role} · {candidate.experience_level || "chưa rõ cấp độ"}. Có {filteredJobs.length} JD đúng chuyên môn và cấp độ.
        </p>}
        {useUploadedCv && hasProfile && <p role="status" className="text-xs text-[var(--text-secondary)] mb-4">
          CV tải lên: {uploadedCvMatch?.target_role || "chưa nhận diện được vị trí"} · {uploadedCvMatch?.experience_level || "chưa nhận diện được cấp độ"}. Có {filteredJobs.length} JD phù hợp.
        </p>}
        {unmappedJobCount > 0 && <p role="status" className="text-xs text-amber-300 mb-4">Đã ẩn {unmappedJobCount} JD chưa ánh xạ được khung phỏng vấn.</p>}
        <div className="flex flex-wrap gap-2 mb-4">
          <button type="button" disabled={busy} onClick={() => { setUseUploadedCv(false); setSelectedJobId(""); setErrorMessage(null); }}
            className={"text-xs font-semibold px-3 py-2 rounded-lg border " + (!useUploadedCv ? "border-[var(--coc-primary)] text-[var(--coc-primary)] bg-[var(--coc-primary)]/10" : "border-[var(--border-color)] text-[var(--text-secondary)]")}>Chọn CV trong dữ liệu</button>
          <button type="button" disabled={busy} onClick={() => { setUseUploadedCv(true); setSelectedJobId(""); setAllowCrossRoleCv(false); setErrorMessage(null); }}
            className={"text-xs font-semibold px-3 py-2 rounded-lg border " + (useUploadedCv ? "border-[var(--coc-primary)] text-[var(--coc-primary)] bg-[var(--coc-primary)]/10" : "border-[var(--border-color)] text-[var(--text-secondary)]")}>Tải CV của tôi</button>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="rounded-xl border border-[var(--border-color)] p-4 min-w-0">
            <label htmlFor="cv-choice" className="block text-xs font-semibold text-[var(--text-secondary)] mb-2">CV ứng viên ({selectableCandidates.length} hồ sơ có JD phù hợp)</label>
            <select id="cv-choice" value={selectedCandidateId} disabled={useUploadedCv || !selectableCandidates.length || busy} className={inputClass}
              onChange={event => { setSelectedCandidateId(event.target.value); setSelectedJobId(""); setAllowCrossRoleCv(false); setErrorMessage(null); }}>
              <option value="">— Chọn CV —</option>
              {selectableCandidates.map(item => <option key={item.candidate_id} value={item.candidate_id}>{item.candidate_id} · {item.target_role} · {item.experience_level || "cấp độ chưa rõ"} · {item.project_count} dự án</option>)}
            </select>
            {!useUploadedCv && candidates.length > selectableCandidates.length && <p className="text-xs text-[var(--text-muted)] mt-2">Đã ẩn {candidates.length - selectableCandidates.length} CV chưa có JD cùng chuyên môn và cấp độ trong bộ dữ liệu.</p>}
            {!useUploadedCv && candidate && <p className="text-xs text-[var(--text-muted)] mt-3">Kỹ năng: {candidate.skills.slice(0, 8).join(", ") || "chưa có"} · {candidate.project_count} dự án</p>}
            {useUploadedCv && <p className="text-xs text-[var(--text-muted)] mt-3">Dùng CV đã upload ở bên dưới; không gửi candidate_id của CV mẫu.</p>}
          </div>
          <div className="rounded-xl border border-[var(--border-color)] p-4 min-w-0">
            <label htmlFor="jd-choice" className="block text-xs font-semibold text-[var(--text-secondary)] mb-2">JD công việc ({filteredJobs.length} phù hợp)</label>
            <select id="jd-choice" value={job?.job_id || ""} disabled={!filteredJobs.length || busy} className={inputClass} onChange={event => { setSelectedJobId(event.target.value); setAllowCrossRoleCv(false); setErrorMessage(null); }}>
              <option value="">— Chọn JD —</option>
              {filteredJobs.map(item => <option key={item.job_id} value={item.job_id}>{item.job_id} · {item.title} · {(item.levels || []).join("/") || "Cấp độ chưa rõ"} · {item.company}</option>)}
            </select>
            {job && <div className="text-xs text-[var(--text-muted)] mt-3"><p>{job.company} · {(job.levels || []).join(" / ") || "Cấp độ chưa rõ hoặc dữ liệu mâu thuẫn"}</p><p className="mt-1">Yêu cầu: {job.required_skills.slice(0, 8).join(", ") || "theo JD"}</p></div>}
            {!filteredJobs.length && candidate && !useUploadedCv && <p className="text-xs text-amber-300 mt-3">Không có JD đúng chuyên môn và cấp độ trong CV này. Hệ thống không tự ghép JD khác ngành/cấp độ.</p>}
            {!filteredJobs.length && useUploadedCv && hasProfile && <p className="text-xs text-amber-300 mt-3">CV tải lên chưa nêu rõ vị trí/cấp độ, hoặc không có JD khớp. Hệ thống không tự ghép JD khác ngành/cấp độ.</p>}
          </div>
        </div>
        <h2 className="text-base font-bold mt-6 mb-3 flex items-center gap-2"><Briefcase className="w-5 h-5 text-[var(--coc-primary)]" />2. Khung phỏng vấn tự động</h2>
        <div id="auto-framework" role="status" aria-live="polite" data-framework-id={framework?.framework_id || ""} className="rounded-2xl border border-[var(--coc-primary)]/30 bg-[var(--coc-primary)]/5 p-4">
          {framework ? (
            <>
              <p className="text-sm font-semibold">{framework.role_title}</p>
              <p className="text-xs text-[var(--text-muted)] mt-1">Framework <code>{framework.framework_id}</code> · {framework.role_family}</p>
              <p className="text-xs text-[var(--text-secondary)] mt-2">{job ? "Khung theo JD mục tiêu; CV cung cấp bằng chứng kinh nghiệm." : "Tạm xem theo CV. Chọn một JD phù hợp để xác định yêu cầu công việc và công ty."}</p>
              <details className="text-xs text-[var(--text-secondary)] mt-3"><summary className="cursor-pointer">Xem trọng tâm khung phỏng vấn</summary><p className="mt-2">{framework.target_competencies?.join(" · ") || "theo khung chuẩn hóa"}</p></details>
            </>
          ) : <p className="text-xs text-[var(--text-secondary)]">{job || (!useUploadedCv && candidate) ? "CV/JD này chưa có khung phỏng vấn phù hợp trong dữ liệu; không dùng khung sai ngành." : "Chọn CV và JD ở trên để hệ thống xác định khung."}</p>}
        </div>
        {crossRoleCv && (
          <div className="mt-4 rounded-xl bg-amber-500/5 border border-amber-500/30 p-4 text-xs text-amber-300">
            <p className="flex gap-2"><AlertCircle className="w-4 h-4 shrink-0" />CV này thuộc chuyên môn khác. AI dùng đúng kinh nghiệm trong CV, còn câu hỏi/rubric vẫn theo framework và JD đã chọn.</p>
            <label className="flex items-center gap-2 mt-3 cursor-pointer">
              <input type="checkbox" checked={allowCrossRoleCv} disabled={busy} onChange={event => setAllowCrossRoleCv(event.target.checked)} />
              Tôi muốn dùng CV này để luyện phỏng vấn chuyển chuyên môn
            </label>
          </div>
        )}
        <label htmlFor="company-choice" className="block text-xs font-semibold text-[var(--text-secondary)] mt-5 mb-2">Công ty mục tiêu (để trống dùng công ty của JD đã chọn)</label>
        <input id="company-choice" value={customCompany} disabled={busy} onChange={event => setCustomCompany(event.target.value)} placeholder={job?.company || "Tên công ty"} className={inputClass} />
      </section>

      {useUploadedCv && (
        <section className="glass-card rounded-3xl p-6 mb-8">
          <h2 className="text-sm font-bold mb-3">Nạp CV của bạn làm ngữ cảnh phỏng vấn</h2>
          {!studentId ? <button onClick={() => setShowLogin(true)} className="btn-secondary">Đăng nhập MSSV để tải CV</button> : hasProfile ? (
            <div className="flex justify-between gap-3 text-xs"><span className="text-emerald-400">CV của bạn đã sẵn sàng.</span><button onClick={() => { setHasProfile(false); setCvFile(null); }} className="underline">Tải CV khác</button></div>
          ) : <CVUploader selectedFile={cvFile} isAnalyzing={isUploadingCv} onFileSelected={handleUploadCv} onClearFile={() => { setCvFile(null); setHasProfile(false); setUploadedCvMatch(null); setSelectedJobId(""); }} />}
        </section>
      )}

      <div className="text-center mt-8">
        <button onClick={handleStart} disabled={!ready || busy || isUploadingCv} className="btn-primary text-base px-8 py-4 rounded-2xl inline-flex items-center gap-3 disabled:opacity-50">
          {loading ? <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <Mic className="w-5 h-5" />}
          <span>Bắt Đầu Phiên Phỏng Vấn</span><ArrowRight className="w-4 h-4" />
        </button>
        {!ready && <p className="text-xs text-[var(--text-muted)] mt-3">Chọn CV và JD; xác nhận nếu CV khác chuyên môn trước khi bắt đầu.</p>}
      </div>
      {process.env.NODE_ENV === "development" && (
        <div className="mt-8 rounded-2xl border border-cyan-500/30 bg-cyan-500/5 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <p className="text-xs text-[var(--text-secondary)]">Demo dùng đúng CV/JD đang chọn. Câu hỏi mới được model sinh theo framework; cần Gemini có key và quota.</p>
          <button type="button" onClick={handleStartDemo} disabled={!ready || useUploadedCv || busy} className="shrink-0 px-4 py-2.5 rounded-xl border border-cyan-400/40 text-cyan-200 text-xs font-bold disabled:opacity-50">{isStartingDemo ? "Đang tạo phiên..." : "Chạy demo với lựa chọn này"}</button>
        </div>
      )}
    </div>
  );
}
