/**
 * CÓC ĐI LÀM — Edge Runtime Orchestrator (§2.4A, §4)
 * Quản lý trạng thái và điều phối 3 Web Workers:
 * 1. Silero VAD Worker (Phát hiện giọng nói & Barge-in)
 * 2. Whisper STT Worker (Speech-to-Text local)
 * 3. Piper TTS Worker (Text-to-Speech vi_VN)
 * Tự động chuyển đổi chế độ suy thoái (Graceful Degradation) nếu thiết bị yếu hoặc WASM lỗi.
 */

import { technicalTermRecovery } from "./technicalTermRecovery";

export type EdgeState = "IDLE" | "LISTENING" | "THINKING" | "SPEAKING" | "ERROR";

export interface EdgeRuntimeConfig {
  vadModelUrl?: string;
  whisperModelUrl?: string;
  piperVoiceUrl?: string;
  onPartialTranscript?: (text: string) => void;
  onFinalTranscript?: (text: string, termCandidates: any[]) => void;
  onBargeIn?: () => void;
  onStateChange?: (state: EdgeState) => void;
  onError?: (error: string) => void;
}

export class EdgeRuntimeOrchestrator {
  private state: EdgeState = "IDLE";
  private vadWorker: Worker | null = null;
  private whisperWorker: Worker | null = null;
  private piperWorker: Worker | null = null;
  private config: EdgeRuntimeConfig;
  private isDegradedMode = false;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private recognition: any = null; // Fallback Web Speech API
  private currentAudio: HTMLAudioElement | null = null;
  private lastRecordedText = "";
  private accumulatedFinalText = "";
  private silenceTimer: any = null;

  constructor(config: EdgeRuntimeConfig) {
    this.config = config;
  }

  private setState(newState: EdgeState) {
    this.state = newState;
    this.config.onStateChange?.(newState);
  }

  getState(): EdgeState {
    return this.state;
  }

  /**
   * Khởi tạo Web Workers và fallback speech recognition
   */
  async init(): Promise<void> {
    if (typeof window === "undefined") return;

    try {
      // Khởi tạo VAD Worker
      try {
        this.vadWorker = new Worker(
          new URL("../workers/vad.worker.ts", import.meta.url),
          { type: "module" }
        );

        this.vadWorker.onmessage = (event) => {
          const { type, isSpeaking } = event.data;
          if (type === "SPEECH_START") {
            // Khi đang nói mà AI đang phát biểu → Kích hoạt BARGE-IN (§9)
            if (this.state === "SPEAKING") {
              this.handleBargeIn();
            }
            this.setState("LISTENING");
          } else if (type === "SPEECH_END") {
            // Speech kết thúc -> hoàn tất final transcript
            this.flushWhisper();
          }
        };

        this.vadWorker.postMessage({ type: "INIT" });
      } catch (err) {
        console.warn("VAD Worker init failed, using fallback:", err);
      }

      // Khởi tạo Whisper Worker
      try {
        this.whisperWorker = new Worker(
          new URL("../workers/whisper.worker.ts", import.meta.url),
          { type: "module" }
        );

        this.whisperWorker.onmessage = (event) => {
          const { type, text, isFinal } = event.data;
          if (type === "TRANSCRIPT") {
            const recovery = technicalTermRecovery.recover(text);
            if (isFinal) {
              this.config.onFinalTranscript?.(recovery.recoveredText, recovery.candidates);
              this.setState("THINKING");
            } else {
              this.config.onPartialTranscript?.(recovery.recoveredText);
            }
          }
        };

        this.whisperWorker.postMessage({ type: "INIT" });
      } catch (err) {
        console.warn("Whisper Worker init failed:", err);
      }

      // Khởi tạo Web Speech API làm fallback nhanh chóng
      const SpeechRecognition =
        (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SpeechRecognition) {
        this.recognition = new SpeechRecognition();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.lang = "vi-VN";

        this.recognition.onresult = (event: any) => {
          let interim = "";
          let final = "";

          for (let i = event.resultIndex; i < event.results.length; ++i) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
              final += transcript;
            } else {
              interim += transcript;
            }
          }

          if (final) {
            this.accumulatedFinalText = (this.accumulatedFinalText + " " + final).trim();
          }

          const currentCombined = (this.accumulatedFinalText + " " + interim).trim();
          if (currentCombined) {
            this.lastRecordedText = currentCombined;
            const recovery = technicalTermRecovery.recover(currentCombined);
            this.config.onPartialTranscript?.(recovery.recoveredText);
          }

          // Debounce tự động chốt transcript khi ứng viên đã im lặng liên tục trên 3.5 giây
          if (this.silenceTimer) {
            clearTimeout(this.silenceTimer);
            this.silenceTimer = null;
          }

          if (this.accumulatedFinalText && !interim) {
            this.silenceTimer = setTimeout(() => {
              if (this.state === "LISTENING" && this.accumulatedFinalText) {
                const fullText = this.accumulatedFinalText;
                this.accumulatedFinalText = "";
                this.lastRecordedText = "";
                const recovery = technicalTermRecovery.recover(fullText);
                this.config.onFinalTranscript?.(recovery.recoveredText, recovery.candidates);
                this.setState("THINKING");
              }
            }, 3500);
          }
        };

        this.recognition.onerror = (e: any) => {
          console.warn("SpeechRecognition error:", e);
        };
      }

      this.setState("IDLE");
    } catch (error: any) {
      console.error("Failed to initialize Edge Runtime:", error);
      this.isDegradedMode = true;
      this.config.onError?.(error.message || "Lỗi khởi tạo Edge AI");
    }
  }

  /**
   * Bắt đầu lắng nghe ứng viên
   */
  async startListening(): Promise<void> {
    try {
      this.accumulatedFinalText = "";
      this.lastRecordedText = "";
      if (this.silenceTimer) {
        clearTimeout(this.silenceTimer);
        this.silenceTimer = null;
      }
      this.setState("LISTENING");
      if (this.recognition) {
        try {
          this.recognition.start();
        } catch (e) {
          // May already be started
        }
      }
    } catch (e: any) {
      this.config.onError?.(e.message || "Không thể mở micro");
    }
  }

  /**
   * Dừng lắng nghe và trả về phần văn bản đã ghi nhận nếu chưa kịp chốt final
   */
  stopListening(): string {
    if (this.silenceTimer) {
      clearTimeout(this.silenceTimer);
      this.silenceTimer = null;
    }
    if (this.recognition) {
      try {
        this.recognition.stop();
      } catch (e) {}
    }
    this.flushWhisper();
    this.setState("IDLE");

    let full = this.accumulatedFinalText.trim();
    if (this.lastRecordedText && this.lastRecordedText.trim()) {
      const last = this.lastRecordedText.trim();
      if (!full.includes(last)) {
        full = (full + " " + last).trim();
      }
    }
    this.accumulatedFinalText = "";
    this.lastRecordedText = "";
    return full;
  }

  /**
   * Gửi trực tiếp câu trả lời bằng văn bản (hỗ trợ nhập liệu bàn phím / test E2E)
   */
  submitTextAnswer(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    this.stopListening();
    const recovery = technicalTermRecovery.recover(trimmed);
    this.config.onFinalTranscript?.(recovery.recoveredText, recovery.candidates);
    this.setState("THINKING");
  }

  /**
   * Xử lý barge-in (ngắt lời AI ngay lập tức)
   */
  handleBargeIn(): void {
    this.stopTTS();
    this.config.onBargeIn?.();
    this.setState("LISTENING");
  }

  /**
   * Dừng phát âm thanh TTS ngay lập tức (phục vụ Barge-In)
   */
  stopTTS(): void {
    if (this.currentAudio) {
      try {
        this.currentAudio.pause();
        this.currentAudio.currentTime = 0;
      } catch {
        // ignore
      }
      this.currentAudio = null;
    }
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
  }

  /**
   * Phát câu hỏi / phản hồi của AI bằng giọng nói Neural tiếng Việt chuẩn con người (Hoài My)
   */
  speak(text: string, onEnd?: () => void): void {
    this.stopTTS();
    this.setState("SPEAKING");

    let isCompleted = false;
    const cleanupAndFinish = () => {
      if (isCompleted) return;
      isCompleted = true;
      clearTimeout(watchdogTimer);
      if (this.currentAudio) {
        this.currentAudio = null;
      }
      this.setState("IDLE");
      onEnd?.();
    };

    // Watchdog Timer chống treo trạng thái
    const wordCount = text.trim().split(/\s+/).length;
    const estimatedDurationMs = Math.max(4000, Math.min(25000, wordCount * 360 + 2500));
    const watchdogTimer = setTimeout(() => {
      console.log(`[EdgeRuntime] TTS Watchdog fired after ${estimatedDurationMs}ms - resetting state.`);
      cleanupAndFinish();
    }, estimatedDurationMs);

    const fallbackToSpeechSynthesis = () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        try {
          window.speechSynthesis.cancel();
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.lang = "vi-VN";
          utterance.rate = 1.0;
          utterance.onend = () => cleanupAndFinish();
          utterance.onerror = () => cleanupAndFinish();
          window.speechSynthesis.speak(utterance);
        } catch {
          cleanupAndFinish();
        }
      } else {
        cleanupAndFinish();
      }
    };

    // 1. Ưu tiên phát bằng Microsoft Neural TTS (Giọng Hoài My vi-VN cực kỳ tự nhiên, truyền cảm như người thật)
    if (typeof window !== "undefined") {
      try {
        const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const ttsUrl = `${apiBase}/api/v1/tts/synthesize?text=${encodeURIComponent(text)}&voice=vi-VN-HoaiMyNeural`;
        const audio = new Audio(ttsUrl);
        this.currentAudio = audio;

        audio.onended = () => {
          cleanupAndFinish();
        };

        audio.onerror = (err) => {
          console.warn("[EdgeRuntime] Neural TTS audio load error, fallback to browser synthesis:", err);
          fallbackToSpeechSynthesis();
        };

        audio.play().catch((err) => {
          console.warn("[EdgeRuntime] Neural TTS autoplay policy or network error:", err);
          fallbackToSpeechSynthesis();
        });
      } catch (err) {
        console.warn("[EdgeRuntime] Neural TTS initialization error:", err);
        fallbackToSpeechSynthesis();
      }
    } else {
      cleanupAndFinish();
    }
  }

  private flushWhisper() {
    this.whisperWorker?.postMessage({ type: "FINALIZE" });
  }

  destroy(): void {
    this.stopListening();
    this.stopTTS();
    this.vadWorker?.terminate();
    this.whisperWorker?.terminate();
    this.piperWorker?.terminate();
    this.vadWorker = null;
    this.whisperWorker = null;
    this.piperWorker = null;
  }
}
