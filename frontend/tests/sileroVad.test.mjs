import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/sileroVadEndpoint.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { SileroVadEndpoint } = await import(
  "data:text/javascript;base64," + Buffer.from(compiled).toString("base64")
);
const energySource = readFileSync(new URL("../src/lib/energyVadEndpoint.ts", import.meta.url), "utf8");
const energyCompiled = ts.transpileModule(energySource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { EnergyVadEndpoint } = await import(
  "data:text/javascript;base64," + Buffer.from(energyCompiled).toString("base64")
);

const runtime = readFileSync(new URL("../src/lib/edgeRuntime.ts", import.meta.url), "utf8");
const recorder = readFileSync(new URL("../src/hooks/useAudioRecorder.ts", import.meta.url), "utf8");
const worker = readFileSync(new URL("../src/workers/vad.worker.ts", import.meta.url), "utf8");
const controls = readFileSync(new URL("../src/components/interview/ControlBar.tsx", import.meta.url), "utf8");
const page = readFileSync(new URL("../src/app/interview/[sessionId]/page.tsx", import.meta.url), "utf8");

test("Silero probability gate ignores short noise before accepting speech", () => {
  const endpoint = new SileroVadEndpoint();
  for (let i = 0; i < 7; i += 1) {
    assert.equal(endpoint.process(0.9).speechStarted, false);
  }
  assert.equal(endpoint.process(0.9).speechStarted, true);
});

test("Silero ends only after sustained silence, and renewed speech resets the timer", () => {
  const endpoint = new SileroVadEndpoint();
  for (let i = 0; i < 8; i += 1) endpoint.process(0.9);
  for (let i = 0; i < 20; i += 1) assert.equal(endpoint.process(0.1).speechEnded, false);
  assert.equal(endpoint.process(0.6).speechEnded, false);
  for (let i = 0; i < 37; i += 1) assert.equal(endpoint.process(0.1).speechEnded, false);
  assert.equal(endpoint.process(0.1).speechEnded, true);
});

test("local energy fallback automatically starts and ends a spoken turn", () => {
  const vad = new EnergyVadEndpoint();
  const voice = new Float32Array(4096).fill(0.09);
  const silence = new Float32Array(4096);
  assert.equal(vad.process(silence, 16000).speechStarted, false);
  assert.equal(vad.process(voice, 16000).speechStarted, true);
  for (let index = 0; index < 4; index++) assert.equal(vad.process(silence, 16000).speechEnded, false);
  assert.equal(vad.process(silence, 16000).speechEnded, true);
});

test("energy fallback waits through a short pause", () => {
  const vad = new EnergyVadEndpoint();
  const voice = new Float32Array(4096).fill(0.08);
  const silence = new Float32Array(4096);
  vad.process(voice, 16000);
  for (let index = 0; index < 3; index++) vad.process(silence, 16000);
  assert.equal(vad.process(voice, 16000).speechEnded, false);
  for (let index = 0; index < 4; index++) assert.equal(vad.process(silence, 16000).speechEnded, false);
});

test("the interview uses local Silero ONNX VAD and sends WAV to local Qwen3-ASR", () => {
  assert.match(worker, /silero-vad-6\.2\.3/);
  assert.match(worker, /FRAME_SAMPLES = 512/);
  assert.match(worker, /CONTEXT_SAMPLES = 64/);
  assert.match(worker, /\[2, 1, 128\]/);
  assert.match(recorder, /new Worker\(new URL\("\.\.\/workers\/vad\.worker\.ts"/);
  assert.match(runtime, /api\/v1\/stt\/transcribe/);
  assert.match(runtime, /encodeMonoWav/);
  assert.doesNotMatch(runtime, /Scribe\.connect|SpeechRecognition|webkitSpeechRecognition/);
});

test("interview auto-endpoint does not require a manual finish button", () => {
  assert.doesNotMatch(controls, /onFinalizeAnswer|Chốt câu trả lời/);
  assert.doesNotMatch(controls, /onToggleMic/);
});

test("late Laya WAIT cannot cancel a VAD endpoint already in progress", () => {
  assert.match(page, /if \(speechEndTimerRef\.current\) return;/);
  assert.doesNotMatch(page, /bấm Chốt câu trả lời/);
});

test("empty Qwen final is sent to orchestrator for an automatic spoken repeat", () => {
  assert.match(runtime, /onUnclearAudio\?\./);
  assert.match(page, /sendFinalTranscript\("", \[\], `unclear_\$\{Date\.now\(\)\}`, false, evidence\)/);
});
