import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/lib/answerDraft.ts", import.meta.url), "utf8");
const appendSource = source.match(/export function appendAnswerSegment[\s\S]*?\n}/)?.[0];
assert.ok(appendSource, "appendAnswerSegment must remain a simple pure function");
const runnableSource = appendSource
  .replace("export function", "function")
  .replace("existingText: string", "existingText")
  .replace("segmentText: string", "segmentText")
  .replace("): string {", ") {");
const appendAnswerSegment = new Function(`${runnableSource}\nreturn appendAnswerSegment;`)();

test("separate spoken segments append to the same answer", () => {
  assert.equal(appendAnswerSegment("Em dùng Redis", "để cache dữ liệu"), "Em dùng Redis để cache dữ liệu");
});

test("overlapping recognized segments are not duplicated", () => {
  assert.equal(appendAnswerSegment("Em dùng Redis để cache", "để cache dữ liệu"), "Em dùng Redis để cache dữ liệu");
});

test("a repeated full transcript replaces/retains instead of duplicating", () => {
  assert.equal(appendAnswerSegment("Em dùng Redis để cache dữ liệu", "Em dùng Redis để cache dữ liệu"), "Em dùng Redis để cache dữ liệu");
});
