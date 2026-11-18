/** Remove what a heading detector picks up from long books but readers never want in a table of contents. */
const DOT_LEADER = /(\.\s*){3,}\d*\s*$/;
const TRAILING_NUMBER = /^(.*\S)\s+\d{1,4}$/;
const ONLY_NUMBER = /^[\divxlc.\s]+$/i;
const DATE_LINE = /^[A-Z][a-z]+ \d{1,2}, \d{4}$/;
const CONTENTS_PAGE_ENTRIES = 12;
const REPEATS_AS_RUNNING_HEADER = 3;
const LONGEST_HEADING = 72;

export function cleanOutline<T extends { title: string; page_index: number }>(items: T[]): T[] {
  const perPage = new Map<number, number>();
  const dotted = new Set<number>();
  const repeats = new Map<string, number>();
  for (const item of items) {
    const title = item.title.trim();
    perPage.set(item.page_index, (perPage.get(item.page_index) ?? 0) + 1);
    if (DOT_LEADER.test(title)) dotted.add(item.page_index);
    const key = (title.match(TRAILING_NUMBER)?.[1] ?? title).toLowerCase();
    repeats.set(key, (repeats.get(key) ?? 0) + 1);
  }
  const seen = new Set<string>();
  return items.filter((item) => {
    const title = item.title.trim();
    if (dotted.has(item.page_index) || (perPage.get(item.page_index) ?? 0) >= CONTENTS_PAGE_ENTRIES) return false;
    if (ONLY_NUMBER.test(title) || DATE_LINE.test(title)) return false;
    if (item.page_index > 0 && title.length > LONGEST_HEADING) return false; // footnotes and body lines
    const numbered = title.match(TRAILING_NUMBER)?.[1];
    const key = (numbered ?? title).toLowerCase();
    if ((repeats.get(key) ?? 0) < REPEATS_AS_RUNNING_HEADER) return true;
    // A running page header: keep the real heading once, never the "title + page number" copies.
    if (numbered || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
