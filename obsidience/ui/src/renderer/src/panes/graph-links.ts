import type { GraphLink, GraphNavigationGroup } from "../lib/api";

/** Exact display identities shared by Article edges and Thinking Packet refs. */
export function articleDisplayAliases(
  nodes: ReadonlyArray<{ id: string; article_ref?: string; navigation_ref?: string }>,
): Map<string, string> {
  const aliases = new Map<string, string>();
  for (const node of nodes) {
    if (node.navigation_ref) aliases.set(node.id, node.navigation_ref);
    if (node.article_ref) aliases.set(node.article_ref, node.id);
  }
  return aliases;
}

/** Display endpoints only; the API's links remain authoritative. */
export function projectedArticleLinks(
  links: ReadonlyArray<GraphLink>,
  aliases: ReadonlyMap<string, string>,
): GraphLink[] {
  return links.map((link) => ({
    ...link,
    source: aliases.get(link.source) ?? link.source,
    target: aliases.get(link.target) ?? link.target,
  }));
}

/** Cloud membership comes from the API; only exact display aliases change here. */
export function graphArticleIds(
  group: Pick<GraphNavigationGroup, "article_refs"> | undefined,
  aliases: ReadonlyMap<string, string>,
): Set<string> {
  return new Set((group?.article_refs ?? []).map((ref) => aliases.get(ref) ?? ref));
}

/** One visible edge per pair, within this cloud and its applicable Agent scope. */
export function visibleArticleLinks(
  links: ReadonlyArray<GraphLink>,
  articleIds: ReadonlySet<string>,
  agentRef?: string,
  scopeRefs: ReadonlySet<string> = articleIds,
): GraphLink[] {
  const seen = new Set<string>();
  return links.filter((link) => {
    if (link.source === link.target || !articleIds.has(link.source) || !articleIds.has(link.target)
      || (agentRef && link.for_agent && link.for_agent !== agentRef)) return false;
    // Contextual ancestors can be local while a derived route selects a foreign
    // descendant. Evidence keeps physical refs, unlike rendered Skill aliases.
    if (agentRef && link.derived && link.via?.some((ref) => !scopeRefs.has(ref))) return false;
    const key = JSON.stringify([link.source, link.target].sort());
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** A rendered hierarchy edge already connects its Articles in either direction. */
export function withoutTaxonomyLinks(
  links: ReadonlyArray<GraphLink>,
  nodes: ReadonlyArray<{ id: string; parentId?: string | null }>,
): GraphLink[] {
  const pairs = new Set(nodes.filter((node) => node.parentId).map((node) =>
    JSON.stringify([node.id, node.parentId].sort())));
  return links.filter((link) => link.source !== link.target
    && !pairs.has(JSON.stringify([link.source, link.target].sort())));
}
