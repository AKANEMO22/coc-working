import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
for (const filename of ["ort-wasm-simd-threaded.wasm", "ort-wasm-simd-threaded.mjs"]) {
  const source = resolve(frontend, "node_modules", "onnxruntime-web", "dist", filename);
  const destination = resolve(frontend, "public", "models", "ort", filename);
  mkdirSync(dirname(destination), { recursive: true });
  copyFileSync(source, destination);
  console.log(`Copied ONNX Runtime asset to public/models/ort/${filename}`);
}
