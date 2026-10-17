/**
 * Local Silero VAD 6.2.3 inference worker.
 * Model input contract: 512 mono samples at 16 kHz plus 64 samples of context.
 */
/// <reference lib="webworker" />

import { SileroVadEndpoint } from "../lib/sileroVadEndpoint";
import type { InferenceSession } from "onnxruntime-web";

const SAMPLE_RATE = 16000;
const FRAME_SAMPLES = 512;
const CONTEXT_SAMPLES = 64;
const STATE_KEY = "silero-vad-6.2.3";

let ort: typeof import("onnxruntime-web/wasm") | null = null;
let session: InferenceSession | null = null;
const hiddenState = new Float32Array(2 * 1 * 128);
const context = new Float32Array(CONTEXT_SAMPLES);
let pendingSamples: Float32Array<ArrayBufferLike> = new Float32Array(0);
let initialized = false;
let workQueue = Promise.resolve();
const endpoint = new SileroVadEndpoint({
  speechThreshold: 0.5,
  silenceThreshold: 0.35,
  minSpeechDurationMs: 250,
  endSilenceDurationMs: 1200,
});

self.onmessage = (event: MessageEvent) => {
  const { type, payload } = event.data ?? {};
  if (type === "init") {
    enqueue(() => initialize(payload?.modelUrl));
  } else if (type === "process" && payload?.audioData) {
    const audioData = payload.audioData as Float32Array;
    const sampleRate = Number(payload.sampleRate);
    enqueue(() => processAudioChunk(audioData, sampleRate));
  } else if (type === "reset") {
    enqueue(() => resetState());
  } else if (type === "destroy") {
    enqueue(async () => {
      initialized = false;
      if (session) await session.release();
      session = null;
      ort = null;
      resetState();
    });
  }
};

function enqueue(operation: () => Promise<void> | void): void {
  workQueue = workQueue
    .then(operation)
    .catch((error: unknown) => {
      const message = error instanceof Error ? error.message : String(error);
      self.postMessage({ type: "error", payload: { message, fatal: !initialized } });
    });
}

async function initialize(modelUrl?: string): Promise<void> {
  try {
    ort = await import("onnxruntime-web/wasm");
    // A single WASM worker avoids cross-origin isolation/threading requirements.
    ort.env.wasm.numThreads = 1;
    ort.env.wasm.proxy = false;
    // Next's module-worker bundle cannot infer the original WASM package URL.
    // Serve the matching ONNX Runtime binary from the app's public directory.
    ort.env.wasm.wasmPaths = "/models/ort/";

    const url = modelUrl || "/models/silero_vad.onnx";
    self.postMessage({ type: "status", payload: { stage: "downloading", model: STATE_KEY } });
    const response = await fetch(url, { cache: "force-cache" });
    if (!response.ok) throw new Error("Không tải được Silero VAD (" + response.status + ").");
    const modelData = await response.arrayBuffer();

    session = await ort.InferenceSession.create(modelData, {
      executionProviders: ["wasm"],
      graphOptimizationLevel: "all",
    });

    const requiredInputs = ["input", "state", "sr"];
    if (!requiredInputs.every((name) => session?.inputNames.includes(name))) {
      throw new Error("Silero VAD có input không mong đợi: " + session.inputNames.join(", "));
    }
    if (!session.outputNames.includes("output") || !session.outputNames.includes("stateN")) {
      throw new Error("Silero VAD có output không mong đợi: " + session.outputNames.join(", "));
    }

    resetState();
    initialized = true;
    self.postMessage({ type: "ready", payload: { model: STATE_KEY, sampleRate: SAMPLE_RATE } });
  } catch (error) {
    initialized = false;
    session = null;
    throw error;
  }
}

async function processAudioChunk(audioData: Float32Array, sampleRate: number): Promise<void> {
  if (!initialized || !ort || !session || audioData.length === 0) return;
  if (sampleRate !== SAMPLE_RATE) {
    throw new Error("Silero VAD cần PCM " + SAMPLE_RATE + " Hz; nhận được " + sampleRate + " Hz.");
  }

  pendingSamples = append(pendingSamples, audioData);
  while (pendingSamples.length >= FRAME_SAMPLES) {
    const frame = pendingSamples.slice(0, FRAME_SAMPLES);
    pendingSamples = pendingSamples.slice(FRAME_SAMPLES);

    const input = new Float32Array(CONTEXT_SAMPLES + FRAME_SAMPLES);
    input.set(context, 0);
    input.set(frame, CONTEXT_SAMPLES);

    const result = await session.run({
      input: new ort.Tensor("float32", input, [1, input.length]),
      state: new ort.Tensor("float32", hiddenState, [2, 1, 128]),
      sr: new ort.Tensor("int64", BigInt64Array.from([BigInt(SAMPLE_RATE)]), [1]),
    });

    const probability = (result.output.data as Float32Array)[0] ?? 0;
    hiddenState.set(result.stateN.data as Float32Array);
    context.set(input.subarray(input.length - CONTEXT_SAMPLES));

    const decision = endpoint.process(probability, (FRAME_SAMPLES / SAMPLE_RATE) * 1000);
    if (decision.speechStarted) {
      self.postMessage({ type: "speech_start", payload: { probability } });
    }
    if (decision.speechEnded) {
      self.postMessage({
        type: "speech_end",
        payload: { probability, silence_ms: decision.silenceMs },
      });
    }
  }
}

function append(left: Float32Array, right: Float32Array): Float32Array {
  const joined = new Float32Array(left.length + right.length);
  joined.set(left, 0);
  joined.set(right, left.length);
  return joined;
}

function resetState(): void {
  hiddenState.fill(0);
  context.fill(0);
  pendingSamples = new Float32Array(0);
  endpoint.reset();
}

export {};
