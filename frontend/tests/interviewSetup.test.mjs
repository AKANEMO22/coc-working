import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/interviewSetup.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { buildInterviewRequest, matchesFramework, resolveInterviewFramework, filterJobs, jobsWithFramework, getJobRoleOptions, getJobLevelOptions, jobsMatchingCandidate, jobsMatchingCv } = await import("data:text/javascript;base64," + Buffer.from(compiled).toString("base64"));

const framework = { framework_id: "IF_FE", canonical_role_id: "ROLE_FE", role_title: "Frontend" };
const candidate = { candidate_id: "CV_SECOND", canonical_role_id: "ROLE_FE", framework_id: "IF_FE" };
const job = { job_id: "JOB_SECOND", canonical_role_id: "ROLE_FE", framework_id: "IF_FE", title: "Frontend Intern", company: "Selected Company" };
const selected = { studentId: "LOCAL_TEST", framework, candidate, job, useUploadedCv: false, hasProfile: false, allowCrossRoleCv: false, customCompany: "" };

test("normal/demo payload carries exact independently selected IDs", () => {
  for (const studentId of ["LOCAL_TEST", "DEMO_IF_FE"]) {
    const request = buildInterviewRequest({ ...selected, studentId });
    assert.equal(request.candidate_id, "CV_SECOND");
    assert.equal(request.job_id, "JOB_SECOND");
    assert.equal(request.framework_id, "IF_FE");
    assert.equal(request.target_company, "Selected Company");
    assert.equal(request.target_role, "Frontend Intern");
  }
});

test("missing CV/JD never silently chooses the first/default pair", () => {
  assert.throws(() => buildInterviewRequest({ ...selected, candidate: null }));
  assert.throws(() => buildInterviewRequest({ ...selected, job: null }));
});

test("old JD is rejected when switching specialty", () => {
  const changed = { framework_id: "IF_AI", canonical_role_id: "ROLE_AI", role_title: "AI" };
  assert.equal(matchesFramework(job, changed), false);
  assert.throws(() => buildInterviewRequest({ ...selected, framework: changed, allowCrossRoleCv: true }));
});

test("cross-role CV requires explicit approval and preserves source ID", () => {
  const cv = { ...candidate, canonical_role_id: "ROLE_OTHER" };
  assert.throws(() => buildInterviewRequest({ ...selected, candidate: cv }));
  const approved = buildInterviewRequest({ ...selected, candidate: cv, allowCrossRoleCv: true });
  assert.equal(approved.allow_cross_role_cv, true);
  assert.equal(approved.candidate_id, "CV_SECOND");
});

test("uploaded CV omits sample candidate ID without changing selected JD", () => {
  const request = buildInterviewRequest({ ...selected, useUploadedCv: true, hasProfile: true });
  assert.equal(request.candidate_id, undefined);
  assert.equal(request.job_id, "JOB_SECOND");
  assert.throws(() => buildInterviewRequest({ ...selected, useUploadedCv: true, hasProfile: false }));
});

test("explicit company override is honored", () => {
  assert.equal(buildInterviewRequest({ ...selected, customCompany: "  Other Company  " }).target_company, "Other Company");
});

const ai = { framework_id: "IF_AI", canonical_role_id: "ROLE_AI", role_title: "AI" };
const frameworks = [ai, framework]; // Deliberately put a wrong default first.
const aiJob = { ...job, job_id: "JD_AI", canonical_role_id: "ROLE_AI", framework_id: "IF_AI", resolved_framework_id: "IF_AI", title: "AI Intern" };

test("no selection has no default framework", () => {
  assert.equal(resolveInterviewFramework(frameworks, null, null), null);
});

test("CV gives provisional framework, then JD takes priority", () => {
  assert.equal(resolveInterviewFramework(frameworks, candidate, null).framework_id, "IF_FE");
  assert.equal(resolveInterviewFramework(frameworks, candidate, aiJob).framework_id, "IF_AI");
});

test("specialty filter controls framework preview and never falls back to a mismatched CV", () => {
  assert.equal(resolveInterviewFramework(frameworks, candidate, null, false, "ROLE_AI", [aiJob]).framework_id, "IF_AI");
  assert.equal(resolveInterviewFramework(frameworks, candidate, null, false, "ROLE_MISSING", []), null);
});

test("explicit resolved framework ID beats a broad canonical role mismatch", () => {
  const fullstack = { framework_id: "IF_FULLSTACK", canonical_role_id: "ROLE_SOFTWARE_ENGINEER", role_title: "FullStack" };
  const fullstackJob = { ...job, canonical_role_id: "ROLE_FULLSTACK", resolved_framework_id: "IF_FULLSTACK" };
  assert.equal(matchesFramework(fullstackJob, fullstack), true);
  assert.equal(resolveInterviewFramework([fullstack], candidate, fullstackJob).framework_id, "IF_FULLSTACK");
});

test("changing JD updates framework without replacing the selected CV", () => {
  const resolved = resolveInterviewFramework(frameworks, candidate, aiJob);
  const request = buildInterviewRequest({ ...selected, framework: resolved, job: aiJob, allowCrossRoleCv: true });
  assert.equal(request.framework_id, "IF_AI");
  assert.equal(request.candidate_id, "CV_SECOND");
  assert.equal(request.job_id, "JD_AI");
  assert.equal(resolveInterviewFramework(frameworks, candidate, job).framework_id, "IF_FE");
});

test("legacy source framework ID resolves by canonical identity", () => {
  const legacy = { ...job, framework_id: "OLD_FE_ID" };
  assert.equal(resolveInterviewFramework(frameworks, candidate, legacy).framework_id, "IF_FE");
});

test("unmapped JD does not fall back to CV or first framework", () => {
  assert.equal(resolveInterviewFramework(frameworks, candidate, { ...aiJob, resolved_framework_id: null }), null);
  assert.equal(resolveInterviewFramework(frameworks, candidate, { ...aiJob, resolved_framework_id: "MISSING" }), null);
});

test("uploaded CV relies on JD rather than an old sample selection", () => {
  assert.equal(resolveInterviewFramework(frameworks, candidate, null, true), null);
  assert.equal(resolveInterviewFramework(frameworks, candidate, aiJob, true).framework_id, "IF_AI");
});

const internAiJob = { ...aiJob, levels: ["Intern", "Fresher"] };
const juniorAiJob = { ...aiJob, job_id: "JD_AI_JUNIOR", levels: ["Junior"] };
const internFrontendJob = { ...job, levels: ["Intern"] };
const filteredSample = [internAiJob, juniorAiJob, internFrontendJob, { ...aiJob, job_id: "LEVEL_UNKNOWN", levels: [] }];

test("AI + Intern excludes frontend, AI Junior and unknown level", () => {
  assert.deepEqual(filterJobs(filteredSample, "ROLE_AI", "Intern").map(job => job.job_id), ["JD_AI"]);
});

test("CV role and level alone filter JD shortlist; no fallback to a wrong job", () => {
  const cv = { ...candidate, resolved_framework_id: "IF_FE", experience_level: "Intern" };
  const offered = [
    { ...internFrontendJob, resolved_framework_id: "IF_FE" },
    { ...internAiJob, resolved_framework_id: "IF_AI" },
    { ...internFrontendJob, job_id: "FE_JUNIOR", resolved_framework_id: "IF_FE", levels: ["Junior"] },
  ];
  assert.deepEqual(jobsMatchingCandidate(offered, cv).map(item => item.job_id), [internFrontendJob.job_id]);
  assert.deepEqual(jobsMatchingCandidate(offered, { ...cv, experience_level: "Senior" }), []);
  assert.deepEqual(jobsMatchingCandidate(offered, { ...cv, experience_level: "" }), []);
  assert.deepEqual(jobsMatchingCandidate(offered, { ...cv, resolved_framework_id: null }), []);
});

test("setup no longer asks for redundant specialty or hiring-level selectors", () => {
  const page = readFileSync(new URL("../src/app/interview/page.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(page, /id="job-role-filter"|id="job-level-filter"/);
  assert.match(page, /jobsMatchingCandidate\(selectableJobs, candidate\)/);
  assert.match(page, /selectableCandidates = candidates\.filter\(item => jobsMatchingCandidate\(selectableJobs, item\)\.length > 0\)/);
  assert.match(page, /jobsMatchingCv\(selectableJobs, uploadedCvMatch\?\.resolved_framework_id, uploadedCvMatch\?\.experience_level\)/);
});

test("uploaded CV metadata filters JD choices without a second role/level selection", () => {
  const offered = [
    { ...internFrontendJob, resolved_framework_id: "IF_FE" },
    { ...internAiJob, resolved_framework_id: "IF_AI" },
  ];
  assert.deepEqual(jobsMatchingCv(offered, "IF_FE", "Intern").map(item => item.job_id), [internFrontendJob.job_id]);
  assert.deepEqual(jobsMatchingCv(offered, null, "Intern"), []);
  assert.deepEqual(jobsMatchingCv(offered, "IF_FE", null), []);
});

test("filters combine with AND and no-results is empty, never all jobs", () => {
  assert.equal(filterJobs(filteredSample, "ROLE_MISSING", "Intern").length, 0);
  assert.equal(filterJobs(filteredSample, "ROLE_AI", "Senior").length, 0);
  assert.equal(filterJobs(filteredSample, "", "Intern").length, 2);
});

test("filter controls only offer specialties and levels backed by matching jobs", () => {
  assert.deepEqual(getJobRoleOptions(filteredSample, "Intern").map(([id]) => id).sort(), ["ROLE_AI", "ROLE_FE"]);
  assert.deepEqual(getJobRoleOptions(filteredSample, "Senior"), []);
  assert.deepEqual(getJobLevelOptions(filteredSample, "ROLE_AI"), ["Intern", "Fresher", "Junior"]);
  assert.deepEqual(getJobLevelOptions(filteredSample, "ROLE_MISSING"), []);
});

test("JD with no resolved interview framework is not offered for selection", () => {
  const options = jobsWithFramework([
    { ...internAiJob, resolved_framework_id: "IF_AI" },
    { ...internFrontendJob, job_id: "UNMAPPED", resolved_framework_id: null },
  ]);
  assert.deepEqual(options.map(item => item.job_id), ["JD_AI"]);
});

test("selected job must still satisfy level/role before request is sent", () => {
  assert.throws(() => buildInterviewRequest({ ...selected, jobRoleFilter: "ROLE_AI", jobLevelFilter: "Intern" }));
  const request = buildInterviewRequest({ ...selected, framework: ai, job: internAiJob, allowCrossRoleCv: true, jobRoleFilter: "ROLE_AI", jobLevelFilter: "Intern" });
  assert.equal(request.job_role_filter, "ROLE_AI");
  assert.equal(request.job_level_filter, "Intern");
  assert.equal(request.framework_id, "IF_AI");
});

test("local STT WAV encoder resamples mono float and writes little-endian PCM16", async () => {
  const audioSource = readFileSync(new URL("../src/lib/audioPcm.ts", import.meta.url), "utf8");
  const audioCompiled = ts.transpileModule(audioSource, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
  const { encodeMonoWav, resampleMonoFloat } = await import("data:text/javascript;base64," + Buffer.from(audioCompiled).toString("base64"));
  const wav = new DataView(await encodeMonoWav(Float32Array.from([-1, -0.5, 0, 0.5, 1])).arrayBuffer());
  assert.equal(String.fromCharCode(...new Uint8Array(wav.buffer.slice(0, 4))), "RIFF");
  assert.deepEqual(Array.from({ length: 5 }, (_, index) => wav.getInt16(44 + index * 2, true)), [-32768, -16384, 0, 16383, 32767]);
  assert.equal(resampleMonoFloat(new Float32Array(4800), 48000).length, 1600);
});

test("interview voice runtime uses Qwen and no external speech APIs", () => {
  const runtime = readFileSync(new URL("../src/lib/edgeRuntime.ts", import.meta.url), "utf8");
  assert.match(runtime, /api\/v1\/stt\/transcribe/);
  assert.match(runtime, /api\/v1\/tts\/synthesize-aligned/);
  assert.doesNotMatch(runtime, /Scribe|ElevenLabs|SpeechRecognition|webkitSpeechRecognition|speechSynthesis|SpeechSynthesisUtterance/);
});

test("voice runtime sends bounded partial audio after speech starts and keeps final transcription", () => {
  const runtime = readFileSync(new URL("../src/lib/edgeRuntime.ts", import.meta.url), "utf8");
  const page = readFileSync(new URL("../src/app/interview/[sessionId]/page.tsx", import.meta.url), "utf8");
  assert.match(runtime, /PARTIAL_WINDOW_SAMPLES = Math\.round\(STT_SAMPLE_RATE \* 4\.5\)/);
  assert.match(runtime, /this\.speechStartSampleIndex === null/);
  assert.match(runtime, /transcribe\(recentAudio, controller\.signal, "partial"\)/);
  assert.match(runtime, /transcribe\(samples, controller\.signal, "final"\)/);
  assert.match(page, /edgeRuntimeRef\.current\?\.markSpeechStarted\(\)/);
  assert.match(page, /submitTextRef\.current\(text, false, evidence\)/);
  assert.match(page, /onSubmitText=\{\(text\) => handleSubmitText\(text, true\)\}/);
});
