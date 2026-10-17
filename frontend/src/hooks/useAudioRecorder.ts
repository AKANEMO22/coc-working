"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { resampleMonoFloat } from "@/lib/audioPcm";
import { EnergyVadEndpoint } from "@/lib/energyVadEndpoint";

export interface AudioFeatures {
  durationSec: number;
  audioQualityOk: boolean;
  rmsLevel: number;
  pauseCount: number;
  speakingTimeSec: number;
}

interface UseAudioRecorderOptions {
  onFeaturesExtracted?: (features: AudioFeatures) => void;
  onAudioChunk?: (samples: Float32Array, sampleRate: number) => void;
  onSpeechStart?: () => void;
  onSpeechEnd?: () => void;
  onVadReady?: () => void;
  onVadError?: (message: string) => void;
  onVadModeChange?: (mode: "silero" | "energy") => void;
}

export function useAudioRecorder(options?: UseAudioRecorderOptions) {
  const forceEnergyVad = () => typeof window !== "undefined" &&
    process.env.NODE_ENV === "development" &&
    new URLSearchParams(window.location.search).get("forceEnergyVad") === "1";
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [frequencyData, setFrequencyData] = useState<Uint8Array | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const audioLevelRef = useRef(0);
  const optionsRef = useRef(options);
  const vadWorkerRef = useRef<Worker | null>(null);
  const vadWorkerReadyRef = useRef(false);
  const vadInitializationPromiseRef = useRef<Promise<void> | null>(null);
  const vadInitTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const vadEpochRef = useRef(0);
  const energyVadRef = useRef(new EnergyVadEndpoint());
  const activeVadModeRef = useRef<"silero" | "energy" | null>(null);
  const resolveVadReadyRef = useRef<(() => void) | null>(null);
  const rejectVadReadyRef = useRef<((error: Error) => void) | null>(null);

  const startTimeRef = useRef<number>(0);
  const pauseCountRef = useRef(0);

  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const ensureVadWorker = useCallback((): Promise<void> => {
    if (vadWorkerReadyRef.current) return Promise.resolve();
    if (vadInitializationPromiseRef.current) return vadInitializationPromiseRef.current;

    const epoch = ++vadEpochRef.current;
    const worker = new Worker(new URL("../workers/vad.worker.ts", import.meta.url), { type: "module" });
    vadWorkerRef.current = worker;
    const isCurrent = () => vadEpochRef.current === epoch && vadWorkerRef.current === worker;
    const clearInitialization = () => {
      if (vadInitTimeoutRef.current) clearTimeout(vadInitTimeoutRef.current);
      vadInitTimeoutRef.current = null;
      resolveVadReadyRef.current = null;
      rejectVadReadyRef.current = null;
      vadInitializationPromiseRef.current = null;
    };
    const readyPromise = new Promise<void>((resolve, reject) => {
      vadInitTimeoutRef.current = setTimeout(() => {
        if (!isCurrent()) return; // An old StrictMode worker cannot fail a new one.
        clearInitialization();
        worker.terminate();
        vadWorkerRef.current = null;
        reject(new Error("Silero VAD khởi tạo quá lâu; đang dùng VAD local dự phòng."));
      }, 60000);
      resolveVadReadyRef.current = resolve;
      rejectVadReadyRef.current = reject;
    });
    vadInitializationPromiseRef.current = readyPromise;

    const fail = (error: Error) => {
      if (!isCurrent()) return;
      const pending = !vadWorkerReadyRef.current;
      const reject = rejectVadReadyRef.current;
      clearInitialization();
      worker.terminate();
      vadWorkerRef.current = null;
      vadWorkerReadyRef.current = false;
      if (activeVadModeRef.current === "silero") {
        activeVadModeRef.current = "energy";
        energyVadRef.current.reset();
        optionsRef.current?.onVadModeChange?.("energy");
      }
      if (pending) reject?.(error);
      else optionsRef.current?.onVadError?.(error.message);
    };
    worker.onmessage = (event: MessageEvent) => {
      if (!isCurrent()) return;
      const message = event.data ?? {};
      if (message.type === "ready") {
        const resolve = resolveVadReadyRef.current;
        clearInitialization();
        vadWorkerReadyRef.current = true;
        resolve?.();
        if (!mediaStreamRef.current || activeVadModeRef.current === "silero") {
          optionsRef.current?.onVadModeChange?.("silero");
          optionsRef.current?.onVadReady?.();
        }
      } else if (message.type === "speech_start") {
        if (activeVadModeRef.current === "silero") optionsRef.current?.onSpeechStart?.();
      } else if (message.type === "speech_end") {
        if (activeVadModeRef.current === "silero") {
          pauseCountRef.current += 1;
          optionsRef.current?.onSpeechEnd?.();
        }
      } else if (message.type === "error") {
        fail(new Error(message.payload?.message || "Silero VAD gặp lỗi."));
      }
    };
    worker.onerror = (event) => fail(new Error(event.message || "Không khởi chạy được Silero VAD Worker."));
    worker.postMessage({ type: "init", payload: { modelUrl: "/models/silero_vad.onnx" } });
    return readyPromise;
  }, []);

  const prepareVadWorker = useCallback(async () => {
    if (forceEnergyVad()) return;
    const ready = ensureVadWorker();
    const epoch = vadEpochRef.current;
    try {
      await ready;
    } catch (error) {
      if (epoch !== vadEpochRef.current) return;
      optionsRef.current?.onVadError?.(
        error instanceof Error ? error.message : "Không tải được Silero VAD.",
      );
    }
  }, [ensureVadWorker]);

  const releaseAudioResources = useCallback(() => {
    if (animFrameRef.current !== null) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    sourceRef.current?.disconnect();
    sourceRef.current = null;
    scriptProcessorRef.current?.disconnect();
    scriptProcessorRef.current = null;
    analyserRef.current?.disconnect();
    analyserRef.current = null;
    const audioContext = audioContextRef.current;
    audioContextRef.current = null;
    if (audioContext && audioContext.state !== "closed") {
      void audioContext.close().catch(() => undefined);
    }
  }, []);

  const startRecording = useCallback(async () => {
    if (mediaStreamRef.current) return;

    let stream: MediaStream | null = null;
    try {
      // The microphone must not wait for ONNX download/compilation. Energy VAD
      // covers this turn; a ready Silero worker is picked up on the next one.
      void prepareVadWorker();
      activeVadModeRef.current = !forceEnergyVad() && vadWorkerReadyRef.current ? "silero" : "energy";
      energyVadRef.current.reset();
      optionsRef.current?.onVadModeChange?.(activeVadModeRef.current);
      if (activeVadModeRef.current === "silero") vadWorkerRef.current?.postMessage({ type: "reset" });

      if (typeof window === "undefined" || !navigator.mediaDevices) {
        throw new Error("Trình duyệt không hỗ trợ truy cập micro");
      }

      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      mediaStreamRef.current = stream;
      const AudioCtx = window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioCtx) throw new Error("Trình duyệt không hỗ trợ xử lý âm thanh trực tiếp");
      const audioCtx = new AudioCtx({ sampleRate: 16000 });
      audioContextRef.current = audioCtx;
      if (audioCtx.state === "suspended") await audioCtx.resume();

      const source = audioCtx.createMediaStreamSource(stream);
      sourceRef.current = source;
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      // The captured microphone stream supplies both local levels and PCM
      // chunks to local Qwen3-ASR; no second transcription microphone.
      const scriptProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
      scriptProcessorRef.current = scriptProcessor;

      scriptProcessor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        optionsRef.current?.onAudioChunk?.(inputData.slice(), e.inputBuffer.sampleRate);
        const worker = vadWorkerRef.current;
        if (activeVadModeRef.current === "silero" && worker && vadWorkerReadyRef.current) {
          const vadSamples = resampleMonoFloat(inputData, e.inputBuffer.sampleRate, 16000);
          worker.postMessage(
            { type: "process", payload: { audioData: vadSamples, sampleRate: 16000 } },
            [vadSamples.buffer as ArrayBuffer],
          );
        } else {
          const decision = energyVadRef.current.process(inputData, e.inputBuffer.sampleRate);
          if (decision.speechStarted) optionsRef.current?.onSpeechStart?.();
          if (decision.speechEnded) {
            pauseCountRef.current += 1;
            optionsRef.current?.onSpeechEnd?.();
          }
        }
      };

      source.connect(analyser);
      analyser.connect(scriptProcessor);
      scriptProcessor.connect(audioCtx.destination);

      startTimeRef.current = Date.now();
      pauseCountRef.current = 0;
      setIsRecording(true);

      // Loop for frequency analysis & UI meter
      const updateMeter = () => {
        if (!analyserRef.current) return;
        const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(dataArray);
        setFrequencyData(dataArray);

        // Compute average level
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i];
        }
        const avg = sum / dataArray.length / 255;
        audioLevelRef.current = avg;
        setAudioLevel((previous) => Math.abs(previous - avg) >= 0.01 ? avg : previous);

        animFrameRef.current = requestAnimationFrame(updateMeter);
      };

      animFrameRef.current = requestAnimationFrame(updateMeter);
    } catch (err: unknown) {
      stream?.getTracks().forEach((track) => track.stop());
      releaseAudioResources();
      setIsRecording(false);
      console.error("Microphone access failed:", err);
      throw err;
    }
  }, [prepareVadWorker, releaseAudioResources]);

  const stopRecording = useCallback((): AudioFeatures => {
    const wasRecording = mediaStreamRef.current !== null;
    const rmsLevel = audioLevelRef.current;
    releaseAudioResources();

    setIsRecording(false);
    setAudioLevel(0);
    audioLevelRef.current = 0;
    setFrequencyData(null);

    const durationSec = wasRecording ? Math.max(0.1, (Date.now() - startTimeRef.current) / 1000) : 0;
    const features: AudioFeatures = {
      durationSec,
      audioQualityOk: true,
      rmsLevel,
      pauseCount: pauseCountRef.current,
      speakingTimeSec: Math.max(0, durationSec - pauseCountRef.current * 0.8),
    };

    vadWorkerRef.current?.postMessage({ type: "reset" });
    activeVadModeRef.current = null;
    energyVadRef.current.reset();
    if (wasRecording) optionsRef.current?.onFeaturesExtracted?.(features);
    return features;
  }, [releaseAudioResources]);

  useEffect(() => {
    return () => {
      vadEpochRef.current += 1;
      if (vadInitTimeoutRef.current) clearTimeout(vadInitTimeoutRef.current);
      vadInitTimeoutRef.current = null;
      rejectVadReadyRef.current?.(new DOMException("Worker released", "AbortError"));
      resolveVadReadyRef.current = null;
      rejectVadReadyRef.current = null;
      releaseAudioResources();
      const worker = vadWorkerRef.current;
      if (worker) {
        worker.postMessage({ type: "destroy" });
        worker.terminate();
      }
      vadWorkerRef.current = null;
      vadWorkerReadyRef.current = false;
      vadInitializationPromiseRef.current = null;
      activeVadModeRef.current = null;
    };
  }, [releaseAudioResources]);

  return {
    isRecording,
    audioLevel,
    frequencyData,
    startRecording,
    stopRecording,
    prepareVadWorker,
  };
}
