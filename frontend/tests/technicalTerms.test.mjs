import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/technicalTermRecovery.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { technicalTermRecovery } = await import(
  "data:text/javascript;base64," + Buffer.from(compiled).toString("base64")
);

test("phonetic lexicon proposes but never silently rewrites Qwen words", () => {
  const original = "Em dùng ri ác cho giao diện.";
  const result = technicalTermRecovery.recover(original);
  assert.equal(result.recoveredText, original);
  assert.deepEqual(result.candidates, [{
    raw: "ri ác", recovered: "React", domain: "frontend", source: "phonetic_lexicon",
  }]);
  assert.equal("confidence" in result.candidates[0], false);
});
