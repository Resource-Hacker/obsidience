/** Graph node and edge shapes shared by the knowledge layout. */
import { z } from "zod";

export const KNOWLEDGE_RELATIONSHIP_TYPES = [
  "extends",
  "implements",
  "contradicts",
  "derived_from",
  "uses",
  "replaces",
  "related_to",
  "runs_on",
  "part_of",
  "depends_on",
  "mitigates",
  "configures",
  "connected_to",
  "governs",
  "affects",
] as const;

const identifierSchema = z
  .string()
  .trim()
  .min(1)
  .max(160)
  .regex(
    /^[A-Za-z0-9][A-Za-z0-9._:-]*$/,
    "Knowledge identifiers may contain only letters, numbers, dot, underscore, colon, and dash.",
  );
const displayTextSchema = (maximum: number) =>
  z
    .string()
    .trim()
    .min(1)
    .max(maximum)
    .refine((value) => !/\p{Cc}/u.test(value), "Display text cannot contain control characters.")
    .refine(
      (value) =>
        !/(?:^|[\s:=("'`[{])(?:\/(?!\/)\S+|~\/\S*|[A-Za-z]:\\\S*)/u.test(
          value,
        ),
      "Knowledge display text cannot contain local filesystem paths.",
    )
    .refine(
      (value) =>
        !/(?:-----BEGIN [^-]*PRIVATE KEY-----|\b(?:Bearer|Basic)\s+\S{8,}|\b(?:sk|hf|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}|\bhttps?:\/\/[^/\s:@]+:[^/\s@]+@|\b(?:authorization|api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|auth[-_ ]?token|password|passwd|passphrase|client[-_ ]?secret|secret|credential|cookie)\s*(?:=|:|\bis\b)|\b(?:path|source[-_ ]?(?:ref|path))\s*(?:=|:)\s*\S+)/iu.test(
          value,
        ),
      "Knowledge display text cannot contain credential material.",
    );

const nonnegativeIntegerSchema = z
  .number()
  .int()
  .nonnegative()
  .max(Number.MAX_SAFE_INTEGER);
export const knowledgeRelationshipTypeSchema = z.enum(
  KNOWLEDGE_RELATIONSHIP_TYPES,
);
export const knowledgeNodeSchema = z
  .object({
    id: identifierSchema,
    kind: z.enum([
      "note",
      "fact",
      "preference",
      "decision",
      "procedure",
      "concept",
      "event",
      "source",
      "task",
    ]),
    lifecycle: z.enum([
      "draft",
      "reviewed",
      "verified",
      "disputed",
      "archived",
    ]),
    tier: z.enum(["hot", "warm", "cold"]),
    confidence: z.number().finite().min(0).max(1),
    degree: nonnegativeIntegerSchema,
    label: displayTextSchema(240).optional(),
    summary: displayTextSchema(600).optional(),
    // Explicit authority-attested claim tags (bounded); never derived or inferred.
    tags: z.array(z.string().min(1).max(64)).max(8).optional(),
  })
  .strict();

export const knowledgeEdgeSchema = z
  .object({
    id: identifierSchema,
    source: identifierSchema,
    target: identifierSchema,
    type: knowledgeRelationshipTypeSchema,
  })
  .strict();

export type KnowledgeNode = z.infer<typeof knowledgeNodeSchema>;
export type KnowledgeEdge = z.infer<typeof knowledgeEdgeSchema>;
