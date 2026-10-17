# Local VAD model

The interview mic endpoint detector uses the Silero VAD ONNX model locally in
the browser. Transcription runs with local Qwen3-ASR through the FastAPI
`/api/v1/stt/transcribe` endpoint.

- Model: silero_vad.onnx
- Upstream: https://github.com/snakers4/silero-vad
- Pinned upstream revision: v6.2.3 / 5cd7945
- SHA-256: 1A153A22F4509E292A94E67D6F9B85E8DEB25B4988682B7E174C65279D8788E3
- License: SILERO-VAD-LICENSE.txt (MIT)
- Runtime: onnxruntime-web in src/workers/vad.worker.ts
- ONNX Runtime WASM loader/assets: `models/ort/` (synced from installed
  `onnxruntime-web` by `npm install` postinstall script).

The worker runs 512-sample windows at 16 kHz with 64 samples of recurrent
context, then applies a 1.2-second local silence endpoint.
