export interface CharacterAlignment {
  characters: string[];
  character_start_times_seconds?: number[];
  character_end_times_seconds: number[];
}

/** Return text only through the last complete word whose aligned audio has played. */
export function revealAlignedWords(
  text: string,
  alignment: CharacterAlignment | null | undefined,
  currentTimeSeconds: number,
): string {
  if (!alignment || alignment.characters.join("") !== text) return "";
  const { characters, character_end_times_seconds: endTimes } = alignment;
  if (endTimes.length !== characters.length || !Number.isFinite(currentTimeSeconds)) return "";

  let visibleEnd = 0;
  let index = 0;
  while (index < characters.length) {
    if (/\s/.test(characters[index])) {
      if (visibleEnd > 0) visibleEnd = index + 1;
      index += 1;
      continue;
    }

    let wordEnd = index;
    while (wordEnd + 1 < characters.length && !/\s/.test(characters[wordEnd + 1])) {
      wordEnd += 1;
    }
    const endTime = endTimes[wordEnd];
    if (!Number.isFinite(endTime) || currentTimeSeconds < endTime) break;
    visibleEnd = wordEnd + 1;
    index = wordEnd + 1;
  }
  return characters.slice(0, visibleEnd).join("");
}
