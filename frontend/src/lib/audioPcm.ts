/** Mono PCM helpers shared by Silero VAD and local Qwen3-ASR uploads. */
export function resampleMonoFloat(
  samples: Float32Array,
  sourceSampleRate: number,
  targetSampleRate = 16000,
): Float32Array {
  if (!samples.length || !Number.isFinite(sourceSampleRate) || sourceSampleRate <= 0) return new Float32Array(0);
  if (sourceSampleRate === targetSampleRate) return samples.slice();
  const targetLength = Math.max(1, Math.round(samples.length * targetSampleRate / sourceSampleRate));
  const result = new Float32Array(targetLength);
  for (let i = 0; i < targetLength; i++) {
    const sourcePosition = i * sourceSampleRate / targetSampleRate;
    const left = Math.min(samples.length - 1, Math.floor(sourcePosition));
    const right = Math.min(samples.length - 1, left + 1);
    const fraction = sourcePosition - left;
    result[i] = samples[left] + (samples[right] - samples[left]) * fraction;
  }
  return result;
}

export function encodeMonoWav(samples: Float32Array, sampleRate = 16000): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const ascii = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index++) view.setUint8(offset + index, value.charCodeAt(index));
  };
  ascii(0, "RIFF");
  view.setUint32(4, buffer.byteLength - 8, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index++) {
    const value = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(44 + index * 2, value < 0 ? value * 32768 : value * 32767, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
