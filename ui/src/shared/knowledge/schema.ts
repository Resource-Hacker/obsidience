import { z } from "zod";

export const KNOWLEDGE_SCHEMA_VERSION = 1 as const;
export const AMBIENT_NODE_LIMIT = 512;
export const AMBIENT_EDGE_LIMIT = 1_024;
export const INSPECT_NODE_LIMIT = AMBIENT_NODE_LIMIT;
export const INSPECT_EDGE_LIMIT = AMBIENT_EDGE_LIMIT;
export const TEMPORARY_OBSERVATION_LIMIT = 10;
export const REVIEW_CANDIDATE_LIMIT = 200;
export const REVIEW_RELATIONSHIP_CHANGE_LIMIT = 64;

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

export const KNOWLEDGE_REVIEW_PROPOSAL_KINDS = [
  "article",
  "relationships",
  "mixed",
  "archive",
  "revalidation",
] as const;

export const KNOWLEDGE_OPERATION_GROUP_KINDS = [
  "news_top10_replace",
  "news_top10_orphan_cleanup",
  "news_top10_publish",
  "news_top10_rotate",
  "managed_checkout_restore",
  "catalog_publish",
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
export const knowledgeIdentifierSchema = identifierSchema;

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

const utcTimestampSchema = z
  .string()
  .datetime({ offset: true })
  .regex(/Z$/, "Knowledge timestamps must be UTC.");
const nonnegativeIntegerSchema = z
  .number()
  .int()
  .nonnegative()
  .max(Number.MAX_SAFE_INTEGER);
export const knowledgeReviewTokenSchema = z
  .string()
  .regex(
    /^rv1:[0-9a-f]{64}$/u,
    "Knowledge review tokens must use the canonical rv1 SHA-256 format.",
  );
export const knowledgeGroupReviewTokenSchema = z
  .string()
  .regex(
    /^grv1:[0-9a-f]{64}$/u,
    "Knowledge group-review tokens must use the canonical grv1 SHA-256 format.",
  );

/** Per-agent knowledge routing: subagent names (delegation.agents) become
 *  URL path segments, ontology subject-id fragments, and storage-key parts,
 *  so they are validated against this fixed grammar BEFORE any
 *  interpolation. Absent agent = the main vault (legacy unprefixed routes). */
export const KNOWLEDGE_AGENT_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{0,31}$/;
export const knowledgeAgentIdSchema = z
  .string()
  .regex(
    KNOWLEDGE_AGENT_ID_PATTERN,
    "Knowledge agent ids are 1-32 chars of lowercase letters, digits, dot, underscore, and dash, starting alphanumeric.",
  );

export const knowledgeGraphModeSchema = z.enum(["ambient", "inspect"]);
export const knowledgeRelationshipTypeSchema = z.enum(
  KNOWLEDGE_RELATIONSHIP_TYPES,
);
export const knowledgeReviewProposalKindSchema = z.enum(
  KNOWLEDGE_REVIEW_PROPOSAL_KINDS,
);
export const knowledgeOperationGroupKindSchema = z.enum(
  KNOWLEDGE_OPERATION_GROUP_KINDS,
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
    // Explicit authority-attested claim tags (bounded). Reserved tags carry
    // a renderer subject assignment for dynamic articles (e.g. the hourly
    // news rotation) so new content never needs a renderer deploy. Never
    // derived or inferred — set at propose/revise in the authority.
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

export const knowledgeTemporaryObservationSchema = z
  .object({
    id: identifierSchema,
    text: displayTextSchema(200),
    observedAt: utcTimestampSchema,
    omitted: z.boolean(),
    // Display references to the active claims the transient entry is about.
    // They live inside the authority's entry row (expiry unlinks them
    // atomically) and are never attested relationships.
    relatedClaimIds: z.array(identifierSchema).max(3).optional(),
  })
  .strict();

export const knowledgeGraphSnapshotSchema = z
  .object({
    schemaVersion: z.literal(KNOWLEDGE_SCHEMA_VERSION),
    revision: nonnegativeIntegerSchema,
    mode: knowledgeGraphModeSchema,
    generatedAt: utcTimestampSchema,
    truncated: z.boolean(),
    nodes: z.array(knowledgeNodeSchema).max(INSPECT_NODE_LIMIT),
    edges: z.array(knowledgeEdgeSchema).max(INSPECT_EDGE_LIMIT),
    temporaryObservations: z
      .array(knowledgeTemporaryObservationSchema)
      .max(TEMPORARY_OBSERVATION_LIMIT),
  })
  .strict()
  .superRefine((snapshot, context) => {
    if (
      snapshot.mode === "ambient" &&
      snapshot.nodes.length > AMBIENT_NODE_LIMIT
    ) {
      context.addIssue({
        code: "too_big",
        maximum: AMBIENT_NODE_LIMIT,
        origin: "array",
        inclusive: true,
        path: ["nodes"],
        message: `Ambient graphs are limited to ${AMBIENT_NODE_LIMIT} nodes.`,
      });
    }
    if (
      snapshot.mode === "ambient" &&
      snapshot.edges.length > AMBIENT_EDGE_LIMIT
    ) {
      context.addIssue({
        code: "too_big",
        maximum: AMBIENT_EDGE_LIMIT,
        origin: "array",
        inclusive: true,
        path: ["edges"],
        message: `Ambient graphs are limited to ${AMBIENT_EDGE_LIMIT} edges.`,
      });
    }

    const nodeIds = new Set<string>();
    for (const node of snapshot.nodes) {
      if (nodeIds.has(node.id)) {
        context.addIssue({
          code: "custom",
          path: ["nodes"],
          message: "Knowledge node IDs must be unique.",
        });
      }
      nodeIds.add(node.id);
    }
    const edgeIds = new Set<string>();
    for (const edge of snapshot.edges) {
      if (edgeIds.has(edge.id)) {
        context.addIssue({
          code: "custom",
          path: ["edges"],
          message: "Knowledge edge IDs must be unique.",
        });
      }
      edgeIds.add(edge.id);
      if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
        context.addIssue({
          code: "custom",
          path: ["edges"],
          message: "Knowledge edges must reference nodes in the snapshot.",
        });
      }
    }
    const temporaryObservationIds = new Set<string>();
    for (const observation of snapshot.temporaryObservations) {
      if (temporaryObservationIds.has(observation.id)) {
        context.addIssue({
          code: "custom",
          path: ["temporaryObservations"],
          message: "Temporary-observation IDs must be unique.",
        });
      }
      temporaryObservationIds.add(observation.id);
    }
  });

export const knowledgeReviewRelationshipChangeSchema = z
  .object({
    change: z.enum(["added", "removed", "unchanged"]),
    source: z
      .object({
        id: identifierSchema,
        title: displayTextSchema(200).optional(),
      })
      .strict(),
    predicate: knowledgeRelationshipTypeSchema,
    target: z
      .object({
        ref: displayTextSchema(300),
        id: identifierSchema.optional(),
        title: displayTextSchema(200).optional(),
        resolution: z.enum(["resolved", "missing", "ambiguous", "self"]),
      })
      .strict(),
    context: displayTextSchema(500).optional(),
  })
  .strict()
  .superRefine((relationship, context) => {
    const { id, resolution } = relationship.target;
    if (resolution === "resolved" && !id) {
      context.addIssue({
        code: "custom",
        path: ["target", "id"],
        message: "Resolved knowledge relationship targets require an exact ID.",
      });
    }
    if (
      (resolution === "missing" || resolution === "ambiguous") &&
      id !== undefined
    ) {
      context.addIssue({
        code: "custom",
        path: ["target", "id"],
        message:
          "Unresolved knowledge relationship targets cannot claim an exact ID.",
      });
    }
    if (
      resolution === "self" &&
      (!id || id !== relationship.source.id)
    ) {
      context.addIssue({
        code: "custom",
        path: ["target", "id"],
        message:
          "Self-referential knowledge relationships must identify their source.",
      });
    }
  });

/** Reserved subject-assignment tag family: the tag value IS the renderer
 *  subject id (explicit operator/curator placement metadata — never derived
 *  from content). Bounded to the 64-char claim tag limit. */
export const knowledgeSubjectIdSchema = z
  .string()
  .regex(/^subject:[a-z0-9][a-z0-9:._-]{0,55}$/);

export const knowledgeCheckoutObjectKindSchema = z.enum([
  "Task",
  "Runbook",
  "Skill",
  "Tool",
]);
export const knowledgeCheckoutDesiredStateSchema = z.enum([
  "checked_out",
  "removed",
]);
export const knowledgeCheckoutSyncStatusSchema = z.enum([
  "pending",
  "synced",
  "conflict",
  "error",
]);
export const knowledgeCheckoutAssignmentIdSchema = z
  .string()
  .regex(/^checkout-[0-9a-f]{24}$/u);

const checkoutSubjectBranchByKind = {
  Task: "tasks",
  Runbook: "runbooks",
  Skill: "skills",
  Tool: "tools",
} as const;

function checkoutSubjectForAgent(
  agent: string,
  objectKind: keyof typeof checkoutSubjectBranchByKind,
): string {
  const branch = checkoutSubjectBranchByKind[objectKind];
  return agent === "executive"
    ? `subject:jarvis:knowledge:agent:${branch}`
    : `subject:agent:${agent}:agent:${branch}`;
}

export const knowledgeCheckoutAssignmentSchema = z
  .object({
    assignment_id: knowledgeCheckoutAssignmentIdSchema,
    agent: knowledgeAgentIdSchema,
    source_agent: z.literal("library"),
    source_claim_id: identifierSchema,
    target_claim_id: identifierSchema.nullable(),
    title: displayTextSchema(200),
    object_kind: knowledgeCheckoutObjectKindSchema,
    subject_id: knowledgeSubjectIdSchema,
    desired_state: knowledgeCheckoutDesiredStateSchema,
    sync_status: knowledgeCheckoutSyncStatusSchema,
    removed_at: utcTimestampSchema.nullable(),
    last_error: displayTextSchema(500).nullable(),
  })
  .strict()
  .superRefine((assignment, context) => {
    const expectedSubject = checkoutSubjectForAgent(
      assignment.agent,
      assignment.object_kind,
    );
    if (assignment.agent === "library") {
      context.addIssue({
        code: "custom",
        path: ["agent"],
        message: "Athenaeum cannot be a checkout target.",
      });
    }
    if (assignment.subject_id !== expectedSubject) {
      context.addIssue({
        code: "custom",
        path: ["subject_id"],
        message: "Checkout object kind and subject do not correlate.",
      });
    }
    if (assignment.desired_state === "checked_out") {
      if (assignment.removed_at !== null) {
        context.addIssue({
          code: "custom",
          path: ["removed_at"],
          message: "An active checkout cannot have a removal timestamp.",
        });
      }
      if (assignment.sync_status === "synced" && assignment.target_claim_id === null) {
        context.addIssue({
          code: "custom",
          path: ["target_claim_id"],
          message: "A synced checkout must identify its target claim.",
        });
      }
    } else if (assignment.removed_at === null) {
      context.addIssue({
        code: "custom",
        path: ["removed_at"],
        message: "A removed checkout must carry its removal timestamp.",
      });
    }
  });

export const knowledgeCheckoutsSnapshotSchema = z
  .object({
    assignments: z.array(knowledgeCheckoutAssignmentSchema).max(1_000),
  })
  .strict();

export const knowledgeCheckoutResultSchema = z
  .object({
    checked_out: z
      .object({
        agent: knowledgeAgentIdSchema,
        source_claim_id: identifierSchema,
        target_claim_id: identifierSchema,
        assignment_id: knowledgeCheckoutAssignmentIdSchema,
        status: z.enum(["created", "restored", "reconciled"]),
      })
      .strict(),
  })
  .strict()
  .superRefine((result, context) => {
    if (result.checked_out.agent === "library") {
      context.addIssue({
        code: "custom",
        path: ["checked_out", "agent"],
        message: "Athenaeum cannot be a checkout target.",
      });
    }
  });

export const knowledgeUncheckoutArchiveStatusSchema = z.enum([
  "not_assigned",
  "not_needed",
  "blocked_pending_review",
  "staged",
  "already_applied",
]);

export const knowledgeUncheckoutResultSchema = z
  .object({
    unassigned: z
      .object({
        agent: knowledgeAgentIdSchema,
        source_claim_id: identifierSchema,
        target_claim_id: identifierSchema.nullable(),
        assignment_id: knowledgeCheckoutAssignmentIdSchema.nullable(),
        desired_state: z.literal("removed"),
        sync_status: knowledgeCheckoutSyncStatusSchema,
        archive_status: knowledgeUncheckoutArchiveStatusSchema,
        removed_at: utcTimestampSchema.nullable(),
      })
      .strict(),
  })
  .strict()
  .superRefine((result, context) => {
    const value = result.unassigned;
    const issue = (path: string, message: string) =>
      context.addIssue({
        code: "custom",
        path: ["unassigned", path],
        message,
      });
    if (value.agent === "library") issue("agent", "Athenaeum cannot be a checkout target.");
    if (value.archive_status === "not_assigned") {
      if (
        value.assignment_id !== null ||
        value.target_claim_id !== null ||
        value.removed_at !== null ||
        value.sync_status !== "synced"
      ) {
        issue("archive_status", "A not-assigned result must have no durable assignment.");
      }
      return;
    }
    if (value.assignment_id === null || value.removed_at === null) {
      issue("assignment_id", "A durable unassignment must identify its assignment and removal time.");
    }
    if (value.archive_status === "not_needed") {
      if (value.target_claim_id !== null || value.sync_status !== "synced") {
        issue("archive_status", "A not-needed archive must have no target and be synced.");
      }
      return;
    }
    if (value.target_claim_id === null) {
      issue("target_claim_id", "An archive operation must identify its target claim.");
    }
    const expectedSync = {
      blocked_pending_review: "conflict",
      staged: "pending",
      already_applied: "synced",
    } as const;
    if (value.sync_status !== expectedSync[value.archive_status]) {
      issue("sync_status", "Unassignment archive status and sync status do not correlate.");
    }
  });

export const knowledgeReviewCandidateSchema = z
  .object({
    id: identifierSchema,
    /** The claim this operation targets (operation ids differ from claim
     *  ids for revisions), so the client can resolve effective placement. */
    claimId: identifierSchema.optional(),
    /** Tags the claim would carry after promotion (staged tags for content
     *  proposals, current tags for archives) — same bound as graph nodes. */
    tags: z.array(z.string().min(1).max(64)).max(8).optional(),
    reviewToken: knowledgeReviewTokenSchema,
    proposalKind: knowledgeReviewProposalKindSchema,
    title: displayTextSchema(200).optional(),
    summary: displayTextSchema(280),
    provenance: z.enum([
      "user_explicit",
      "tool_observed",
      "source_extracted",
      "agent_inferred",
      "imported",
    ]),
    /** Curator's ADVISORY placement recommendation (omitted when unset).
     *  Prefill-only: it never enters the review token, is never written as
     *  a tag, and never feeds placement resolution — the operator's promote
     *  decision carries the real subject. */
    suggestedSubjectId: knowledgeSubjectIdSchema.optional(),
    confidence: z.number().finite().min(0).max(1),
    conflicts: nonnegativeIntegerSchema,
    createdAt: utcTimestampSchema,
    allowedDecisions: z
      .array(z.enum(["promote", "reject"]))
      .min(1)
      .max(2),
    /** Atomic-operation membership. Grouped candidates remain visible for
     *  inspection but can never be decided independently. */
    groupId: identifierSchema.optional(),
    groupKind: knowledgeOperationGroupKindSchema.optional(),
    groupReviewToken: knowledgeGroupReviewTokenSchema.optional(),
    individualDecisionAllowed: z.literal(false).optional(),
    relationshipChanges: z
      .array(knowledgeReviewRelationshipChangeSchema)
      .max(REVIEW_RELATIONSHIP_CHANGE_LIMIT)
      .default([]),
  })
  .strict()
  .superRefine((candidate, context) => {
    const groupFields = [
      candidate.groupId,
      candidate.groupKind,
      candidate.groupReviewToken,
      candidate.individualDecisionAllowed,
    ];
    const present = groupFields.filter((value) => value !== undefined).length;
    if (present !== 0 && present !== groupFields.length) {
      context.addIssue({
        code: "custom",
        path: ["groupId"],
        message: "Grouped knowledge candidates require complete group metadata.",
      });
    }
    const rejectOnly =
      candidate.allowedDecisions.length === 1 &&
      candidate.allowedDecisions[0] === "reject";
    const promoteAndReject =
      candidate.allowedDecisions.length === 2 &&
      candidate.allowedDecisions[0] === "promote" &&
      candidate.allowedDecisions[1] === "reject";
    if (!rejectOnly && !promoteAndReject) {
      context.addIssue({
        code: "custom",
        path: ["allowedDecisions"],
        message: "Knowledge decisions must be promote-then-reject or reject-only.",
      });
    }
    if (
      rejectOnly !== (candidate.groupKind === "news_top10_orphan_cleanup")
    ) {
      context.addIssue({
        code: "custom",
        path: ["allowedDecisions"],
        message:
          "Only news orphan-cleanup group members may be reject-only.",
      });
    }
  });

export const knowledgeReviewGroupSchema = z
  .object({
    id: identifierSchema,
    kind: knowledgeOperationGroupKindSchema,
    status: z.enum(["pending", "applying"]),
    memberCount: nonnegativeIntegerSchema,
    createdAt: utcTimestampSchema,
    tags: z.array(z.string().min(1).max(64)).max(16),
    allowedDecisions: z
      .array(z.enum(["promote", "reject"]))
      .min(1)
      .max(2),
    groupReviewToken: knowledgeGroupReviewTokenSchema,
    members: z.array(knowledgeReviewCandidateSchema).min(1).max(REVIEW_CANDIDATE_LIMIT),
  })
  .strict()
  .superRefine((group, context) => {
    if (group.memberCount !== group.members.length) {
      context.addIssue({
        code: "custom",
        path: ["memberCount"],
        message: "Knowledge review group memberCount must match its members.",
      });
    }
    const rejectOnly =
      group.allowedDecisions.length === 1 &&
      group.allowedDecisions[0] === "reject";
    const promoteAndReject =
      group.allowedDecisions.length === 2 &&
      group.allowedDecisions[0] === "promote" &&
      group.allowedDecisions[1] === "reject";
    if (!rejectOnly && !promoteAndReject) {
      context.addIssue({
        code: "custom",
        path: ["allowedDecisions"],
        message: "Knowledge decisions must be promote-then-reject or reject-only.",
      });
    }
    if (rejectOnly !== (group.kind === "news_top10_orphan_cleanup")) {
      context.addIssue({
        code: "custom",
        path: ["allowedDecisions"],
        message: "Only news orphan-cleanup groups may be reject-only.",
      });
    }
    const memberIds = new Set<string>();
    for (const [index, member] of group.members.entries()) {
      if (memberIds.has(member.id)) {
        context.addIssue({
          code: "custom",
          path: ["members", index, "id"],
          message: "Knowledge review group member IDs must be unique.",
        });
      }
      memberIds.add(member.id);
      if (
        member.groupId !== group.id ||
        member.groupKind !== group.kind ||
        member.groupReviewToken !== group.groupReviewToken ||
        member.individualDecisionAllowed !== false
      ) {
        context.addIssue({
          code: "custom",
          path: ["members", index],
          message: "Knowledge review group members must carry exact group metadata.",
        });
      }
    }
  });

export const knowledgeReviewsSnapshotSchema = z
  .object({
    schemaVersion: z.literal(KNOWLEDGE_SCHEMA_VERSION),
    revision: nonnegativeIntegerSchema,
    candidates: z
      .array(knowledgeReviewCandidateSchema)
      .max(REVIEW_CANDIDATE_LIMIT),
    groups: z.array(knowledgeReviewGroupSchema).max(REVIEW_CANDIDATE_LIMIT),
  })
  .strict()
  .superRefine((snapshot, context) => {
    const ids = new Set<string>();
    const candidateById = new Map<string, (typeof snapshot.candidates)[number]>();
    for (const candidate of snapshot.candidates) {
      if (ids.has(candidate.id)) {
        context.addIssue({
          code: "custom",
          path: ["candidates"],
          message: "Knowledge review IDs must be unique.",
        });
      }
      ids.add(candidate.id);
      candidateById.set(candidate.id, candidate);
    }
    const groupIds = new Set<string>();
    const groupedCandidateIds = new Set<string>();
    for (const [groupIndex, group] of snapshot.groups.entries()) {
      if (groupIds.has(group.id)) {
        context.addIssue({
          code: "custom",
          path: ["groups", groupIndex, "id"],
          message: "Knowledge review group IDs must be unique.",
        });
      }
      groupIds.add(group.id);
      for (const [memberIndex, member] of group.members.entries()) {
        if (groupedCandidateIds.has(member.id)) {
          context.addIssue({
            code: "custom",
            path: ["groups", groupIndex, "members", memberIndex, "id"],
            message: "A knowledge candidate can belong to only one review group.",
          });
        }
        groupedCandidateIds.add(member.id);
        const topLevel = candidateById.get(member.id);
        if (!topLevel || JSON.stringify(topLevel) !== JSON.stringify(member)) {
          context.addIssue({
            code: "custom",
            path: ["groups", groupIndex, "members", memberIndex],
            message: "Knowledge group members must exactly duplicate top-level candidates.",
          });
        }
      }
    }
    for (const [candidateIndex, candidate] of snapshot.candidates.entries()) {
      if (
        (candidate.groupId !== undefined) !== groupedCandidateIds.has(candidate.id)
      ) {
        context.addIssue({
          code: "custom",
          path: ["candidates", candidateIndex, "groupId"],
          message: "Grouped knowledge candidates and group membership must be bijective.",
        });
      }
    }
  });

export const knowledgeReviewDecisionRequestSchema = z
  .object({
    id: identifierSchema,
    decision: z.enum(["promote", "reject"]),
    reviewToken: knowledgeReviewTokenSchema,
    /** Operator-chosen placement, applied at promotion as the claim's
     *  reserved subject tag. Promote-only. */
    subjectId: knowledgeSubjectIdSchema.optional(),
  })
  .strict()
  .superRefine((request, context) => {
    if (request.subjectId !== undefined && request.decision !== "promote") {
      context.addIssue({
        code: "custom",
        path: ["subjectId"],
        message: "A subject assignment is only valid with a promote decision.",
      });
    }
  });

export const knowledgeReviewDecisionResultSchema = z
  .object({
    schemaVersion: z.literal(KNOWLEDGE_SCHEMA_VERSION),
    id: identifierSchema,
    decision: z.enum(["promote", "reject"]),
    status: z.enum(["applied", "already_applied"]),
    revision: nonnegativeIntegerSchema,
  })
  .strict();

export const knowledgeReviewGroupDecisionRequestSchema = z
  .object({
    id: identifierSchema,
    decision: z.enum(["promote", "reject"]),
    groupReviewToken: knowledgeGroupReviewTokenSchema,
  })
  .strict();

export const knowledgeReviewGroupDecisionResultSchema = z
  .object({
    schemaVersion: z.literal(KNOWLEDGE_SCHEMA_VERSION),
    id: identifierSchema,
    decision: z.enum(["promote", "reject"]),
    status: z.enum(["applied", "already_applied"]),
    memberCount: nonnegativeIntegerSchema,
    revision: nonnegativeIntegerSchema,
  })
  .strict();

export const knowledgeSubjectAssignmentRequestSchema = z
  .object({
    id: identifierSchema,
    subjectId: knowledgeSubjectIdSchema,
  })
  .strict();

/** Curation can be assigned only to an acting agent. Athenaeum uses the
 *  otherwise-valid `library` vault id, but it is a passive bookshelf and
 *  must never become the WHO axis of a curation request. */
export const knowledgeCurationAssigneeSchema = knowledgeAgentIdSchema.refine(
  (agent) => agent !== "library",
  { message: "Athenaeum cannot be a curation assignee" },
);

export const knowledgeCurationRequestSchema = z
  .object({
    id: identifierSchema,
    /** The GATE axis (owner 2026-08-04: the two axes are independent —
     *  everything is curated; auto-curate only bypasses the owner review
     *  gate). Omitted = leave the gate untouched. */
    enabled: z.boolean().optional(),
    /** The WHO axis: which agent curates this node. "curator" is the
     *  default and clears the tag; omitted = leave the assignee
     *  untouched. */
    assignee: knowledgeCurationAssigneeSchema.optional(),
  })
  .strict()
  .refine(
    (request) => request.enabled !== undefined || request.assignee !== undefined,
    { message: "curation request needs enabled and/or assignee" },
  );

export const knowledgeCurationResultSchema = z
  .object({
    schemaVersion: z.literal(KNOWLEDGE_SCHEMA_VERSION),
    id: identifierSchema,
    enabled: z.boolean(),
    /** Effective WHO after local and inherited policy resolution. */
    agent: knowledgeCurationAssigneeSchema,
    status: z.enum(["applied", "already_applied"]),
    revision: nonnegativeIntegerSchema,
  })
  .strict();

/** The owner editor surface (Knowledge pane): full note bodies cross this
 *  authenticated loopback surface deliberately — unlike the ambient graph
 *  DTO, which stays metadata-only. Bounded, but not display-sanitized. */
export const knowledgeClaimDocumentSchema = z
  .object({
    schemaVersion: z.literal(KNOWLEDGE_SCHEMA_VERSION),
    id: identifierSchema,
    title: z.string().min(1).max(200),
    summary: z.string().max(280).default(""),
    content: z.string().max(150_000).default(""),
    tags: z.array(z.string().min(1).max(64)).max(32).default([]),
    lifecycle: z.enum(["draft", "reviewed", "verified", "disputed", "archived"]),
    revision: nonnegativeIntegerSchema,
    updatedAt: utcTimestampSchema.optional(),
  })
  .strict();

export const knowledgeClaimEditRequestSchema = z
  .object({
    id: identifierSchema,
    title: z.string().min(1).max(200).optional(),
    summary: z.string().max(280).optional(),
    content: z.string().max(150_000).optional(),
    expectedRevision: nonnegativeIntegerSchema.optional(),
  })
  .strict()
  .superRefine((request, context) => {
    if (
      request.title === undefined &&
      request.summary === undefined &&
      request.content === undefined
    ) {
      context.addIssue({
        code: "custom",
        path: ["content"],
        message: "A claim edit must change at least one field.",
      });
    }
  });

export const knowledgeClaimEditResultSchema = z
  .object({
    schemaVersion: z.literal(KNOWLEDGE_SCHEMA_VERSION),
    id: identifierSchema,
    status: z.enum(["applied", "already_applied"]),
    revision: nonnegativeIntegerSchema,
    claimRevision: nonnegativeIntegerSchema,
  })
  .strict();

export const knowledgeSubjectAssignmentResultSchema = z
  .object({
    schemaVersion: z.literal(KNOWLEDGE_SCHEMA_VERSION),
    id: identifierSchema,
    subjectId: knowledgeSubjectIdSchema,
    status: z.enum(["applied", "already_applied"]),
    revision: nonnegativeIntegerSchema,
  })
  .strict();

export const knowledgeActivitySchema = z
  .object({
    schemaVersion: z.literal(KNOWLEDGE_SCHEMA_VERSION),
    phase: z.enum([
      "query_started",
      "hits",
      "path",
      "query_completed",
      "write_staged",
      "write_promoted",
      "conflict",
    ]),
    queryId: identifierSchema.optional(),
    nodeIds: z.array(identifierSchema).max(AMBIENT_NODE_LIMIT).optional(),
    edgeIds: z.array(identifierSchema).max(AMBIENT_EDGE_LIMIT).optional(),
    revision: nonnegativeIntegerSchema.optional(),
    durationMs: z.number().finite().nonnegative().max(3_600_000).optional(),
  })
  .strict();

export type KnowledgeAgentId = z.infer<typeof knowledgeAgentIdSchema>;
export type KnowledgeCheckoutObjectKind = z.infer<
  typeof knowledgeCheckoutObjectKindSchema
>;
export type KnowledgeCheckoutAssignment = z.infer<
  typeof knowledgeCheckoutAssignmentSchema
>;
export type KnowledgeCheckoutResult = z.infer<
  typeof knowledgeCheckoutResultSchema
>;
export type KnowledgeCheckoutsSnapshot = z.infer<
  typeof knowledgeCheckoutsSnapshotSchema
>;
export type KnowledgeUncheckoutResult = z.infer<
  typeof knowledgeUncheckoutResultSchema
>;
export type KnowledgeGraphMode = z.infer<typeof knowledgeGraphModeSchema>;
export type KnowledgeRelationshipType = z.infer<
  typeof knowledgeRelationshipTypeSchema
>;
export type KnowledgeReviewProposalKind = z.infer<
  typeof knowledgeReviewProposalKindSchema
>;
export type KnowledgeOperationGroupKind = z.infer<
  typeof knowledgeOperationGroupKindSchema
>;
export type KnowledgeNode = z.infer<typeof knowledgeNodeSchema>;
export type KnowledgeEdge = z.infer<typeof knowledgeEdgeSchema>;
export type KnowledgeTemporaryObservation = z.infer<
  typeof knowledgeTemporaryObservationSchema
>;
export type KnowledgeGraphSnapshot = z.infer<typeof knowledgeGraphSnapshotSchema>;
export type KnowledgeReviewRelationshipChange = z.infer<
  typeof knowledgeReviewRelationshipChangeSchema
>;
export type KnowledgeReviewCandidate = z.infer<
  typeof knowledgeReviewCandidateSchema
>;
export type KnowledgeReviewGroup = z.infer<typeof knowledgeReviewGroupSchema>;
export type KnowledgeReviewsSnapshot = z.infer<
  typeof knowledgeReviewsSnapshotSchema
>;
export type KnowledgeReviewDecisionRequest = z.infer<
  typeof knowledgeReviewDecisionRequestSchema
>;
export type KnowledgeReviewDecisionResult = z.infer<
  typeof knowledgeReviewDecisionResultSchema
>;
export type KnowledgeReviewGroupDecisionRequest = z.infer<
  typeof knowledgeReviewGroupDecisionRequestSchema
>;
export type KnowledgeReviewGroupDecisionResult = z.infer<
  typeof knowledgeReviewGroupDecisionResultSchema
>;
export type KnowledgeSubjectAssignmentRequest = z.infer<
  typeof knowledgeSubjectAssignmentRequestSchema
>;
export type KnowledgeSubjectAssignmentResult = z.infer<
  typeof knowledgeSubjectAssignmentResultSchema
>;
export type KnowledgeClaimDocument = z.infer<
  typeof knowledgeClaimDocumentSchema
>;
export type KnowledgeClaimEditRequest = z.infer<
  typeof knowledgeClaimEditRequestSchema
>;
export type KnowledgeClaimEditResult = z.infer<
  typeof knowledgeClaimEditResultSchema
>;
export type KnowledgeCurationRequest = z.infer<
  typeof knowledgeCurationRequestSchema
>;
export type KnowledgeCurationResult = z.infer<
  typeof knowledgeCurationResultSchema
>;
export type KnowledgeActivity = z.infer<typeof knowledgeActivitySchema>;
