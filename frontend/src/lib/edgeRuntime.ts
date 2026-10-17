/** Local interview voice runtime: Qwen3-ASR on the backend and VieNeu TTS. */
import { technicalTermRecovery, type TermCandidate } from "./technicalTermRecovery";
import { resampleMonoFloat, encodeMonoWav } from "./audioPcm";
import { appendAnswerSegment } from "./answerDraft";
import { revealAlignedWords, type CharacterAlignment } from "./speechAlignment";

export type EdgeState = "IDLE" | "LISTENING" | "THINKING" | "PREPARING_TTS" | "SPEAKING" | "ERROR";

export interface EdgeRuntimeConfig {
  sessionId: string;
  onPartialTranscript?: (text: string, audioQualityOk: boolean, latencyMs: number) => void;
  onFinalTranscript?: (text: string, termCandidates: TermCandidate[], evidence: ASREvidence) => void;
  onUnclearAudio?: (evidence: ASREvidence) => void;
  onBargeIn?: () => void;
  onStateChange?: (state: EdgeState) => void;
  onError?: (error: string) => void;
}

export interface ASREvidence {
  source: "qwen_microphone";
  duration_sec: number;
  rms: number;
  clipped_fraction: number;
  audio_quality_ok: boolean;
}

const STT_SAMPLE_RATE = 16000;
const FIRST_PARTIAL_SAMPLES = Math.round(STT_SAMPLE_RATE * 1.5);
const PARTIAL_INTERVAL_SAMPLES = STT_SAMPLE_RATE * 3;
const PARTIAL_WINDOW_SAMPLES = Math.round(STT_SAMPLE_RATE * 4.5);
const MAX_UTTERANCE_SAMPLES = STT_SAMPLE_RATE * 120;

export class EdgeRuntimeOrchestrator {
  private state: EdgeState = "IDLE";
  private config: EdgeRuntimeConfig;
  private listeningGeneration = 0;
  private listening = false;
  private audioChunks: Float32Array[] = [];
  private totalSamples = 0;
  private nextPartialAt = FIRST_PARTIAL_SAMPLES;
  private speechStartSampleIndex: number | null = null;
  private speechEndSampleIndex: number | null = null;
  private partialController: AbortController | null = null;
  private finalController: AbortController | null = null;
  private lastPartial = "";
  private currentAudio: HTMLAudioElement | null = null;
  private currentAudioObjectUrl: string | null = null;
  private playbackGeneration = 0;
  private playbackFrame: number | null = null;
  private playbackWatchdog: ReturnType<typeof setTimeout> | null = null;
  private activeSpeechText: string | null = null;
  private activeSpeechProgress: ((visibleText: string) => void) | null = null;

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

  async init(): Promise<void> {
    this.setState("IDLE");
  }

  async startListening(): Promise<void> {
    this.cancelListening();
    this.listening = true;
    this.audioChunks = [];
    this.totalSamples = 0;
    this.nextPartialAt = FIRST_PARTIAL_SAMPLES;
    this.speechStartSampleIndex = null;
    this.speechEndSampleIndex = null;
    this.lastPartial = "";
    this.setState("LISTENING");
  }

  private collectAudio(limit?: number): Float32Array {
    const count = Math.min(this.totalSamples, limit ?? this.totalSamples);
    const output = new Float32Array(count);
    let destination = count;
    for (let index = this.audioChunks.length - 1; index >= 0 && destination > 0; index--) {
      const chunk = this.audioChunks[index];
      const used = Math.min(destination, chunk.length);
      destination -= used;
      output.set(chunk.subarray(chunk.length - used), destination);
    }
    return output;
  }

  private async transcribe(samples: Float32Array, signal: AbortSignal, kind: "partial" | "final"): Promise<string> {
    const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    const body = new FormData();
    body.append("file", encodeMonoWav(samples), "speech.wav");
    const response = await fetch(`${apiBase}/api/v1/stt/transcribe?language=vi&kind=${kind}&session_id=${encodeURIComponent(this.config.sessionId)}`, {
      method: "POST", body, signal,
    });
    const payload = await response.json().catch(() => ({})) as { text?: string; detail?: string };
    if (!response.ok) throw new Error(payload.detail || `Qwen3-ASR HTTP ${response.status}`);
    return (payload.text || "").trim();
  }

  markSpeechStarted(): void {
    this.speechEndSampleIndex = null;
    if (this.listening && this.speechStartSampleIndex === null) {
      this.speechStartSampleIndex = this.totalSamples;
    }
  }

  markSpeechEnded(): void {
    if (this.listening) this.speechEndSampleIndex = this.totalSamples;
  }

  sendAudioChunk(samples: Float32Array, sourceSampleRate: number): void {
    if (!this.listening || !samples.length) return;
    const converted = resampleMonoFloat(samples, sourceSampleRate, STT_SAMPLE_RATE);
    if (this.totalSamples + converted.length > MAX_UTTERANCE_SAMPLES) {
      this.cancelListening();
      this.config.onError?.("Câu trả lời quá 120 giây. Hãy nói ngắn hơn hoặc nhập văn bản.");
      return;
    }
    this.audioChunks.push(converted);
    this.totalSamples += converted.length;
    if (this.speechStartSampleIndex === null ||
        this.totalSamples - this.speechStartSampleIndex < this.nextPartialAt || this.partialController) return;
    this.nextPartialAt += PARTIAL_INTERVAL_SAMPLES;
    const generation = this.listeningGeneration;
    const controller = new AbortController();
    this.partialController = controller;
    const recentAudio = this.collectAudio(PARTIAL_WINDOW_SAMPLES);
    let energy = 0;
    let clipped = 0;
    for (const sample of recentAudio) {
      energy += sample * sample;
      if (Math.abs(sample) > 0.985) clipped++;
    }
    const rms = Math.sqrt(energy / Math.max(1, recentAudio.length));
    const audioQualityOk = rms >= 0.009 && clipped / Math.max(1, recentAudio.length) < 0.12;
    const started = performance.now();
    void this.transcribe(recentAudio, controller.signal, "partial").then((text) => {
      if (!this.listening || generation !== this.listeningGeneration || !text) return;
      const recovery = technicalTermRecovery.recover(text);
      const merged = appendAnswerSegment(this.lastPartial, recovery.recoveredText);
      if (merged !== this.lastPartial) {
        this.lastPartial = merged;
        this.config.onPartialTranscript?.(merged, audioQualityOk, performance.now() - started);
      }
    }).catch((error) => {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        console.warn("[Qwen3-ASR] partial transcription failed", error);
      }
    }).finally(() => {
      if (this.partialController === controller) this.partialController = null;
    });
  }

  stopListening(): void {
    if (!this.listening) return;
    this.listening = false;
    this.partialController?.abort();
    this.partialController = null;
    const allSamples = this.collectAudio();
    // VAD already observed the endpoint. Do not send the extra pause used to
    // debounce speech_end to Qwen: it adds seconds of ASR work without words.
    const start = Math.max(0, (this.speechStartSampleIndex ?? 0) - STT_SAMPLE_RATE / 2);
    const end = Math.min(allSamples.length, (this.speechEndSampleIndex ?? allSamples.length) + STT_SAMPLE_RATE / 5);
    const samples = allSamples.subarray(start, Math.max(start, end));
    const speechStart = Math.min(Math.max(0, (this.speechStartSampleIndex ?? start) - start), samples.length);
    const speechSamples = samples.subarray(speechStart);
    let energy = 0;
    let clipped = 0;
    for (const sample of speechSamples) {
      energy += sample * sample;
      if (Math.abs(sample) > 0.985) clipped++;
    }
    const rms = Math.sqrt(energy / Math.max(1, speechSamples.length));
    const clippedFraction = clipped / Math.max(1, speechSamples.length);
    const evidence: ASREvidence = {
      source: "qwen_microphone",
      duration_sec: speechSamples.length / STT_SAMPLE_RATE,
      rms,
      clipped_fraction: clippedFraction,
      audio_quality_ok: rms >= 0.008 && rms <= 0.6 && clippedFraction < 0.12,
    };
    this.audioChunks = [];
    this.totalSamples = 0;
    this.speechStartSampleIndex = null;
    this.speechEndSampleIndex = null;
    if (samples.length < STT_SAMPLE_RATE / 5) {
      this.setState("IDLE");
      this.config.onError?.("Chưa thu được âm thanh rõ ràng. Hãy thử lại hoặc nhập văn bản.");
      return;
    }
    const generation = this.listeningGeneration;
    const controller = new AbortController();
    this.finalController = controller;
    this.setState("THINKING");
    void this.transcribe(samples, controller.signal, "final").then((text) => {
      if (generation !== this.listeningGeneration) return;
      if (!text) {
        this.setState("THINKING");
        this.config.onUnclearAudio?.({ ...evidence, audio_quality_ok: false });
        return;
      }
      const recovery = technicalTermRecovery.recover(text);
      this.config.onFinalTranscript?.(recovery.recoveredText, recovery.candidates, evidence);
    }).catch((error) => {
      if (generation !== this.listeningGeneration) return;
      this.setState("IDLE");
      this.config.onError?.(error instanceof Error ? error.message : "Qwen3-ASR không nhận dạng được âm thanh.");
    }).finally(() => {
      if (this.finalController === controller) this.finalController = null;
    });
  }

  cancelListening(): void {
    this.listeningGeneration++;
    this.listening = false;
    this.partialController?.abort();
    this.partialController = null;
    this.finalController?.abort();
    this.finalController = null;
    this.audioChunks = [];
    this.totalSamples = 0;
    this.speechStartSampleIndex = null;
    this.speechEndSampleIndex = null;
    this.setState("IDLE");
  }

  submitTextAnswer(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    this.cancelListening();
    const recovery = technicalTermRecovery.recover(trimmed);
    this.config.onFinalTranscript?.(recovery.recoveredText, recovery.candidates, {
      source: "qwen_microphone", duration_sec: 0, rms: 0,
      clipped_fraction: 0, audio_quality_ok: false,
    });
    this.setState("THINKING");
  }

  handleBargeIn(): void {
    this.stopTTS(true);
    this.config.onBargeIn?.();
    this.setState("LISTENING");
  }

  /**
   * Dừng phát âm thanh TTS ngay lập tức (phục vụ Barge-In)
   */
  stopTTS(revealInterruptedText = false): void {
    this.playbackGeneration += 1;
    if (this.playbackWatchdog) {
      clearTimeout(this.playbackWatchdog);
      this.playbackWatchdog = null;
    }
    if (this.playbackFrame !== null && typeof window !== "undefined") {
      cancelAnimationFrame(this.playbackFrame);
      this.playbackFrame = null;
    }
    if (revealInterruptedText && this.activeSpeechText) {
      this.activeSpeechProgress?.(this.activeSpeechText);
    }
    if (this.currentAudio) {
      try {
        this.currentAudio.pause();
        this.currentAudio.currentTime = 0;
        this.currentAudio.onended = null;
        this.currentAudio.onerror = null;
        this.currentAudio.removeAttribute("src");
        this.currentAudio.load();
      } catch {
        // ignore
      }
      this.currentAudio = null;
    }
    if (this.currentAudioObjectUrl) {
      URL.revokeObjectURL(this.currentAudioObjectUrl);
      this.currentAudioObjectUrl = null;
    }
    this.activeSpeechText = null;
    this.activeSpeechProgress = null;
  }

  /** Play local VieNeu speech, revealing captions from estimated audio timing. */
  speak(
    text: string,
    onEnd?: () => void,
    onPlaybackUnavailable?: (reason: string) => void,
    onProgress?: (visibleText: string) => void,
  ): void {
    this.stopTTS(true);
    const generation = this.playbackGeneration;
    this.setState("PREPARING_TTS");

    let isCompleted = false;
    const cleanupAndFinish = () => {
      if (isCompleted) return;
      isCompleted = true;
      if (generation !== this.playbackGeneration) return;
      if (this.playbackWatchdog) {
        clearTimeout(this.playbackWatchdog);
        this.playbackWatchdog = null;
      }
      if (this.playbackFrame !== null) {
        cancelAnimationFrame(this.playbackFrame);
        this.playbackFrame = null;
      }
      if (this.currentAudio) {
        this.currentAudio.onended = null;
        this.currentAudio.onerror = null;
        this.currentAudio = null;
      }
      if (this.currentAudioObjectUrl) {
        URL.revokeObjectURL(this.currentAudioObjectUrl);
        this.currentAudioObjectUrl = null;
      }
      this.activeSpeechText = null;
      this.activeSpeechProgress = null;
      this.setState("IDLE");
      onEnd?.();
    };
    const reportPlaybackUnavailable = (reason: string) => {
      if (generation !== this.playbackGeneration || isCompleted) return;
      onPlaybackUnavailable?.(reason);
      onProgress?.(text);
      cleanupAndFinish();
    };

    this.activeSpeechText = text;
    this.activeSpeechProgress = onProgress || null;

    // Audio generation is allowed its own bounded window; a slow local model
    // must not be mistaken for a finished/failed interview turn after 30 s.
    const synthesisTimeoutMs = 120000;
    this.playbackWatchdog = setTimeout(() => {
      console.warn(`[EdgeRuntime] VieNeu synthesis watchdog fired after ${synthesisTimeoutMs}ms.`);
      reportPlaybackUnavailable("Không nhận được phản hồi âm thanh đúng hạn. Bấm biểu tượng loa để thử phát lại.");
    }, synthesisTimeoutMs);

    const startAlignedPlayback = async () => {
      try {
        const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
        const response = await fetch(`${apiBase}/api/v1/tts/synthesize-aligned`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, session_id: this.config.sessionId }),
        });
        const payload = await response.json().catch(() => ({})) as {
          audio_base64?: string;
          audio_mime_type?: string;
          alignment?: CharacterAlignment | null;
          normalized_alignment?: CharacterAlignment | null;
          detail?: string;
        };
        if (generation !== this.playbackGeneration) return;
        if (!response.ok || !payload.audio_base64) {
          throw new Error(payload.detail || `VieNeu TTS HTTP ${response.status}`);
        }

        const binaryAudio = window.atob(payload.audio_base64);
        const audioBytes = new Uint8Array(binaryAudio.length);
        for (let index = 0; index < binaryAudio.length; index += 1) {
          audioBytes[index] = binaryAudio.charCodeAt(index);
        }
        const audioBlob = new Blob([audioBytes.buffer as ArrayBuffer], { type: payload.audio_mime_type || "audio/wav" });
        const audioUrl = URL.createObjectURL(audioBlob);
        this.currentAudioObjectUrl = audioUrl;
        const audio = new Audio();
        audio.preload = "auto";
        audio.playbackRate = 0.92;
        audio.preservesPitch = true;
        this.currentAudio = audio;
        const alignment = payload.alignment || payload.normalized_alignment || null;
        if (this.playbackWatchdog) clearTimeout(this.playbackWatchdog);
        const playbackSeconds = alignment?.character_end_times_seconds?.at(-1) || Math.ceil(audioBytes.length / 96000);
        const playbackTimeoutMs = Math.max(15000, Math.min(120000, playbackSeconds * 1000 + 20000));
        this.playbackWatchdog = setTimeout(() => {
          reportPlaybackUnavailable("Âm thanh VieNeu phát quá lâu. Bấm loa cạnh câu hỏi để thử lại.");
        }, playbackTimeoutMs);

        audio.onended = () => {
          onProgress?.(text);
          cleanupAndFinish();
        };
        audio.onerror = () => reportPlaybackUnavailable(
          "Không giải mã/phát được audio VieNeu. Bấm loa cạnh câu hỏi để thử lại.",
        );
        audio.src = audioUrl;
        audio.load();

        await new Promise<void>((resolve, reject) => {
          if (audio.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
            resolve();
            return;
          }
          const onCanPlay = () => {
            audio.removeEventListener("canplay", onCanPlay);
            audio.removeEventListener("error", onAudioError);
            resolve();
          };
          const onAudioError = () => {
            audio.removeEventListener("canplay", onCanPlay);
            audio.removeEventListener("error", onAudioError);
            reject(new Error("Không thể giải mã audio VieNeu."));
          };
          audio.addEventListener("canplay", onCanPlay, { once: true });
          audio.addEventListener("error", onAudioError, { once: true });
        });
        if (generation !== this.playbackGeneration) return;

        // Wait for the decoded buffer to settle before releasing the first phoneme.
        await new Promise((resolve) => setTimeout(resolve, 140));
        if (generation !== this.playbackGeneration) return;
        await audio.play();
        this.setState("SPEAKING");

        let lastVisibleText: string | null = null;
        const updateSynchronizedText = () => {
          if (generation !== this.playbackGeneration || audio.paused || audio.ended) return;
          const visibleText = revealAlignedWords(text, alignment, audio.currentTime);
          if (visibleText !== lastVisibleText) {
            lastVisibleText = visibleText;
            onProgress?.(visibleText);
          }
          this.playbackFrame = requestAnimationFrame(updateSynchronizedText);
        };
        updateSynchronizedText();
      } catch (error) {
        if (generation !== this.playbackGeneration) return;
        console.warn("[EdgeRuntime] VieNeu TTS failed:", error);
        const reason = error instanceof DOMException && error.name === "NotAllowedError"
          ? "Trình duyệt chặn tự phát âm thanh. Bấm biểu tượng loa cạnh câu hỏi để nghe lại."
          : error instanceof Error ? error.message : "VieNeu TTS không phát được. Kiểm tra backend rồi bấm loa để thử lại.";
        reportPlaybackUnavailable(reason);
      }
    };

    if (typeof window !== "undefined") void startAlignedPlayback();
    else reportPlaybackUnavailable("Không thể phát âm thanh trong môi trường hiện tại.");
  }

  destroy(): void {
    this.cancelListening();
    this.stopTTS();
  }
}
