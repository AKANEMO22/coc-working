/**
 * CÓC ĐI LÀM — VAD Worker (§4, §9)
 * Silero VAD ONNX via onnxruntime-web
 * Phát hiện speech start/end, barge-in trigger.
 * Chạy trong Web Worker — không block UI thread.
 */

/// <reference lib="webworker" />

let vadModel: any = null;
let isInitialized = false;

const SPEECH_THRESHOLD = 0.5;
const SILENCE_THRESHOLD = 0.35;
const MIN_SPEECH_DURATION_MS = 250;
const MIN_SILENCE_DURATION_MS = 700;

let speechStartTime = 0;
let silenceStartTime = 0;
let isSpeechActive = false;
let sampleRate = 16000;

// Internal state for Silero VAD ONNX
let h_state: Float32Array | null = null;
let c_state: Float32Array | null = null;

self.onmessage = async (event: MessageEvent) => {
  const { type, payload } = event.data;

  switch (type) {
    case "init":
      await initVAD(payload?.modelUrl);
      break;

    case "process":
      if (isInitialized && payload?.audioData) {
        processAudioChunk(payload.audioData);
      }
      break;

    case "reset":
      resetState();
      break;

    case "destroy":
      vadModel = null;
      isInitialized = false;
      break;
  }
};

async function initVAD(modelUrl?: string) {
  try {
    const ort = await import("onnxruntime-web");

    // Cấu hình ONNX Runtime WASM
    ort.env.wasm.wasmPaths = "/wasm/";

    const url = modelUrl || "/models/silero_vad.onnx";

    // Thử tải từ IndexedDB cache trước
    let modelData: ArrayBuffer | null = await loadFromCache("silero_vad");

    if (!modelData) {
      // Tải từ URL
      self.postMessage({ type: "status", payload: { stage: "downloading", progress: 0 } });
      const response = await fetch(url);
      modelData = await response.arrayBuffer();

      // Lưu vào cache
      await saveToCache("silero_vad", modelData);
      self.postMessage({ type: "status", payload: { stage: "downloaded", progress: 100 } });
    }

    vadModel = await ort.InferenceSession.create(modelData, {
      executionProviders: ["wasm"],
    });

    // Khởi tạo hidden states
    h_state = new Float32Array(2 * 1 * 64).fill(0);
    c_state = new Float32Array(2 * 1 * 64).fill(0);

    isInitialized = true;
    self.postMessage({ type: "ready" });
  } catch (error) {
    self.postMessage({
      type: "error",
      payload: { message: `VAD init failed: ${error}` },
    });
  }
}

async function processAudioChunk(audioData: Float32Array) {
  if (!vadModel || !h_state || !c_state) return;

  try {
    const ort = await import("onnxruntime-web");

    // Prepare inputs for Silero VAD
    const inputTensor = new ort.Tensor("float32", audioData, [1, audioData.length]);
    const srTensor = new ort.Tensor("int64", BigInt64Array.from([BigInt(sampleRate)]), []);
    const hTensor = new ort.Tensor("float32", h_state, [2, 1, 64]);
    const cTensor = new ort.Tensor("float32", c_state, [2, 1, 64]);

    const feeds = {
      input: inputTensor,
      sr: srTensor,
      h: hTensor,
      c: cTensor,
    };

    const results = await vadModel.run(feeds);

    // Update hidden states
    h_state = results.hn.data as Float32Array;
    c_state = results.cn.data as Float32Array;

    // Get speech probability
    const speechProb = (results.output.data as Float32Array)[0];
    const now = Date.now();

    // Detect speech transitions
    if (speechProb >= SPEECH_THRESHOLD && !isSpeechActive) {
      if (speechStartTime === 0) {
        speechStartTime = now;
      }
      if (now - speechStartTime >= MIN_SPEECH_DURATION_MS) {
        isSpeechActive = true;
        silenceStartTime = 0;
        self.postMessage({
          type: "speech_start",
          payload: { probability: speechProb, timestamp: now },
        });
      }
    } else if (speechProb < SILENCE_THRESHOLD && isSpeechActive) {
      if (silenceStartTime === 0) {
        silenceStartTime = now;
      }
      if (now - silenceStartTime >= MIN_SILENCE_DURATION_MS) {
        isSpeechActive = false;
        speechStartTime = 0;
        self.postMessage({
          type: "speech_end",
          payload: {
            probability: speechProb,
            timestamp: now,
            duration_ms: now - silenceStartTime + MIN_SILENCE_DURATION_MS,
          },
        });
      }
    } else {
      if (speechProb >= SPEECH_THRESHOLD) {
        silenceStartTime = 0;
      } else {
        speechStartTime = 0;
      }
    }

    // Continuous probability updates (throttled)
    self.postMessage({
      type: "vad_score",
      payload: { probability: speechProb, isSpeaking: isSpeechActive },
    });
  } catch (error) {
    self.postMessage({
      type: "error",
      payload: { message: `VAD processing error: ${error}` },
    });
  }
}

function resetState() {
  isSpeechActive = false;
  speechStartTime = 0;
  silenceStartTime = 0;
  if (h_state) h_state.fill(0);
  if (c_state) c_state.fill(0);
}

// IndexedDB helpers for model caching (§22)
async function loadFromCache(modelName: string): Promise<ArrayBuffer | null> {
  return new Promise((resolve) => {
    try {
      const request = indexedDB.open("coc_model_cache", 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains("models")) {
          db.createObjectStore("models");
        }
      };
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction("models", "readonly");
        const store = tx.objectStore("models");
        const get = store.get(modelName);
        get.onsuccess = () => resolve(get.result || null);
        get.onerror = () => resolve(null);
      };
      request.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

async function saveToCache(modelName: string, data: ArrayBuffer): Promise<void> {
  return new Promise((resolve) => {
    try {
      const request = indexedDB.open("coc_model_cache", 1);
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction("models", "readwrite");
        const store = tx.objectStore("models");
        store.put(data, modelName);
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve();
      };
      request.onerror = () => resolve();
    } catch {
      resolve();
    }
  });
}

export {};
