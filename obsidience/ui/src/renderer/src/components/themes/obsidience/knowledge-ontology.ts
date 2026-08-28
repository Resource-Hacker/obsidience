/** Minimal presentation vocabulary for the Obsidience graph renderer.
 *
 * Semantic truth comes from the live vault graph. This module deliberately
 * contains no copied claim catalog, fixed article assignments, trust rules,
 * checkout policy, or runtime ontology.
 */

export type KnowledgeHierarchyRole =
  | "root"
  | "section"
  | "entity"
  | "claim"
  | "temporary";

export function isKnowledgeLeafRole(
  role: KnowledgeHierarchyRole | undefined,
): role is "claim" | "temporary" {
  return role === "claim" || role === "temporary";
}
