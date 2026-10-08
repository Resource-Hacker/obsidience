import type { KnowledgeForceNode, KnowledgeForceLink } from "@/components/themes/obsidience/knowledge-3d";
import type { ProviderGraph, ProviderNode } from "./provider-graph-scene";

export const CODE_STRUCTURE = new Set(["Project", "Branch", "Folder", "File", "Module", "Package"]);
export function codeNodeRadius(node: Pick<ProviderNode, "kind">): number {
  return node.kind === "Project" ? 6.6 : node.kind === "Branch" ? 5
    : node.kind === "Folder" ? 4.2 : CODE_STRUCTURE.has(node.kind) ? 3.2 : 2.2;
}

/** Layout-only ancestry over native identities. Calls/imports are never parents.
 * Exact file-path fallback groups incomplete index fragments without publishing
 * invented relationships. The provider's complete edges remain the display data. */
export function codeLayoutAncestry(data: ProviderGraph) {
  const members = data.nodes.slice().sort((a, b) => a.id.localeCompare(b.id));
  const byId = new Map(members.map(node => [node.id, node]));
  const root = members.find(node => data.code_root ? node.id === data.code_root : node.kind === "Project");
  const parents = new Map<string, string>();
  const candidates = new Map<string, {id: string; priority: number}[]>();
  for (const edge of data.edges) {
    const source = byId.get(edge.source), target = byId.get(edge.target);
    if (!source || !target || source === target || target === root) continue;
    let priority = Infinity;
    if (edge.kind === "HAS_BRANCH" && source.kind === "Project" && target.kind === "Branch"
      || edge.kind === "CONTAINS_FOLDER" && target.kind === "Folder"
      || edge.kind === "CONTAINS_FILE" && target.kind === "File") priority = 0;
    else if (edge.kind === "DEFINES_METHOD" && source.file === target.file) priority = 1;
    else if (edge.kind === "DEFINES" && source.kind === "File" && source.file === target.file) priority = 2;
    if (!Number.isFinite(priority)) continue;
    const entries = candidates.get(target.id) || [];
    entries.push({id: source.id, priority}); candidates.set(target.id, entries);
  }
  const files = new Map(members.filter(node => node.kind === "File" && node.file).map(node => [node.file!, node.id]));
  const folders = new Map(members.filter(node => node.kind === "Folder" && node.file).map(node => [node.file!, node.id]));
  for (const node of members) {
    if (node === root) continue;
    const native = candidates.get(node.id)?.sort((a, b) => a.priority - b.priority || a.id.localeCompare(b.id))[0]?.id;
    const pathParent = node.kind === "File" || node.kind === "Folder"
      ? folders.get((node.file || "").split("/").slice(0, -1).join("/")) : files.get(node.file || "");
    const parent = native || pathParent || root?.id;
    if (parent && parent !== node.id) parents.set(node.id, parent);
  }
  // A derived index may contain cycles. Break only private placement ancestry;
  // do not remove or rewrite the provider's original edges.
  const depths = new Map<string, number>(root ? [[root.id, 0]] : []);
  for (const node of members) {
    const path: string[] = [], seen = new Set<string>();
    let id: string | undefined = node.id;
    while (id && !depths.has(id)) {
      if (seen.has(id)) {
        if (root) parents.set(path[path.length - 1], root.id);
        else parents.delete(path[path.length - 1]);
        id = root?.id; break;
      }
      seen.add(id); path.push(id); id = parents.get(id);
    }
    let depth = id ? depths.get(id)! : 0;
    for (const child of path.reverse()) depths.set(child, ++depth);
  }
  return {members, root, parents, depths};
}

export function codeSphericalHierarchy(data: ProviderGraph) {
  const {members, root, parents, depths} = codeLayoutAncestry(data);
  const nodes: KnowledgeForceNode[] = members.map(node => ({
    id: node.id, parentId: parents.get(node.id), depth: depths.get(node.id),
    role: node === root ? "root" : "code", radius: node === root ? 6.6 : codeNodeRadius(node),
  }));
  // Dense call/reference fans remain visible native links, not containment
  // forces: they must not collapse unrelated code branches onto one bearing.
  const links: KnowledgeForceLink[] = [...parents].map(([child, parent]) => ({
    source: child < parent ? child : parent, target: child < parent ? parent : child, taxonomy: true,
  }));
  links.sort((a, b) => a.source.localeCompare(b.source) || a.target.localeCompare(b.target));
  return {nodes, links, parents};
}

/** A file lens over native nodes/edges, not a second graph or synthetic calls.
 * File-level Module wrappers share the file orb; actual symbols remain distinct.
 * Bound only the one-hop external context. */
export function codeFileGraph(data: ProviderGraph, fileId: string): ProviderGraph | null {
  const file = data.nodes.find(node => node.id === fileId && node.kind === "File");
  if (!file?.file) return null;
  const members = new Set(data.nodes.filter(node => node.file === file.file).map(node => node.id));
  const wrappers = data.nodes.filter(node => node.kind === "Module" && node.file === file.file && node.name === file.file);
  const folded = new Set(wrappers.map(node => node.id));
  const displayId = (id: string) => folded.has(id) ? file.id : id;
  const candidates = new Map<string, number>();
  const relations = new Set(["CALLS", "IMPORTS", "USAGE", "INHERITS", "IMPLEMENTS", "CALL_REFERENCE"]);
  for (const edge of data.edges) {
    if (!relations.has(edge.kind) || members.has(edge.source) === members.has(edge.target)) continue;
    const id = members.has(edge.source) ? edge.target : edge.source;
    candidates.set(id, (candidates.get(id) || 0) + 1);
  }
  const external = new Set([...candidates].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 16).map(([id]) => id));
  const nodes = data.nodes.filter(node => !folded.has(node.id) && (members.has(node.id) || external.has(node.id)))
    .map(node => ({...node, external: external.has(node.id), aliases: node.id === file.id
      ? [...(node.aliases || []), ...wrappers.flatMap(wrapper => [wrapper.id, ...(wrapper.qualified_name ? ["qn:" + wrapper.qualified_name] : [])])]
      : node.aliases}));
  const ids = new Set(nodes.map(node => node.id));
  const seen = new Set<string>();
  // Folding is presentation-only. Preserve each native relationship's kind
  // and connection through the file representative, omitting self/duplicate
  // display links. The full provider snapshot keeps the original identities.
  const edges = data.edges.flatMap(edge => {
    const source = displayId(edge.source), target = displayId(edge.target);
    if (source === target || !ids.has(source) || !ids.has(target)
      || !(members.has(edge.source) && members.has(edge.target) || relations.has(edge.kind)
        && (members.has(edge.source) || members.has(edge.target)))) return [];
    const key = `${source}|${target}|${edge.kind}`;
    if (seen.has(key)) return [];
    seen.add(key); return [{...edge, source, target}];
  });
  return {...data, code_root: file.id, code_file: file.file, external_count: candidates.size,
    nodes, edges};
}
