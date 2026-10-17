/** Local amplitude endpoint while Silero's WASM worker is still loading. */
export class EnergyVadEndpoint {
  private active = false;
  private speechCandidateMs = 0;
  private silenceMs = 0;
  private noiseFloor = 0.004;

  reset(): void {
    this.active = false;
    this.speechCandidateMs = 0;
    this.silenceMs = 0;
    this.noiseFloor = 0.004;
  }

  process(samples: Float32Array, sampleRate: number): { speechStarted: boolean; speechEnded: boolean; rms: number } {
    if (!samples.length || sampleRate <= 0) return { speechStarted: false, speechEnded: false, rms: 0 };
    let sum = 0;
    for (const sample of samples) sum += sample * sample;
    const rms = Math.sqrt(sum / samples.length);
    const durationMs = samples.length / sampleRate * 1000;
    const startThreshold = Math.max(0.012, this.noiseFloor * 2.8);
    const stopThreshold = Math.max(0.007, this.noiseFloor * 1.8);
    let speechStarted = false;
    let speechEnded = false;

    if (!this.active) {
      if (rms >= startThreshold) {
        this.speechCandidateMs += durationMs;
        if (this.speechCandidateMs >= 250) {
          this.active = true;
          this.silenceMs = 0;
          speechStarted = true;
        }
      } else {
        this.speechCandidateMs = 0;
        this.noiseFloor = Math.min(0.015, this.noiseFloor * 0.92 + rms * 0.08);
      }
    } else if (rms < stopThreshold) {
      this.silenceMs += durationMs;
      if (this.silenceMs >= 1200) {
        this.active = false;
        this.speechCandidateMs = 0;
        this.silenceMs = 0;
        speechEnded = true;
      }
    } else {
      this.silenceMs = 0;
    }
    return { speechStarted, speechEnded, rms };
  }
}
