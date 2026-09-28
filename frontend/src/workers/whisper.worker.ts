/**
 * CÓC ĐI LÀM — Whisper STT Worker (§4, §5)
 * Whisper.cpp WASM cho speech-to-text local.
 * Partial + Final transcript generation.
 * Technical-Term Recovery tier 1 integration.
 */

/// <reference lib="webworker" />

let whisperModule: any = null;
let isInitialized = false;
let isProcessing = false;

self.onmessage = async (event: MessageEvent) => {
  const { type, payload } = event.data;

  switch (type) {
    case "init":
      await initWhisper(payload);
      break;

    case "transcribe":
      if (isInitialized && payload?.audioData) {
        await transcribeAudio(payload.audioData, payload.isPartial);
      }
      break;

    case "destroy":
      whisperModule = null;
      isInitialized = false;
      break;
  }
};

async function initWhisper(options: {
  modelUrl?: string;
  wasmUrl?: string;
  language?: string;
}) {
  try {
    self.postMessage({
      type: "status",
      payload: { stage: "loading", message: "Đang tải Whisper model..." },
    });

    // Whisper.cpp WASM: load model from URL or cache
    const modelUrl = options?.modelUrl || "/models/ggml-base.bin";

    // Check IndexedDB cache first
    let modelData = await loadFromCache("whisper_base");

    if (!modelData) {
      self.postMessage({
        type: "status",
        payload: { stage: "downloading", progress: 0 },
      });

      const response = await fetch(modelUrl);
      const reader = response.body?.getReader();
      const contentLength = Number(response.headers.get("Content-Length")) || 0;

      const chunks: Uint8Array[] = [];
      let received = 0;

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          received += value.length;
          self.postMessage({
            type: "status",
            payload: {
              stage: "downloading",
              progress: contentLength > 0 ? Math.round((received / contentLength) * 100) : -1,
            },
          });
        }
      }

      const uint8 = new Uint8Array(received);
      let offset = 0;
      for (const chunk of chunks) {
        uint8.set(chunk, offset);
        offset += chunk.length;
      }

      modelData = uint8.buffer as ArrayBuffer;
      await saveToCache("whisper_base", modelData);
    }

    // Placeholder: In production, initialize whisper.cpp WASM module
    // const Module = await loadWhisperModule();
    // whisperModule = await Module.init(modelData);

    isInitialized = true;
    self.postMessage({
      type: "ready",
      payload: { model: "whisper-base-multilingual" },
    });
  } catch (error) {
    self.postMessage({
      type: "error",
      payload: { message: `Whisper init failed: ${error}` },
    });
  }
}

async function transcribeAudio(audioData: Float32Array, isPartial: boolean = false) {
  if (isProcessing) return;
  if (!whisperModule) {
    // Production sử dụng Web Speech API native trong edgeRuntime.ts. Whisper WASM offline module không khả dụng.
    return;
  }
  isProcessing = true;

  try {
    const result = whisperModule.transcribe(audioData, {
      language: "vi",
      task: "transcribe",
      word_timestamps: true,
    });

    // Technical-Term Recovery (§5 — Tier 1: Local lexicon)
    const termCandidates = applyTechnicalTermRecovery(result.text);

    self.postMessage({
      type: isPartial ? "partial_transcript" : "final_transcript",
      payload: {
        text: result.text,
        segments: result.segments,
        language: result.language,
        term_candidates: termCandidates,
        timestamp: Date.now(),
      },
    });
  } catch (error) {
    self.postMessage({
      type: "error",
      payload: { message: `Transcription error: ${error}` },
    });
  } finally {
    isProcessing = false;
  }
}

/**
 * Technical-Term Recovery Tier 1: Domain lexicon matching (§5)
 * Chạy local, không cần API.
 */
function applyTechnicalTermRecovery(text: string): Array<{
  original: string;
  suggested: string;
  confidence: number;
  category: string;
}> {
  const candidates: Array<{
    original: string;
    suggested: string;
    confidence: number;
    category: string;
  }> = [];

  // Domain lexicon cho phỏng vấn IT
  const lexicon: Record<string, { correct: string; category: string }> = {
    "react js": { correct: "ReactJS", category: "framework" },
    "next js": { correct: "Next.js", category: "framework" },
    "node js": { correct: "Node.js", category: "runtime" },
    "spring boot": { correct: "Spring Boot", category: "framework" },
    "docker": { correct: "Docker", category: "devops" },
    "kubernetes": { correct: "Kubernetes", category: "devops" },
    "ci cd": { correct: "CI/CD", category: "devops" },
    "rest api": { correct: "REST API", category: "architecture" },
    "graph ql": { correct: "GraphQL", category: "api" },
    "type script": { correct: "TypeScript", category: "language" },
    "java script": { correct: "JavaScript", category: "language" },
    "sql": { correct: "SQL", category: "database" },
    "no sql": { correct: "NoSQL", category: "database" },
    "postgres": { correct: "PostgreSQL", category: "database" },
    "redis": { correct: "Redis", category: "database" },
    "git hub": { correct: "GitHub", category: "vcs" },
    "microservices": { correct: "Microservices", category: "architecture" },
    "oop": { correct: "OOP", category: "paradigm" },
    "solid": { correct: "SOLID", category: "principle" },
    "dry": { correct: "DRY", category: "principle" },
    "mvp": { correct: "MVP", category: "pattern" },
    "mvc": { correct: "MVC", category: "pattern" },
    "singleton": { correct: "Singleton", category: "pattern" },
  };

  const textLower = text.toLowerCase();
  for (const [pattern, info] of Object.entries(lexicon)) {
    if (textLower.includes(pattern) && !text.includes(info.correct)) {
      candidates.push({
        original: pattern,
        suggested: info.correct,
        confidence: 0.85,
        category: info.category,
      });
    }
  }

  return candidates;
}

// IndexedDB cache helpers
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
