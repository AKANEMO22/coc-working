export interface SileroVadDecision {
  isSpeechActive: boolean;
  speechStarted: boolean;
  speechEnded: boolean;
  silenceMs: number;
}

export interface SileroVadEndpointOptions {
  speechThreshold?: number;
  silenceThreshold?: number;
  minSpeechDurationMs?: number;
  endSilenceDurationMs?: number;
}

const DEFAULTS: Required<SileroVadEndpointOptions> = {
  speechThreshold: 0.5,
  silenceThreshold: 0.35,
  minSpeechDurationMs: 250,
  endSilenceDurationMs: 1200,
};

/** Converts Silero's per-frame speech probabilities into turn start/end events. */
export class SileroVadEndpoint {
  private readonly options: Required<SileroVadEndpointOptions>;
  private speechCandidateMs = 0;
  private silenceMs = 0;
  private active = false;

  constructor(options: SileroVadEndpointOptions = {}) {
    this.options = { ...DEFAULTS, ...options };
  }

  process(probability: number, frameDurationMs = 32): SileroVadDecision {
    const score = Number.isFinite(probability) ? Math.max(0, Math.min(1, probability)) : 0;
    let speechStarted = false;
    let speechEnded = false;

    if (!this.active) {
      if (score >= this.options.speechThreshold) {
        this.speechCandidateMs += frameDurationMs;
        if (this.speechCandidateMs >= this.options.minSpeechDurationMs) {
          this.active = true;
          this.silenceMs = 0;
          speechStarted = true;
        }
      } else {
        this.speechCandidateMs = 0;
      }
    } else if (score < this.options.silenceThreshold) {
      this.silenceMs += frameDurationMs;
      if (this.silenceMs >= this.options.endSilenceDurationMs) {
        this.active = false;
        this.speechCandidateMs = 0;
        this.silenceMs = 0;
        speechEnded = true;
      }
    } else {
      this.silenceMs = 0;
    }

    return {
      isSpeechActive: this.active,
      speechStarted,
      speechEnded,
      silenceMs: this.silenceMs,
    };
  }

  reset(): void {
    this.speechCandidateMs = 0;
    this.silenceMs = 0;
    this.active = false;
  }
}
