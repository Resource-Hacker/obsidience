/** Project backend-resolved permission onto the same visible Article IDs.
 * Do not infer inheritance here: explicit child opt-outs and capability
 * boundaries belong to the canonical policy, not to the layout. */
export function projectedAutoCuratedRefs(
  refs: readonly string[],
  articles: ReadonlyArray<{ id: string; navigation_ref?: string }>,
  subjects: ReadonlyArray<{ id: string; article_ref?: string }>,
): Set<string> {
  const result = new Set(refs);
  for (const article of articles) {
    if (article.navigation_ref && result.has(article.id)) result.add(article.navigation_ref);
  }
  for (const subject of subjects) {
    if (subject.article_ref && result.has(subject.article_ref)) result.add(subject.id);
  }
  return result;
}
