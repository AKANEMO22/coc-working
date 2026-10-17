/** Join recognized answer segments while avoiding repeated overlap at boundaries. */
export function appendAnswerSegment(existingText: string, segmentText: string): string {
  const existing = existingText.trim().replace(/\s+/g, " ");
  const segment = segmentText.trim().replace(/\s+/g, " ");
  if (!existing) return segment;
  if (!segment || existing.toLocaleLowerCase() === segment.toLocaleLowerCase()) return existing;
  if (segment.toLocaleLowerCase().startsWith(existing.toLocaleLowerCase())) return segment;
  if (existing.toLocaleLowerCase().endsWith(segment.toLocaleLowerCase())) return existing;

  const oldWords = existing.split(" ");
  const newWords = segment.split(" ");
  const maxOverlap = Math.min(oldWords.length, newWords.length, 40);
  for (let count = maxOverlap; count > 0; count -= 1) {
    const oldTail = oldWords.slice(-count).map((word) => word.toLocaleLowerCase());
    const newHead = newWords.slice(0, count).map((word) => word.toLocaleLowerCase());
    if (oldTail.every((word, index) => word === newHead[index])) {
      return [...oldWords, ...newWords.slice(count)].join(" ").trim();
    }
  }
  return `${existing} ${segment}`.trim();
}
