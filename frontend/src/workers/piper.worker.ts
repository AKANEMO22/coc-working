/**
 * CÓC ĐI LÀM — Piper TTS Worker (§4)
 * Piper TTS WASM vi_VN voice synthesis.
 * Text-to-speech local, hỗ trợ barge-in interruption.
 */

/// <reference lib="webworker" />

let piperModule: any = null;
let isInitialized = false;
let isSpeaking = false;
let abortController: AbortController | null = null;

self.onmessage = async (event: MessageEvent) => {
  const { type, payload } = event.data;

  switch (type) {
    case "init":
      await initPiper(payload);
      break;

    case "speak":
      if (isInitialized && payload?.text) {
        await synthesize(payload.text, payload.speed);
      }
      break;

    case "stop":
      stopSpeaking();
      break;

    case "destroy":
      stopSpeaking();
      piperModule = null;
      isInitialized = false;
      break;
  }
};

async function initPiper(options?: {
  modelUrl?: string;
  configUrl?: string;
}) {
  try {
    self.postMessage({
      type: "status",
      payload: { stage: "loading", message: "Đang tải Piper TTS model..." },
    });

    const modelUrl = options?.modelUrl || "/models/vi_VN-vais1000-medium.onnx";
    const configUrl = options?.configUrl || "/models/vi_VN-vais1000-medium.onnx.json";

    // Check cache
    let modelData = await loadFromCache("piper_vi");

    if (!modelData) {
      self.postMessage({
        type: "status",
        payload: { stage: "downloading", progress: 0 },
      });

      const response = await fetch(modelUrl);
      modelData = await response.arrayBuffer();

      await saveToCache("piper_vi", modelData);
      self.postMessage({
        type: "status",
        payload: { stage: "downloaded", progress: 100 },
      });
    }

    // Placeholder: Initialize Piper WASM module
    // piperModule = await PiperWasm.init(modelData, configData);

    isInitialized = true;
    self.postMessage({
      type: "ready",
      payload: { voice: "vi_VN-vais1000-medium" },
    });
  } catch (error) {
    self.postMessage({
      type: "error",
      payload: { message: `Piper TTS init failed: ${error}` },
    });
  }
}

async function synthesize(text: string, speed: number = 1.0) {
  if (isSpeaking) {
    stopSpeaking();
  }

  if (!piperModule) {
    // Production sử dụng Microsoft Neural TTS (/api/v1/tts/synthesize). Piper WASM offline module không khả dụng.
    self.postMessage({
      type: "error",
      payload: { message: "Piper WASM module not loaded. Using Microsoft Neural TTS fallback." },
    });
    return;
  }

  isSpeaking = true;
  abortController = new AbortController();

  try {
    self.postMessage({
      type: "tts_start",
      payload: { text, timestamp: Date.now() },
    });

    const audioBuffer = piperModule.synthesize(text, {
      speed,
      sampleRate: 22050,
    });

    isSpeaking = false;
    self.postMessage({
      type: "tts_end",
      payload: { timestamp: Date.now(), audioBuffer },
    });
  } catch (error: any) {
    isSpeaking = false;
    if (error?.message === "Aborted") {
      self.postMessage({
        type: "tts_interrupted",
        payload: { reason: "barge_in", timestamp: Date.now() },
      });
    } else {
      self.postMessage({
        type: "error",
        payload: { message: `TTS synthesis error: ${error}` },
      });
    }
  }
}

function stopSpeaking() {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
  isSpeaking = false;
}

// IndexedDB cache
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
