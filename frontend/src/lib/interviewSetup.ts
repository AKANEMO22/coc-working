// Shared by normal start and demo: never substitute an automatically chosen pair.
export type CandidateChoice = {
  candidate_id: string;
  target_role: string;
  canonical_role_id: string | null;
  framework_id: string | null;
  resolved_framework_id?: string | null;
  experience_level?: string;
  skills: string[];
  project_count: number;
};

export type JobChoice = {
  job_id: string;
  title: string;
  company: string;
  canonical_role_id: string | null;
  canonical_role_name?: string | null;
  framework_id: string | null;
  resolved_framework_id?: string | null;
  level?: string;
  levels?: string[];
  min_years?: number | null;
  required_skills: string[];
};

export type FrameworkChoice = {
  framework_id: string;
  role_title: string;
  canonical_role_id: string | null;
};

export const JOB_LEVELS = ["Intern", "Fresher", "Junior", "Mid", "Senior"] as const;

export function jobsWithFramework(jobs: JobChoice[]): JobChoice[] {
  return jobs.filter(job => Boolean(job.resolved_framework_id));
}

export function filterJobs(jobs: JobChoice[], roleId: string, level: string): JobChoice[] {
  return jobs.filter(job => (!roleId || job.canonical_role_id === roleId)
    && (!level || (job.levels || []).includes(level)));
}

/** CV metadata is authoritative for the visible JD shortlist. Never fall
 * back to another specialty or hiring level just to keep the list populated. */
export function jobsMatchingCandidate(jobs: JobChoice[], candidate: CandidateChoice | null): JobChoice[] {
  if (!candidate) return [];
  const frameworkId = candidate.resolved_framework_id === undefined
    ? candidate.framework_id : candidate.resolved_framework_id;
  return jobsMatchingCv(jobs, frameworkId, candidate.experience_level);
}

export function jobsMatchingCv(jobs: JobChoice[], frameworkId?: string | null, experienceLevel?: string | null): JobChoice[] {
  const level = (experienceLevel || "").trim();
  if (!frameworkId || !level || !JOB_LEVELS.some(item => item === level)) return [];
  return jobsWithFramework(jobs).filter(job =>
    job.resolved_framework_id === frameworkId && (job.levels || []).includes(level)
  );
}

export function getJobRoleOptions(jobs: JobChoice[], level: string): [string, string][] {
  const available = jobs.filter(job => !level || (job.levels || []).includes(level));
  return Array.from(new Map(available
    .filter(job => job.canonical_role_id)
    .map(job => [job.canonical_role_id as string, job.canonical_role_name || job.canonical_role_id as string])).entries())
    .sort((a, b) => a[1].localeCompare(b[1]));
}

export function getJobLevelOptions(jobs: JobChoice[], roleId: string): string[] {
  const available = new Set(jobs
    .filter(job => !roleId || job.canonical_role_id === roleId)
    .flatMap(job => job.levels || []));
  return JOB_LEVELS.filter(level => available.has(level));
}

export function matchesFramework(record: CandidateChoice | JobChoice, framework: FrameworkChoice | null): boolean {
  if (!framework) return false;
  if ("resolved_framework_id" in record && record.resolved_framework_id !== undefined) {
    return Boolean(record.resolved_framework_id) && record.resolved_framework_id === framework.framework_id;
  }
  if (record.canonical_role_id && framework.canonical_role_id) {
    return record.canonical_role_id === framework.canonical_role_id;
  }
  return record.framework_id === framework.framework_id;
}

export function resolveInterviewFramework<T extends FrameworkChoice>(
  frameworks: T[], candidate: CandidateChoice | null, job: JobChoice | null, useUploadedCv = false,
  jobRoleFilter = "", matchingJobs: JobChoice[] = [],
): T | null {
  // A selected JD always wins. Before one is selected, an explicit specialty
  // filter is authoritative too: never preview a framework from an unrelated CV.
  if (!job && jobRoleFilter) {
    if (!matchingJobs.length || matchingJobs.some(item => !item.resolved_framework_id)) return null;
    const ids = Array.from(new Set(matchingJobs.map(item => item.resolved_framework_id)));
    if (ids.length !== 1) return null;
    return frameworks.find(item => item.framework_id === ids[0]) || null;
  }
  const source = job || (useUploadedCv ? null : candidate);
  if (!source) return null;
  if ("resolved_framework_id" in source && source.resolved_framework_id !== undefined) {
    return source.resolved_framework_id
      ? frameworks.find(item => item.framework_id === source.resolved_framework_id && matchesFramework(source, item)) || null
      : null;
  }
  // Compatibility with older options payloads; no first-framework default.
  return frameworks.find(item => item.framework_id === source.framework_id && matchesFramework(source, item))
    || frameworks.find(item => source.canonical_role_id && item.canonical_role_id === source.canonical_role_id)
    || null;
}

export function buildInterviewRequest(input: {
  studentId: string;
  framework: FrameworkChoice | null;
  candidate: CandidateChoice | null;
  job: JobChoice | null;
  useUploadedCv: boolean;
  hasProfile: boolean;
  allowCrossRoleCv: boolean;
  customCompany: string;
  jobRoleFilter?: string;
  jobLevelFilter?: string;
}) {
  const { studentId, framework, candidate, job, useUploadedCv, hasProfile, allowCrossRoleCv, customCompany, jobRoleFilter = "", jobLevelFilter = "" } = input;
  if (!studentId) throw new Error("Đăng nhập MSSV trước khi bắt đầu.");
  if (!framework) throw new Error("CV/JD đã chọn chưa xác định được khung phỏng vấn.");
  if (!job || !matchesFramework(job, framework)) throw new Error("Chọn JD phù hợp với chuyên môn đang luyện.");
  if (!filterJobs([job], jobRoleFilter, jobLevelFilter).length) throw new Error("JD không còn khớp bộ lọc chuyên môn/cấp độ; chọn lại JD.");
  if (useUploadedCv ? !hasProfile : !candidate) throw new Error("Chọn một CV trong danh sách hoặc tải CV của bạn lên.");
  const crossRole = !useUploadedCv && candidate !== null && !matchesFramework(candidate, framework);
  if (crossRole && !allowCrossRoleCv) throw new Error("Xác nhận dùng CV khác chuyên môn trước khi bắt đầu.");
  const company = customCompany.trim() || job.company;
  if (!company) throw new Error("Nhập tên công ty mục tiêu.");
  return {
    student_id: studentId,
    framework_id: framework.framework_id,
    candidate_id: useUploadedCv ? undefined : candidate?.candidate_id,
    job_id: job.job_id,
    target_company: company,
    target_role: job.title || framework.role_title,
    allow_cross_role_cv: crossRole && allowCrossRoleCv,
    job_role_filter: jobRoleFilter || undefined,
    job_level_filter: jobLevelFilter || undefined,
  };
}
