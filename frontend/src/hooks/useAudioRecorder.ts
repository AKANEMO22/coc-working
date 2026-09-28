"use client";

import { useState, useRef, useCallback, useEffect } from "react";

export interface AudioFeatures {
  durationSec: number;
  audioQualityOk: boolean;
  rmsLevel: number;
  pauseCount: number;
  speakingTimeSec: number;
}

interface UseAudioRecorderOptions {
  onAudioData?: (pcmData: Float32Array) => void;
  onFeaturesExtracted?: (features: AudioFeatures) => void;
}

export function useAudioRecorder(options?: UseAudioRecorderOptions) {
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [frequencyData, setFrequencyData] = useState<Uint8Array | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const animFrameRef = useRef<number | null>(null);

  const startTimeRef = useRef<number>(0);
  const pauseCountRef = useRef<number>(0);
  const lastActiveRef = useRef<number>(0);

  const startRecording = useCallback(async () => {
    try {
      if (typeof window === "undefined" || !navigator.mediaDevices) {
        throw new Error("Trình duyệt không hỗ trợ truy cập micro");
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      mediaStreamRef.current = stream;
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      const audioCtx = new AudioCtx({ sampleRate: 16000 });
      audioContextRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      // ScriptProcessor for PCM audio streaming to VAD/Whisper
      const scriptProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
      scriptProcessorRef.current = scriptProcessor;

      scriptProcessor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        options?.onAudioData?.(inputData);

        // Feature calculations: RMS
        let sumSquares = 0;
        for (let i = 0; i < inputData.length; i++) {
          sumSquares += inputData[i] * inputData[i];
        }
        const rms = Math.sqrt(sumSquares / inputData.length);
        const now = Date.now();

        if (rms < 0.02) {
          if (now - lastActiveRef.current > 1200) {
            pauseCountRef.current += 1;
            lastActiveRef.current = now;
          }
        } else {
          lastActiveRef.current = now;
        }
      };

      source.connect(analyser);
      analyser.connect(scriptProcessor);
      scriptProcessor.connect(audioCtx.destination);

      startTimeRef.current = Date.now();
      lastActiveRef.current = Date.now();
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
        setAudioLevel(avg);

        animFrameRef.current = requestAnimationFrame(updateMeter);
      };

      animFrameRef.current = requestAnimationFrame(updateMeter);
    } catch (err: any) {
      console.error("Microphone access failed:", err);
      throw err;
    }
  }, [options]);

  const stopRecording = useCallback((): AudioFeatures => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }

    if (scriptProcessorRef.current) {
      scriptProcessorRef.current.disconnect();
      scriptProcessorRef.current = null;
    }

    if (analyserRef.current) {
      analyserRef.current.disconnect();
      analyserRef.current = null;
    }

    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    setIsRecording(false);
    setAudioLevel(0);
    setFrequencyData(null);

    const durationSec = Math.max(0.1, (Date.now() - startTimeRef.current) / 1000);
    const features: AudioFeatures = {
      durationSec,
      audioQualityOk: true,
      rmsLevel: audioLevel,
      pauseCount: pauseCountRef.current,
      speakingTimeSec: Math.max(0, durationSec - pauseCountRef.current * 0.8),
    };

    options?.onFeaturesExtracted?.(features);
    return features;
  }, [audioLevel, options]);

  useEffect(() => {
    return () => {
      if (isRecording) {
        stopRecording();
      }
    };
  }, [isRecording, stopRecording]);

  return {
    isRecording,
    audioLevel,
    frequencyData,
    startRecording,
    stopRecording,
  };
}
