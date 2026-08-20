import type {
  KnowledgeEdge,
  KnowledgeGraphSnapshot,
  KnowledgeNode,
  KnowledgeTemporaryObservation,
} from "../../../../../shared/knowledge";

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

export interface KnowledgeHierarchyEntry {
  id: string;
  parentId: string | null;
  order: number;
  role: KnowledgeHierarchyRole;
}

export interface WorkstationKnowledgeProjection {
  snapshot: KnowledgeGraphSnapshot;
  hierarchy: KnowledgeHierarchyEntry[];
  subjectNodeIds: string[];
  subjectArticleBySubjectId: ReadonlyMap<string, KnowledgeNode>;
  subjectIdByArticleClaimId: ReadonlyMap<string, string>;
  taxonomyEdgeIds: ReadonlySet<string>;
  roleById: ReadonlyMap<string, KnowledgeHierarchyRole>;
  parentById: ReadonlyMap<string, string>;
  taxonomyEdgeByChildId: ReadonlyMap<string, string>;
  breadcrumbById: ReadonlyMap<string, readonly string[]>;
  temporaryObservationNodeIds: ReadonlySet<string>;
  /** Nodes visibly under agent auto-curation: claims carrying the reserved
   *  auto-curate tag, and subjects whose hub index article carries it. */
  autoCuratedNodeIds: ReadonlySet<string>;
  claimCount: number;
  temporaryObservationCount: number;
  attestedEdgeCount: number;
}

export interface WorkstationKnowledgeProjectionAdmission {
  projection: WorkstationKnowledgeProjection | null;
  unassignedClaimIds: string[];
}

export interface SubjectDefinition {
  id: string;
  label: string;
  summary: string;
  parentId: string | null;
  order: number;
  role: Exclude<KnowledgeHierarchyRole, "claim" | "temporary">;
}

export const WORKSTATION_SUBJECT_IDS = {
  brain: "subject:jarvis:agent-brain",
  workstation: "subject:workstation",
  hardware: "subject:workstation:hardware",
  displays: "subject:workstation:hardware:displays",
  samsung: "subject:workstation:hardware:displays:samsung-g95sc",
  dp4: "subject:workstation:hardware:displays:dp-4",
  usbC: "subject:workstation:hardware:displays:usb-c",
  input: "subject:workstation:hardware:input",
  software: "subject:workstation:software",
  desktop: "subject:workstation:software:desktop",
  terminal: "subject:workstation:software:terminal",
  games: "subject:workstation:software:games",
  wow: "subject:workstation:software:games:wow",
  tft: "subject:workstation:software:games:tft",
  workstationObservations: "subject:workstation:observations",
  workstationIncidents: "subject:workstation:observations:incidents",
  agent: "subject:jarvis:knowledge:agent",
  agentPreferences: "subject:jarvis:knowledge:agent:preferences",
  agentArchitecture: "subject:jarvis:knowledge:agent:architecture",
  agentObservations: "subject:jarvis:knowledge:agent:observations",
  agentTemporaryObservations:
    "subject:jarvis:knowledge:agent:observations:temporary",
  news: "subject:workstation:knowledge:news",
  newsObservations: "subject:workstation:knowledge:news:observations",
  gameStrategy: "subject:workstation:knowledge:game-strategy",
  wowStrategy: "subject:workstation:knowledge:game-strategy:wow",
  tftStrategy: "subject:workstation:knowledge:game-strategy:tft",
  gameObservations:
    "subject:workstation:knowledge:game-strategy:observations",
  projects: "subject:workstation:knowledge:projects",
  codingContext: "subject:workstation:knowledge:projects:coding-context",
  projectObservations:
    "subject:workstation:knowledge:projects:observations",
  personal: "subject:workstation:knowledge:personal",
  finance: "subject:workstation:knowledge:personal:finance",
  personalObservations:
    "subject:workstation:knowledge:personal:observations",
  newsTop10: "subject:workstation:knowledge:news:top10",
  websites: "subject:workstation:knowledge:websites",
  websitesObservations:
    "subject:workstation:knowledge:websites:observations",
  websitesReddit: "subject:workstation:knowledge:websites:reddit",
  agentTools: "subject:jarvis:knowledge:agent:tools",
  agentSkills: "subject:jarvis:knowledge:agent:skills",
  agentTasks: "subject:jarvis:knowledge:agent:tasks",
  agentRunbooks: "subject:jarvis:knowledge:agent:runbooks",
  agentSubagents: "subject:jarvis:knowledge:agent:subagents",
} as const;

const SUBJECTS: readonly SubjectDefinition[] = [
  {
    id: WORKSTATION_SUBJECT_IDS.brain,
    label: "JARVIS Agent Brain",
    summary:
      "The agent's self-model: reasoning, tools, memory authority, interface, and environments.",
    parentId: null,
    order: 0,
    role: "root",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.workstation,
    label: "ADMECH Workstation",
    summary:
      "The local CachyOS machine, its physical topology, software, and operating procedures.",
    parentId: WORKSTATION_SUBJECT_IDS.brain,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.hardware,
    label: "Hardware",
    summary: "Physical workstation devices and topology.",
    parentId: WORKSTATION_SUBJECT_IDS.workstation,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.displays,
    label: "Displays",
    summary: "Main and isolated display topology.",
    parentId: WORKSTATION_SUBJECT_IDS.hardware,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.samsung,
    label: "Samsung Odyssey OLED G9",
    summary: "Primary Samsung G95SC display navigation subject.",
    parentId: WORKSTATION_SUBJECT_IDS.displays,
    order: 0,
    role: "entity",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.dp4,
    label: "DP-4 Display",
    summary: "Isolated DP-4 workspace navigation subject.",
    parentId: WORKSTATION_SUBJECT_IDS.displays,
    order: 1,
    role: "entity",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.usbC,
    label: "USB-C Display",
    summary: "Isolated USB-C workspace navigation subject.",
    parentId: WORKSTATION_SUBJECT_IDS.displays,
    order: 2,
    role: "entity",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.input,
    label: "Input",
    summary: "Mouse, keyboard, bridge, and input-mapping navigation subject.",
    parentId: WORKSTATION_SUBJECT_IDS.hardware,
    order: 1,
    role: "entity",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.software,
    label: "Software",
    summary: "Operating-system, desktop, application, and game software.",
    parentId: WORKSTATION_SUBJECT_IDS.workstation,
    order: 1,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.desktop,
    label: "Desktop and Windowing",
    summary: "KWin, application launching, and desktop integration.",
    parentId: WORKSTATION_SUBJECT_IDS.software,
    order: 1,
    role: "entity",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.terminal,
    label: "Terminal and tmux",
    summary: "Terminal persistence and session continuity.",
    parentId: WORKSTATION_SUBJECT_IDS.software,
    order: 2,
    role: "entity",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.games,
    label: "Games",
    summary:
      "Game software on this machine: launch parameters, profiles, and launchers.",
    parentId: WORKSTATION_SUBJECT_IDS.software,
    order: 3,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.wow,
    label: "World of Warcraft",
    summary: "World of Warcraft workstation knowledge.",
    parentId: WORKSTATION_SUBJECT_IDS.games,
    order: 0,
    role: "entity",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.tft,
    label: "Teamfight Tactics",
    summary: "Teamfight Tactics workstation knowledge.",
    parentId: WORKSTATION_SUBJECT_IDS.games,
    order: 1,
    role: "entity",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.workstationObservations,
    label: "Workstation Observations",
    summary:
      "Distilled agent-authored observations about the workstation and its operation.",
    parentId: WORKSTATION_SUBJECT_IDS.workstation,
    order: 2,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.workstationIncidents,
    label: "Incident",
    summary:
      "Confirmed workstation incidents, their symptoms, root causes, and recovery state.",
    parentId: WORKSTATION_SUBJECT_IDS.workstationObservations,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agent,
    label: "Agent",
    summary:
      "JARVIS runtime, reasoning, tools, memory authority, interfaces, and environments.",
    parentId: WORKSTATION_SUBJECT_IDS.brain,
    order: 6,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agentPreferences,
    label: "Preferences",
    summary:
      "How the operator wants JARVIS to behave: interaction, collaboration, verification, and aesthetics.",
    parentId: WORKSTATION_SUBJECT_IDS.agent,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agentArchitecture,
    label: "Architecture",
    summary: "Durable agent architecture decisions and runtime structure.",
    parentId: WORKSTATION_SUBJECT_IDS.agent,
    order: 1,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agentObservations,
    label: "Agent Observations",
    summary:
      "Distilled agent-authored observations about JARVIS behavior, tools, and operation.",
    parentId: WORKSTATION_SUBJECT_IDS.agent,
    order: 7,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agentTemporaryObservations,
    label: "Temporary Observations",
    summary:
      "A bounded, transient working-context cache. These entries are unreviewed and are not durable wiki claims.",
    parentId: WORKSTATION_SUBJECT_IDS.agentObservations,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.news,
    label: "News and Research",
    summary: "Time-sensitive articles, sources, and current-event research.",
    parentId: WORKSTATION_SUBJECT_IDS.brain,
    order: 5,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.newsObservations,
    label: "News and Research Observations",
    summary:
      "Distilled agent-authored observations about current events, sources, and research.",
    parentId: WORKSTATION_SUBJECT_IDS.news,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.newsTop10,
    label: "Today's Top 10",
    summary:
      "The rotating hourly top-10 news digest: each story is a bounded summarized article that arrives with the batch and falls off when superseded.",
    parentId: WORKSTATION_SUBJECT_IDS.news,
    order: 2,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.gameStrategy,
    label: "Games",
    summary:
      "In-game knowledge: characters, stats, gear, builds, encounters, and patch strategy.",
    parentId: WORKSTATION_SUBJECT_IDS.brain,
    order: 4,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.wowStrategy,
    label: "WoW",
    summary:
      "World of Warcraft character, gear, account, encounters, builds, and rotations.",
    parentId: WORKSTATION_SUBJECT_IDS.gameStrategy,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.tftStrategy,
    label: "TFT",
    summary:
      "Teamfight Tactics account, compositions, economy, positioning, and patch notes.",
    parentId: WORKSTATION_SUBJECT_IDS.gameStrategy,
    order: 1,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.gameObservations,
    label: "Game Observations",
    summary:
      "Distilled agent-authored observations about games, characters, encounters, and strategy.",
    parentId: WORKSTATION_SUBJECT_IDS.gameStrategy,
    order: 2,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.projects,
    label: "Projects",
    summary: "Durable project architecture, decisions, and implementation context.",
    parentId: WORKSTATION_SUBJECT_IDS.brain,
    order: 3,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.codingContext,
    label: "Coding Context",
    summary:
      "Project documentation, code research, interfaces, and implementation decisions.",
    parentId: WORKSTATION_SUBJECT_IDS.projects,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.projectObservations,
    label: "Project Observations",
    summary:
      "Distilled agent-authored observations about projects and implementation work.",
    parentId: WORKSTATION_SUBJECT_IDS.projects,
    order: 1,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.personal,
    label: "Personal",
    summary:
      "Banking and finance context, medical, insurance, vehicle registration, and other credential-free personal records.",
    parentId: WORKSTATION_SUBJECT_IDS.brain,
    order: 2,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.finance,
    label: "Finance and Budgeting",
    summary:
      "Budget goals, categories, recurring obligations, and sanitized financial summaries.",
    parentId: WORKSTATION_SUBJECT_IDS.personal,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.personalObservations,
    label: "Personal Observations",
    summary:
      "Distilled agent-authored observations about personal context, kept separate from explicitly requested records.",
    parentId: WORKSTATION_SUBJECT_IDS.personal,
    order: 1,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.websites,
    label: "Websites",
    summary:
      "How specific websites work for agent interaction: site mechanics, URL schemas, automation-friendly surfaces, and the owner's context on each site.",
    parentId: WORKSTATION_SUBJECT_IDS.brain,
    order: 7,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.websitesReddit,
    label: "Reddit",
    summary:
      "Reddit's mechanics and automation surfaces plus the owner's Reddit context; every Reddit article lives beneath this site subject.",
    parentId: WORKSTATION_SUBJECT_IDS.websites,
    order: 0,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.websitesObservations,
    label: "Website Observations",
    summary:
      "Distilled agent-authored notes about website interaction: browser profile state, site-specific behavior the agent has learned, and automation lessons.",
    parentId: WORKSTATION_SUBJECT_IDS.websites,
    order: 1,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agentTools,
    label: "Tools",
    summary:
      "The agent's own tool surface: what each tool is for, its operational failure modes, and recovery.",
    parentId: WORKSTATION_SUBJECT_IDS.agent,
    order: 2,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agentSkills,
    label: "Skills",
    summary:
      "Reusable techniques JARVIS has checked out for applying its tool surface safely and effectively.",
    parentId: WORKSTATION_SUBJECT_IDS.agent,
    order: 3,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agentTasks,
    label: "Tasks",
    summary:
      "Bounded task definitions JARVIS can execute through its own authority and tools.",
    parentId: WORKSTATION_SUBJECT_IDS.agent,
    order: 4,
    role: "section",
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agentRunbooks,
    label: "Runbooks",
    summary:
      "Operational procedures JARVIS follows for recurring or specialized work.",
    parentId: WORKSTATION_SUBJECT_IDS.agent,
    order: 5,
    role: "section",
  },
  {
    // One article per named subagent (owner 2026-08-03); on-creation
    // automation is future work — articles are seeded manually today.
    id: WORKSTATION_SUBJECT_IDS.agentSubagents,
    label: "Subagents",
    summary:
      "The named subagents filling the workstation's roles: who they are, what they do, and how the executive works with them.",
    parentId: WORKSTATION_SUBJECT_IDS.agent,
    order: 6,
    role: "section",
  },
];

const ASSIGNABLE_SUBJECT_IDS = new Set(
  SUBJECTS.filter(
    (subject) => subject.id !== WORKSTATION_SUBJECT_IDS.brain,
  ).map((subject) => subject.id),
);

const SUBJECT_ARTICLE_CLAIM_ID_BY_SUBJECT_ID: ReadonlyMap<string, string> =
  new Map([
    // RAPTOR index hubs: each subject node absorbs its own index article
    // (distilled overview + annotated child index). Hubs are edge-free by
    // contract so absorption is never declined. The former agent/identity
    // absorption is retired; the identity article is an ordinary leaf.
    [WORKSTATION_SUBJECT_IDS.brain, "e1b55d8c-331f-49c4-afef-d60a346520cf"],
    [WORKSTATION_SUBJECT_IDS.workstation, "3c6d7c9c-7e86-4c02-abc9-573186e471c4"],
    [WORKSTATION_SUBJECT_IDS.agent, "6ce54afc-dcfc-4a7c-82a0-c68ec5428d46"],
    [WORKSTATION_SUBJECT_IDS.agentTools, "672b20af-0d70-4ad5-8690-709c52b0ae51"],
    [WORKSTATION_SUBJECT_IDS.gameStrategy, "aef7f70b-dba4-4518-8e6d-aed209a02ef7"],
    [WORKSTATION_SUBJECT_IDS.news, "3c04177b-7e0d-4050-aca1-f75b5dbfb7c1"],
    [WORKSTATION_SUBJECT_IDS.projects, "a442ba37-4c12-4231-b96d-23057442eb63"],
    [WORKSTATION_SUBJECT_IDS.personal, "0e330157-0259-451c-9f6a-22cca7420dcf"],
    [WORKSTATION_SUBJECT_IDS.websites, "92494c33-d3e2-4490-aded-919c145566b2"],
  ]);

/**
 * Presentation membership is intentionally explicit and keyed by the
 * authority's stable claim IDs. It does not masquerade as an attested
 * `part_of` relationship, and it never feeds back into Hermes retrieval.
 */
const PRIMARY_SUBJECT_BY_CLAIM_ID: Readonly<Record<string, string>> = {
  "3e5e73cc-2f4f-4a2f-b478-767b1e71feb2":
    WORKSTATION_SUBJECT_IDS.wow,
  "f7a51a37-a83f-485f-ae8f-0e4c17f24d2a":
    WORKSTATION_SUBJECT_IDS.wow,
  "bfa0e497-7b16-4ee7-9908-a4a464b50297":
    WORKSTATION_SUBJECT_IDS.agentPreferences,
  "754fe29f-34b1-4b9b-a790-3dc7d5bcf0fe":
    WORKSTATION_SUBJECT_IDS.agentObservations,
  "7c2c9678-dac4-4ffb-b6da-710010b54d9c":
    WORKSTATION_SUBJECT_IDS.agentObservations,
  "49b3e09e-74ba-4523-9d07-72bdf9937d0f":
    WORKSTATION_SUBJECT_IDS.agentObservations,
  "4f0babed-2020-40eb-b26c-5931a73f9616":
    WORKSTATION_SUBJECT_IDS.agentObservations,
  "bdf862cb-d01b-49a3-978c-2a1923ff826b":
    WORKSTATION_SUBJECT_IDS.agentPreferences,
  "595700d3-f574-4f1c-ba66-6f631edfdc02":
    WORKSTATION_SUBJECT_IDS.games,
  "463cc7c8-d994-4909-ba26-08f10190dcdf":
    WORKSTATION_SUBJECT_IDS.agentPreferences,
  "f2cc8948-7d78-4208-bfd3-b8ce25f7883f":
    WORKSTATION_SUBJECT_IDS.wowStrategy,
  "b7bed8fd-2f86-4217-8064-5a5c333d5832":
    WORKSTATION_SUBJECT_IDS.agentPreferences,
  "7d8e77cc-3acb-44ea-8afe-050367d8042f":
    WORKSTATION_SUBJECT_IDS.agentArchitecture,
  "b877a224-bcaa-49f4-87e5-4beef4bc2903":
    WORKSTATION_SUBJECT_IDS.agentPreferences,
  "dd0825ab-d60a-408a-bdd7-e171569efe26":
    WORKSTATION_SUBJECT_IDS.agentPreferences,
  "c9a9f55c-d1a9-412f-b0a7-96679a3d6ffc":
    WORKSTATION_SUBJECT_IDS.agentPreferences,
  "f26441df-73c3-4431-9050-10742e3c33db":
    WORKSTATION_SUBJECT_IDS.agent,
  "f06bf516-240b-4a5b-904f-645c045ba10f":
    WORKSTATION_SUBJECT_IDS.agent,
  "e868685d-1f51-4847-9f9f-1f7303cc8582":
    WORKSTATION_SUBJECT_IDS.terminal,
  "c6db7c16-1580-464e-8cba-0b75c6957718": WORKSTATION_SUBJECT_IDS.dp4,
  "bcacd849-c6df-4d05-bbbf-7971c8f7b793":
    WORKSTATION_SUBJECT_IDS.workstationIncidents,
  "c05b5d51-d40f-46c3-9c54-a23ac5effcfd":
    WORKSTATION_SUBJECT_IDS.workstationObservations,
  "4a4412b7-c916-4f88-8fe6-abe80bd5415f":
    WORKSTATION_SUBJECT_IDS.agentPreferences,
  "a8755cfa-a881-4457-9473-4b9316a483f8":
    WORKSTATION_SUBJECT_IDS.displays,
  "91d81e37-d488-480a-8844-1de23a968b07":
    WORKSTATION_SUBJECT_IDS.agent,
  "88c574be-b502-4c6d-a04a-37ce8cf3831b":
    WORKSTATION_SUBJECT_IDS.agent,
  "8657dcf7-9419-4a7d-92fd-1254d780082b":
    WORKSTATION_SUBJECT_IDS.agent,
  "7d8c9b1d-20ac-481d-9cd9-5f8129bba1f5": WORKSTATION_SUBJECT_IDS.usbC,
  "5579dfc0-9397-4e1b-afe1-45acaa34ee38": WORKSTATION_SUBJECT_IDS.input,
  "3e5726a8-8528-404f-9658-bf95c8c1b501": WORKSTATION_SUBJECT_IDS.tft,
  "22f9e5a4-8028-4f1c-84ac-94e13774923f":
    WORKSTATION_SUBJECT_IDS.desktop,
  "339f2788-6971-43ee-ace1-0ddfdc723a25":
    WORKSTATION_SUBJECT_IDS.desktop,
  "96ccfd7b-0767-4bd6-8e25-4c6aa48419b6":
    WORKSTATION_SUBJECT_IDS.samsung,
  "9c818559-0ea5-46c9-bf80-9bf1caec17bf":
    WORKSTATION_SUBJECT_IDS.agentArchitecture,
  "3745813a-1ea6-4b71-b800-d749b052d116":
    WORKSTATION_SUBJECT_IDS.agentArchitecture,
  "9270e321-36f5-44fd-b056-abf32539a481": WORKSTATION_SUBJECT_IDS.wow,
  "e6b9594b-a353-4bd5-a5ba-a50e16415e50": WORKSTATION_SUBJECT_IDS.wow,

  "e1b55d8c-331f-49c4-afef-d60a346520cf": WORKSTATION_SUBJECT_IDS.brain,
  "3c6d7c9c-7e86-4c02-abc9-573186e471c4": WORKSTATION_SUBJECT_IDS.workstation,
  "6ce54afc-dcfc-4a7c-82a0-c68ec5428d46": WORKSTATION_SUBJECT_IDS.agent,
  "672b20af-0d70-4ad5-8690-709c52b0ae51": WORKSTATION_SUBJECT_IDS.agentTools,
  "aef7f70b-dba4-4518-8e6d-aed209a02ef7": WORKSTATION_SUBJECT_IDS.gameStrategy,
  "3c04177b-7e0d-4050-aca1-f75b5dbfb7c1": WORKSTATION_SUBJECT_IDS.news,
  "a442ba37-4c12-4231-b96d-23057442eb63": WORKSTATION_SUBJECT_IDS.projects,
  "0e330157-0259-451c-9f6a-22cca7420dcf": WORKSTATION_SUBJECT_IDS.personal,
  "92494c33-d3e2-4490-aded-919c145566b2": WORKSTATION_SUBJECT_IDS.websites,
  "e87586e6-246b-4c44-83ec-a7a350c97707": WORKSTATION_SUBJECT_IDS.agentTools,
  "242d5605-8fce-48b5-89fe-d22c4e862c34": WORKSTATION_SUBJECT_IDS.agentTools,
  "d1fcb0ee-2b47-417a-80e5-4997acb853fc": WORKSTATION_SUBJECT_IDS.agentTools,
  "390eec2d-7206-4b99-8676-404a799f203a": WORKSTATION_SUBJECT_IDS.agentTools,
  "1ed0ad3e-69bd-4a90-b6e7-1dd3d0ff3a12": WORKSTATION_SUBJECT_IDS.agentTools,
  "14cafaee-c577-4149-859d-0cedb101634f": WORKSTATION_SUBJECT_IDS.agentTools,
  "79da55dd-7700-476c-beca-a54e8d17e3e3": WORKSTATION_SUBJECT_IDS.agentTools,
  "cd8259a5-9202-4ef3-9c4a-e3c921733d66": WORKSTATION_SUBJECT_IDS.agentTools,
  "31611a5b-c794-4ce5-8fd5-5d463c202567": WORKSTATION_SUBJECT_IDS.agentTools,
  "71eb9f8e-d8a0-442c-9db3-158841c311d1": WORKSTATION_SUBJECT_IDS.agentTools,
  "0ca90ee1-3f87-4dad-a1a6-e3f6caee655d": WORKSTATION_SUBJECT_IDS.agentTools,
  "4c1f0023-f38c-4bb3-b733-0601adb07c95": WORKSTATION_SUBJECT_IDS.agentTools,
  "5d4da873-2856-4e16-967f-b57019cb51c5":
    WORKSTATION_SUBJECT_IDS.websitesReddit,
};

export function primaryWorkstationSubjectForClaim(
  claimId: string,
): string | null {
  return PRIMARY_SUBJECT_BY_CLAIM_ID[claimId] ?? null;
}

/**
 * Reserved authority tags that carry an explicit renderer subject
 * assignment. This is NOT classification: the tag is deliberate claim
 * metadata set at propose/revise time in the authority (like the hand
 * -maintained ID map, but attached to the claim itself), so dynamic
 * articles — the hourly news rotation — never need a renderer deploy.
 * Titles, summaries, kinds, keywords, provenance, and generic
 * relationships still never assign anything.
 */
const SUBJECT_BY_RESERVED_TAG: ReadonlyMap<string, string> = new Map([
  ["news-top10", WORKSTATION_SUBJECT_IDS.newsTop10],
  // The agent's own observation lane: each branch's Observations child
  // accepts distilled agent-authored notes placed by tag, with no renderer
  // deploy and no owner review (the curator promotes the observation lane
  // itself — owner-directed 2026-08-01).
  ["obs-workstation", WORKSTATION_SUBJECT_IDS.workstationObservations],
  ["obs-agent", WORKSTATION_SUBJECT_IDS.agentObservations],
  ["obs-news", WORKSTATION_SUBJECT_IDS.newsObservations],
  ["obs-games", WORKSTATION_SUBJECT_IDS.gameObservations],
  ["obs-projects", WORKSTATION_SUBJECT_IDS.projectObservations],
  ["obs-personal", WORKSTATION_SUBJECT_IDS.personalObservations],
  ["obs-websites", WORKSTATION_SUBJECT_IDS.websitesObservations],
  // Tool articles reconcile automatically against the live tool surface;
  // the tag places new ones under Agent > Tools without a deploy.
  ["agent-tool", WORKSTATION_SUBJECT_IDS.agentTools],
]);

/** Subjects the subject-tag family may target. The Brain is structural, and
 *  the authority-owned lanes — the 24-hour transient cache and the rotating
 *  news lane — accept content only through their own reserved lane tags:
 *  a durable claim parked there by tag would masquerade as lane content
 *  (and, unlike real temporary observations, persist into the fallback
 *  cache). Both the resolver and the picker use this one set. */
const SUBJECT_TAG_ASSIGNABLE_IDS: ReadonlySet<string> = new Set(
  [...ASSIGNABLE_SUBJECT_IDS].filter(
    (subjectId) =>
      subjectId !== WORKSTATION_SUBJECT_IDS.agentTemporaryObservations &&
      subjectId !== WORKSTATION_SUBJECT_IDS.newsTop10,
  ),
);

/** The agent's own no-input lanes are auto-curated BY DESIGN (owner
 *  2026-08-03): every Observations subject, the transient cache, and
 *  the rotating Today's Top 10 — the curator already creates, edits,
 *  and links their content without review, so their rings carry the
 *  comet permanently. */
const MAIN_AUTO_CURATED_SUBJECT_IDS: ReadonlySet<string> = new Set([
  WORKSTATION_SUBJECT_IDS.workstationObservations,
  WORKSTATION_SUBJECT_IDS.agentObservations,
  WORKSTATION_SUBJECT_IDS.agentTemporaryObservations,
  WORKSTATION_SUBJECT_IDS.newsObservations,
  WORKSTATION_SUBJECT_IDS.gameObservations,
  WORKSTATION_SUBJECT_IDS.projectObservations,
  WORKSTATION_SUBJECT_IDS.personalObservations,
  WORKSTATION_SUBJECT_IDS.websitesObservations,
  WORKSTATION_SUBJECT_IDS.newsTop10,
]);

/**
 * One presentation ontology per knowledge vault. The MAIN context wraps the
 * hand-authored workstation taxonomy verbatim; subagent vaults get a small
 * generic taxonomy from `agentKnowledgeOntologyContext`. Everything here is
 * presentation-only projection state — never trust, review, or retrieval
 * input — and each vault's context is self-contained so one agent's
 * admission failure can never affect another's projection.
 */
export interface KnowledgeOntologyContext {
  /** Presentation-only subject table; exactly one `role: "root"` entry. */
  subjects: readonly SubjectDefinition[];
  rootId: string;
  /** Subjects an accepted claim may resolve to (the root is never one). */
  assignableSubjectIds: ReadonlySet<string>;
  /** Subjects the reserved subject-tag family and the picker may target. */
  subjectTagAssignableIds: ReadonlySet<string>;
  /** Where synthetic temporary-observation leaves parent. */
  temporaryObservationsSubjectId: string;
  /** Lane subjects auto-curated by design (ring-marker seeds). */
  autoCuratedSubjectIds: ReadonlySet<string>;
  /** Resolve each subject's absorbed index-hub article against the
   *  snapshot's nodes: subject id → claim id (root included). Main uses
   *  the hand-maintained UUID map; agent contexts absorb by reserved
   *  tags so a freshly seeded vault never needs a renderer deploy. */
  subjectArticleClaimIds(
    nodes: readonly Pick<KnowledgeNode, "id" | "tags" | "lifecycle">[],
  ): ReadonlyMap<string, string>;
  /** Athenaeum's shelf indexes ARE the shelf nodes. Unlike ordinary agent
   *  vaults, a connected index may therefore still be absorbed: renderer
   *  projection remaps its meaningful edges onto the subject and represents
   *  redundant child-to-index membership through the taxonomy branch. */
  absorbConnectedSubjectArticles?: boolean;
  /** Explicit subject-level exceptions to the ordinary connected-index
   *  fail-safe. The main Agent > Tools index is itself the Tools node even
   *  when it gains meaningful relationships; those edges bind to the node. */
  alwaysAbsorbConnectedSubjectIds?: ReadonlySet<string>;
  /** Placement precedence for one node. Explicit metadata only — titles,
   *  summaries, kinds, keywords, and provenance never assign anything. */
  primarySubjectForNode(node: {
    id: string;
    tags?: readonly string[];
  }): string | null;
  /** Presentation label cleanup for a claim filed under a subject. */
  claimDisplayLabel(label: string, subjectId: string): string;
}

/** Whether a subject id is one the operator picker itself offers — the
 *  validation gate for the curator's ADVISORY `suggestedSubjectId` on
 *  review candidates. Fails closed exactly like the tag resolver: an
 *  unknown, Brain, or authority-lane suggestion is simply ignored. */
export function isAssignableWorkstationSubjectId(id: string): boolean {
  return SUBJECT_TAG_ASSIGNABLE_IDS.has(id);
}

export function primaryWorkstationSubjectForNodeIn(
  context: KnowledgeOntologyContext,
  node: {
    id: string;
    tags?: readonly string[];
  },
): string | null {
  return context.primarySubjectForNode(node);
}

export function primaryWorkstationSubjectForNode(node: {
  id: string;
  tags?: readonly string[];
}): string | null {
  return mainKnowledgeOntologyContext.primarySubjectForNode(node);
}

export const mainKnowledgeOntologyContext: KnowledgeOntologyContext = {
  subjects: SUBJECTS,
  rootId: WORKSTATION_SUBJECT_IDS.brain,
  assignableSubjectIds: ASSIGNABLE_SUBJECT_IDS,
  subjectTagAssignableIds: SUBJECT_TAG_ASSIGNABLE_IDS,
  temporaryObservationsSubjectId:
    WORKSTATION_SUBJECT_IDS.agentTemporaryObservations,
  autoCuratedSubjectIds: MAIN_AUTO_CURATED_SUBJECT_IDS,
  subjectArticleClaimIds(nodes) {
    // Keep the historical stable-ID table authoritative for its established
    // hubs, then admit owner-created index articles by the same explicit
    // `index-hub` + exact subject-tag contract used by agent vaults. This
    // lets every main-vault navigation node be its real article without
    // teaching the renderer newly generated claim IDs one deployment at a
    // time. A duplicate contender never displaces an established mapping;
    // otherwise the lowest accepted claim ID wins deterministically.
    const hubs = new Map(SUBJECT_ARTICLE_CLAIM_ID_BY_SUBJECT_ID);
    for (const node of nodes) {
      if (
        node.lifecycle === "draft" ||
        !(node.tags ?? []).includes(KNOWLEDGE_INDEX_HUB_TAG)
      ) {
        continue;
      }
      const subjectId = (node.tags ?? []).find((tag) =>
        ASSIGNABLE_SUBJECT_IDS.has(tag),
      );
      if (!subjectId || SUBJECT_ARTICLE_CLAIM_ID_BY_SUBJECT_ID.has(subjectId)) {
        continue;
      }
      const existing = hubs.get(subjectId);
      if (existing === undefined || node.id < existing) {
        hubs.set(subjectId, node.id);
      }
    }
    return hubs;
  },
  alwaysAbsorbConnectedSubjectIds: new Set([
    WORKSTATION_SUBJECT_IDS.agentTools,
    WORKSTATION_SUBJECT_IDS.agentSkills,
    WORKSTATION_SUBJECT_IDS.agentTasks,
    WORKSTATION_SUBJECT_IDS.agentRunbooks,
  ]),
  primarySubjectForNode(node) {
    // Index articles may represent authority-owned lane subjects that are
    // deliberately unavailable in the ordinary placement picker (for
    // example Today's Top 10 and Temporary Observations). The explicit
    // `index-hub` marker makes that subject tag index metadata rather than
    // an attempt to park an ordinary durable article in a reserved lane.
    if ((node.tags ?? []).includes(KNOWLEDGE_INDEX_HUB_TAG)) {
      const indexSubject = (node.tags ?? []).find((tag) =>
        ASSIGNABLE_SUBJECT_IDS.has(tag),
      );
      if (indexSubject) return indexSubject;
    }
    // The reserved subject-assignment tag family: the tag value IS the
    // subject id (explicit operator/curator placement set at promote/assign
    // time). It outranks the hand-maintained claim-id map so an operator can
    // move an article without a renderer deploy; an unknown or non-assignable
    // subject tag is ignored (fail closed to the needs-category badge), and
    // this is still not classification — titles/summaries/kinds never assign.
    for (const tag of node.tags ?? []) {
      if (tag.startsWith("subject:") && SUBJECT_TAG_ASSIGNABLE_IDS.has(tag)) {
        return tag;
      }
    }
    const mapped = PRIMARY_SUBJECT_BY_CLAIM_ID[node.id];
    if (mapped) return mapped;
    for (const tag of node.tags ?? []) {
      const subjectId = SUBJECT_BY_RESERVED_TAG.get(tag);
      if (subjectId) return subjectId;
    }
    return null;
  },
  claimDisplayLabel(label, subjectId) {
    let cleaned = label;
    if (
      subjectId === WORKSTATION_SUBJECT_IDS.workstationObservations ||
      subjectId === WORKSTATION_SUBJECT_IDS.workstationIncidents ||
      subjectId === WORKSTATION_SUBJECT_IDS.agentObservations
    ) {
      cleaned = cleaned.replace(/^(?:workstation|agent)\s+observation:\s*/iu, "");
    }
    if (subjectId === WORKSTATION_SUBJECT_IDS.workstationIncidents) {
      cleaned = cleaned.replace(/^incident:\s*/iu, "");
    }
    return cleaned;
  },
};

/** Reserved marker tag: an index-hub article absorbs into its subject in
 *  the agent-context TAG-DRIVEN absorption path (main keeps its UUID map). */
export const KNOWLEDGE_INDEX_HUB_TAG = "index-hub";

/** Agent id grammar shared with the gateway's per-agent knowledge routes
 *  (`knowledgeAgentIdSchema`): validated before the name reaches a subject
 *  id, storage key, or URL segment. */
const KNOWLEDGE_AGENT_NAME_PATTERN = /^[a-z0-9][a-z0-9._-]{0,31}$/;

/** Per-role subject trees (owner 2026-08-03, second round): each agent
 *  brain MIRRORS the JARVIS shape — an Agent node carrying Tools/Skills/
 *  Runbooks/Tasks/Architecture/Preferences plus its own named observations
 *  child, and
 *  bespoke domain branches per role, each owning its own explicitly named
 *  observations child (the main-brain convention). Entries are
 *  {key, label, summary, parentKey?} — parentKey references another
 *  entry's key; absent = a direct root branch. Unknown roles fall back to
 *  the generic shape so a future subagent still renders without a deploy. */
interface AgentSubjectSpec {
  key: string;
  label: string;
  summary: string;
  parentKey?: string;
}

const AGENT_SELF_BRANCH: readonly AgentSubjectSpec[] = [
  {
    key: "agent",
    label: "Agent",
    summary:
      "The agent itself: identity, tools, skills, runbooks, tasks, architecture, and preferences.",
  },
  {
    key: "agent:tools",
    label: "Tools",
    summary: "The agent's own tool surface, one article per tool.",
    parentKey: "agent",
  },
  {
    key: "agent:skills",
    label: "Skills",
    summary:
      "Checked-out skill articles: reusable methods kept current from Athenaeum.",
    parentKey: "agent",
  },
  {
    // The agent's procedural shelf: active runbooks and checked-out runbook
    // templates live here. Every marked checkout remains a full local copy,
    // so run-time reads and semantic search never leave this agent's vault;
    // the guardian sync keeps those copies current with Athenaeum.
    key: "agent:runbooks",
    label: "Runbooks",
    summary:
      "Active runbooks and checked-out runbook templates kept current from Athenaeum.",
    parentKey: "agent",
  },
  {
    // The variant registry (owner 2026-08-04: "tasks under the jobs …
    // then we can have task articles, problem solved"): one `Task: <name>`
    // article per kind of work an existing task type absorbs (ingest
    // phases, archive lanes, news kinds). The articles ARE the valid
    // values — a runbook parameter of type `task` validates against what
    // this node holds, exactly like the runbook dropdown law. Growth is
    // one curated article, never a declaration edit or a code change.
    key: "agent:tasks",
    label: "Tasks",
    summary:
      "Task articles: the variant registry — one article per kind of work an existing task type absorbs.",
    parentKey: "agent",
  },
  {
    key: "agent:architecture",
    label: "Architecture",
    summary: "How this agent is wired into the workstation.",
    parentKey: "agent",
  },
  {
    key: "agent:preferences",
    label: "Preferences",
    summary: "Durable working preferences for this agent.",
    parentKey: "agent",
  },
  {
    key: "agent:others",
    label: "Other Agents",
    summary: "The executive and the sibling agents: who they are, what they do.",
    parentKey: "agent",
  },
  {
    key: "agent:observations",
    label: "Agent Observations",
    summary: "The agent's distilled notes about itself and its own runs.",
    parentKey: "agent",
  },
];

const AGENT_SUBJECT_TREES: Readonly<
  Record<string, readonly AgentSubjectSpec[]>
> = {
  curator: [
    ...AGENT_SELF_BRANCH,
    {
      key: "curation",
      label: "Curation",
      summary: "Wiki maintenance: runbooks, trust lanes, taxonomy discipline.",
    },
    {
      key: "curation:observations",
      label: "Curation Observations",
      summary: "Distilled notes from curation runs: patterns, failures, fixes.",
      parentKey: "curation",
    },
    {
      key: "sources",
      label: "Sources",
      summary: "The raw-source pipeline: inbox, ingest, evidence, library.",
    },
    {
      key: "sources:observations",
      label: "Source Observations",
      summary: "Distilled notes about the source pipeline's behavior.",
      parentKey: "sources",
    },
  ],
  researcher: [
    ...AGENT_SELF_BRANCH,
    {
      key: "acquisition",
      label: "Acquisition",
      summary: "Fetching and filing: job runbooks and inbox conventions.",
    },
    {
      key: "acquisition:observations",
      label: "Acquisition Observations",
      summary: "Distilled notes from acquisition runs.",
      parentKey: "acquisition",
    },
    {
      key: "sites",
      label: "Sites",
      summary: "How specific sites and feeds are fetched effectively.",
    },
    {
      key: "sites:observations",
      label: "Site Observations",
      summary: "Distilled notes on source quality, paywalls, and feeds.",
      parentKey: "sites",
    },
  ],
  guardian: [
    ...AGENT_SELF_BRANCH,
    {
      key: "verification",
      label: "Verification",
      summary: "Job auditing and claim verification: runbooks and formats.",
    },
    {
      key: "verification:observations",
      label: "Verification Observations",
      summary: "Distilled notes from verify and audit cycles.",
      parentKey: "verification",
    },
    {
      key: "gate",
      label: "Merge Gate",
      summary: "The agent-lane review gate: rules, checks, git proposals.",
    },
    {
      key: "gate:observations",
      label: "Gate Observations",
      summary: "Distilled notes from merge-gate reviews.",
      parentKey: "gate",
    },
    {
      // The Task Board (owner 2026-08-04, final form: "the taskboard is a
      // node under the guardian" — never a separate agent or vault): one
      // mirrored Job: article per gateway cron job, projected into the
      // TASKMASTER-HOLDER'S own vault by the code-owned jobs mirror
      // (JARVIS_TASKMASTER_AGENT, default guardian — this bespoke subject
      // is presentation sugar for today's holder, not a role law).
      // Definitions only, never live status; articles are mirror-owned;
      // jobs change through the scoped jobs CLI. Hermes cron is the clock.
      key: "taskboard",
      label: "Task Board",
      summary:
        "The fleet's job calendar: one mirrored article per cron job; the taskmaster's working surface.",
    },
  ],
  // Athenaeum, the shared knowledge library (owner 2026-08-04: the
  // "libraries library"): a PASSIVE vault, not an actor — no Agent self
  // branch and no conventions shelf: it is the fleet's four indexed
  // bookshelves. Agent-side architecture owns the working conventions. One
  // article edited here
  // changes behavior on every agent that references it.
  library: [
    {
      key: "tools",
      label: "Tools",
      summary: "Shared tool interface documentation, one article per tool.",
    },
    {
      key: "skills",
      label: "Skills",
      summary: "Shared technique articles composing tools for task families.",
    },
    {
      key: "runbooks",
      label: "Runbooks",
      summary: "Shared procedure templates, copied and specialized per agent.",
    },
    {
      // The shared variant registry shelf (owner 2026-08-04: "Tasks need
      // to go into the library like the jobs do and get copied the same
      // way"): canonical Task: articles checked out to agents as marked
      // copies — the library composes the agents.
      key: "tasks",
      label: "Tasks",
      summary:
        "Shared task articles: canonical variants of the fleet's task types, checked out to agents as synced copies.",
    },
  ],
};

/** Fallback shape for roles without a bespoke tree. */
const AGENT_GENERIC_TREE: readonly AgentSubjectSpec[] = [
  ...AGENT_SELF_BRANCH,
  {
    key: "operations",
    label: "Operations",
    summary: "How the agent runs its own recurring work and procedures.",
  },
  {
    key: "operations:observations",
    label: "Operation Observations",
    summary: "Distilled agent-authored observations from its own runs.",
    parentKey: "operations",
  },
];


export function agentKnowledgeSubjectId(agent: string, branch?: string): string {
  return branch === undefined
    ? `subject:agent:${agent}`
    : `subject:agent:${agent}:${branch}`;
}

/**
 * The generic per-subagent taxonomy: one root named after the agent plus
 * four fixed branches. Placement and hub absorption are entirely
 * TAG-DRIVEN (no hand-maintained claim-id map): an ordinary claim resolves
 * only through a `subject:agent:<name>:<branch>` tag in the agent's own
 * assignable set (the root is excluded, so a claim can never sit on it);
 * a non-draft claim tagged `index-hub` with NO subject tag is the one
 * sanctioned root index (several contenders tie-break to the lowest claim
 * id, deterministically), and an `index-hub` claim that also carries a
 * branch subject tag absorbs as that branch's hub.
 */
export function agentKnowledgeOntologyContext(
  name: string,
  label: string,
): KnowledgeOntologyContext {
  if (!KNOWLEDGE_AGENT_NAME_PATTERN.test(name)) {
    throw new Error("Knowledge agent id is invalid.");
  }
  const rootId = agentKnowledgeSubjectId(name);
  const tree = AGENT_SUBJECT_TREES[name] ?? AGENT_GENERIC_TREE;
  const subjects: readonly SubjectDefinition[] = [
    {
      id: rootId,
      label,
      summary: `The ${label} agent's own knowledge vault.`,
      parentId: null,
      order: 0,
      role: "root",
    },
    ...tree.map(
      (branch, index): SubjectDefinition => ({
        id: agentKnowledgeSubjectId(name, branch.key),
        label: branch.label,
        summary: branch.summary,
        parentId: branch.parentKey
          ? agentKnowledgeSubjectId(name, branch.parentKey)
          : rootId,
        order: index,
        role: "section",
      }),
    ),
  ];
  const assignableSubjectIds: ReadonlySet<string> = new Set(
    subjects
      .filter((subject) => subject.id !== rootId)
      .map((subject) => subject.id),
  );
  const firstSubjectTag = (tags: readonly string[]): string | undefined =>
    tags.find(
      (tag) => tag.startsWith("subject:") && assignableSubjectIds.has(tag),
    );
  return {
    subjects,
    rootId,
    assignableSubjectIds,
    subjectTagAssignableIds: assignableSubjectIds,
    absorbConnectedSubjectArticles: name === "library",
    temporaryObservationsSubjectId: agentKnowledgeSubjectId(
      name,
      "observations",
    ),
    autoCuratedSubjectIds: new Set(),
    subjectArticleClaimIds(nodes) {
      const hubs = new Map<string, string>();
      const claimHub = (subjectId: string, claimId: string) => {
        // Deterministic: when several claims contend for one hub, the
        // lowest claim id wins.
        const existing = hubs.get(subjectId);
        if (existing === undefined || claimId < existing) {
          hubs.set(subjectId, claimId);
        }
      };
      for (const node of nodes) {
        const tags = node.tags ?? [];
        if (!tags.includes(KNOWLEDGE_INDEX_HUB_TAG)) continue;
        if (!tags.some((tag) => tag.startsWith("subject:"))) {
          // index-hub with NO subject tag: the one sanctioned root index.
          // Draft root indexes stay review-queue material, never absorbed.
          if (node.lifecycle !== "draft") claimHub(rootId, node.id);
          continue;
        }
        const subjectTag = firstSubjectTag(tags);
        if (subjectTag) claimHub(subjectTag, node.id);
      }
      return hubs;
    },
    primarySubjectForNode(node) {
      const tags = node.tags ?? [];
      const subjectTag = firstSubjectTag(tags);
      if (subjectTag) return subjectTag;
      if (
        tags.includes(KNOWLEDGE_INDEX_HUB_TAG) &&
        !tags.some((tag) => tag.startsWith("subject:"))
      ) {
        // The root index resolves to the root; admission then accepts only
        // the absorbed (lowest-id, non-draft) contender, exactly like the
        // Brain's one sanctioned assignment on the main vault.
        return rootId;
      }
      return null;
    },
    claimDisplayLabel(label) {
      return label;
    },
  };
}

export interface AssignableWorkstationSubject {
  id: string;
  label: string;
  /** Label path below the Brain root, e.g. "ADMECH Workstation > Hardware". */
  path: string;
  depth: number;
}

/** Subjects the operator may choose as an article's placement, in taxonomy
 *  (depth-first) order. The root is never assignable; on the main vault the
 *  authority-owned transient cache and the rotating news lane are excluded
 *  from the picker (they remain reachable by their own reserved lane tags). */
export function assignableWorkstationSubjectsIn(
  context: KnowledgeOntologyContext,
): AssignableWorkstationSubject[] {
  const childrenByParent = new Map<string, SubjectDefinition[]>();
  for (const subject of context.subjects) {
    if (subject.parentId === null) continue;
    const siblings = childrenByParent.get(subject.parentId) ?? [];
    siblings.push(subject);
    childrenByParent.set(subject.parentId, siblings);
  }
  for (const siblings of childrenByParent.values()) {
    siblings.sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
  }
  const result: AssignableWorkstationSubject[] = [];
  const walk = (parentId: string, path: readonly string[], depth: number) => {
    for (const subject of childrenByParent.get(parentId) ?? []) {
      const subjectPath = [...path, subject.label];
      if (context.subjectTagAssignableIds.has(subject.id)) {
        result.push({
          id: subject.id,
          label: subject.label,
          path: subjectPath.join(" > "),
          depth,
        });
      }
      walk(subject.id, subjectPath, depth + 1);
    }
  };
  walk(context.rootId, [], 0);
  return result;
}

export function assignableWorkstationSubjects(): AssignableWorkstationSubject[] {
  return assignableWorkstationSubjectsIn(mainKnowledgeOntologyContext);
}

/** Full-path labels for EVERY subject — including the deliberately
 *  non-assignable authority lanes (Today's Top 10, Temporary Observations)
 *  and the root. Presentation-only: a resolved placement's face label must
 *  read as a path even when its subject is excluded from the picker's
 *  choices (a reserved lane tag can resolve placement onto exactly those
 *  subjects). */
export function workstationSubjectPathLabelsIn(
  context: KnowledgeOntologyContext,
): ReadonlyMap<string, string> {
  const childrenByParent = new Map<string, SubjectDefinition[]>();
  for (const subject of context.subjects) {
    if (subject.parentId === null) continue;
    const siblings = childrenByParent.get(subject.parentId) ?? [];
    siblings.push(subject);
    childrenByParent.set(subject.parentId, siblings);
  }
  const labels = new Map<string, string>();
  const root = context.subjects.find((subject) => subject.id === context.rootId);
  if (root) labels.set(root.id, root.label);
  const walk = (parentId: string, path: readonly string[]) => {
    for (const subject of childrenByParent.get(parentId) ?? []) {
      const subjectPath = [...path, subject.label];
      labels.set(subject.id, subjectPath.join(" > "));
      walk(subject.id, subjectPath);
    }
  };
  walk(context.rootId, []);
  return labels;
}

export function workstationSubjectPathLabels(): ReadonlyMap<string, string> {
  return workstationSubjectPathLabelsIn(mainKnowledgeOntologyContext);
}

export function unassignedWorkstationClaimIdsIn(
  context: KnowledgeOntologyContext,
  source: Pick<KnowledgeGraphSnapshot, "nodes">,
): string[] {
  const hubClaimIdBySubjectId = context.subjectArticleClaimIds(source.nodes);
  return source.nodes
    .filter((node) => {
      // Pending review DRAFTS never gate admission (2026-08-02: a single
      // curator-staged draft with no assignment blanked the whole ambient
      // graph after the HEREBRUM rename emptied the last-known-good
      // fallback cache). An un-reviewed candidate is review-queue
      // material — it is excluded from ambient placement below rather
      // than treated as a mis-categorized accepted claim.
      if (node.lifecycle === "draft") return false;
      const subjectId = context.primarySubjectForNode(node);
      if (subjectId === context.rootId) {
        // The root's own absorbed index article is the one sanctioned
        // root assignment; every other claim needs a real subject.
        return hubClaimIdBySubjectId.get(context.rootId) !== node.id;
      }
      return !subjectId || !context.assignableSubjectIds.has(subjectId);
    })
    .map((node) => node.id);
}

export function unassignedWorkstationClaimIds(
  source: Pick<KnowledgeGraphSnapshot, "nodes">,
): string[] {
  return unassignedWorkstationClaimIdsIn(mainKnowledgeOntologyContext, source);
}

/** Ambient placement excludes unassigned pending drafts: they surface in
 *  the review queue (badge + Inspect), never as accepted graph content.
 *  A draft that DOES carry an explicit assignment (e.g. an agent-lane
 *  reserved tag) keeps rendering exactly as before. */
export function placeableWorkstationSnapshotIn(
  context: KnowledgeOntologyContext,
  source: KnowledgeGraphSnapshot,
): KnowledgeGraphSnapshot {
  const hubClaimIdBySubjectId = context.subjectArticleClaimIds(source.nodes);
  const placeable = source.nodes.filter((node) => {
    if (node.lifecycle !== "draft") return true;
    const subjectId = context.primarySubjectForNode(node);
    if (subjectId === context.rootId) {
      return hubClaimIdBySubjectId.get(context.rootId) === node.id;
    }
    return Boolean(subjectId && context.assignableSubjectIds.has(subjectId));
  });
  if (placeable.length === source.nodes.length) return source;
  const kept = new Set(placeable.map((node) => node.id));
  return {
    ...source,
    nodes: placeable,
    edges: source.edges.filter(
      (edge) => kept.has(edge.source) && kept.has(edge.target),
    ),
  };
}

export function placeableWorkstationSnapshot(
  source: KnowledgeGraphSnapshot,
): KnowledgeGraphSnapshot {
  return placeableWorkstationSnapshotIn(mainKnowledgeOntologyContext, source);
}

function subjectNode(
  definition: SubjectDefinition,
  degree: number,
  article?: KnowledgeNode,
): KnowledgeNode {
  return {
    id: definition.id,
    kind: article?.kind ?? "concept",
    lifecycle: article?.lifecycle ?? "reviewed",
    tier: article?.tier ?? "hot",
    confidence: article?.confidence ?? 1,
    degree,
    label: definition.label,
    summary: article?.summary ?? definition.summary,
  };
}

function taxonomyEdge(childId: string, parentId: string): KnowledgeEdge {
  return {
    id: `taxonomy:${childId}`,
    source: childId,
    target: parentId,
    type: "part_of",
  };
}

function displayClaim(
  context: KnowledgeOntologyContext,
  node: KnowledgeNode,
  subjectId: string,
): KnowledgeNode {
  if (!node.label) return node;
  const label = context.claimDisplayLabel(node.label, subjectId);
  return label === node.label ? node : { ...node, label };
}

export function temporaryObservationPresentationId(id: string): string {
  return `temporary:${id}`;
}

function temporaryObservationNode(
  observation: KnowledgeTemporaryObservation,
  degree: number,
): KnowledgeNode {
  return {
    id: temporaryObservationPresentationId(observation.id),
    kind: "event",
    lifecycle: "draft",
    tier: "hot",
    confidence: 0,
    degree,
    label: observation.text,
    summary: `Observed ${observation.observedAt}. ${
      observation.omitted
        ? "Source content was omitted by policy."
        : "Transient, unverified working context."
    }`,
  };
}

function buildBreadcrumbs(
  nodes: readonly KnowledgeNode[],
  hierarchy: readonly KnowledgeHierarchyEntry[],
): ReadonlyMap<string, readonly string[]> {
  const labelById = new Map(
    nodes.map((node) => [node.id, node.label ?? node.kind] as const),
  );
  const parentById = new Map(
    hierarchy
      .filter(
        (
          entry,
        ): entry is KnowledgeHierarchyEntry & { parentId: string } =>
          entry.parentId !== null,
      )
      .map((entry) => [entry.id, entry.parentId] as const),
  );
  const breadcrumbs = new Map<string, readonly string[]>();

  for (const node of nodes) {
    const labels: string[] = [];
    const visited = new Set<string>();
    let currentId: string | undefined = node.id;
    while (currentId && !visited.has(currentId)) {
      visited.add(currentId);
      const label = labelById.get(currentId);
      if (label) labels.unshift(label);
      currentId = parentById.get(currentId);
    }
    breadcrumbs.set(node.id, labels);
  }
  return breadcrumbs;
}

export function buildWorkstationKnowledgeProjectionIn(
  context: KnowledgeOntologyContext,
  rawSource: KnowledgeGraphSnapshot,
): WorkstationKnowledgeProjection {
  const unassignedClaimIds = unassignedWorkstationClaimIdsIn(
    context,
    rawSource,
  );
  if (unassignedClaimIds.length > 0) {
    throw new Error(
      `Knowledge navigation requires an explicit subject for ${unassignedClaimIds.length} claim(s).`,
    );
  }
  const source = placeableWorkstationSnapshotIn(context, rawSource);
  const sourceNodeById = new Map(
    source.nodes.map((node) => [node.id, node] as const),
  );
  const subjectParentById = new Map(
    context.subjects.map((subject) => [subject.id, subject.parentId] as const),
  );
  const subjectIsWithin = (candidate: string | null, ancestor: string) => {
    const visited = new Set<string>();
    let current = candidate;
    while (current && !visited.has(current)) {
      if (current === ancestor) return true;
      visited.add(current);
      current = subjectParentById.get(current) ?? null;
    }
    return false;
  };
  const hubClaimIdBySubjectId = context.subjectArticleClaimIds(source.nodes);
  const subjectArticleBySubjectId = new Map(
    context.subjects.flatMap((subject) => {
      const articleId = hubClaimIdBySubjectId.get(subject.id);
      const article = articleId ? sourceNodeById.get(articleId) : undefined;
      if (!article) return [];
      const carriesMeaningfulAttestedEdge = source.edges.some((edge) => {
        if (edge.source !== article.id && edge.target !== article.id) {
          return false;
        }
        // A child article's `part_of` edge to its own index says exactly
        // what the subject taxonomy already says. It is safe to collapse,
        // and the projection below removes that duplicate membership edge.
        // Any other relationship touching the index remains meaningful and
        // retains the ordinary connected-hub fail-safe.
        if (edge.type === "part_of" && edge.target === article.id) {
          const child = sourceNodeById.get(edge.source);
          return (
            !child ||
            !subjectIsWithin(
              context.primarySubjectForNode(child),
              subject.id,
            )
          );
        }
        return true;
      });
      // Ordinary connected index hubs retain the fail-safe: they stay visible
      // as leaves so the renderer never silently reattributes an attested
      // relationship. Athenaeum explicitly absorbs every connected shelf
      // index, and main Agent > Tools is the one subject-level exception; only
      // those declared cases remap meaningful edges and collapse redundant
      // child-to-index membership into the presentation taxonomy below.
      if (
        carriesMeaningfulAttestedEdge &&
        !context.absorbConnectedSubjectArticles &&
        !context.alwaysAbsorbConnectedSubjectIds?.has(subject.id)
      ) {
        return [];
      }
      return [[subject.id, article]] as const;
    }),
  );
  const subjectIdByArticleClaimId = new Map(
    [...subjectArticleBySubjectId].map(([subjectId, article]) => [
      article.id,
      subjectId,
    ]),
  );
  const subjectByClaimId = new Map(
    source.nodes.map(
      (node) => [node.id, context.primarySubjectForNode(node)] as const,
    ),
  );
  const projectedAttestedEdges: KnowledgeEdge[] = source.edges.flatMap(
    (edge) => {
      const projectedSource =
        subjectIdByArticleClaimId.get(edge.source) ?? edge.source;
      const projectedTarget =
        subjectIdByArticleClaimId.get(edge.target) ?? edge.target;

      // Child articles already connect to their exact subject through the
      // presentation taxonomy. The accepted child `part_of` index edge is
      // the same membership fact, so rendering both creates a duplicate line
      // and makes the index look like a separate leaf. Its semantics remain
      // represented by the taxonomy branch.
      const taxonomyRepresentsMembership =
        edge.type === "part_of" &&
        subjectIdByArticleClaimId.has(edge.target) &&
        subjectIsWithin(
          subjectByClaimId.get(edge.source) ?? null,
          projectedTarget,
        );
      if (taxonomyRepresentsMembership || projectedSource === projectedTarget) {
        return [];
      }

      return [
        {
          ...edge,
          source: projectedSource,
          target: projectedTarget,
        },
      ];
    },
  );
  const visibleClaims = source.nodes
    .filter((node) => !subjectIdByArticleClaimId.has(node.id))
    .map((node) => displayClaim(context, node, subjectByClaimId.get(node.id)!));
  const claimHierarchy = visibleClaims.map(
    (node, index): KnowledgeHierarchyEntry => ({
      id: node.id,
      parentId: subjectByClaimId.get(node.id)!,
      order: 100 + index,
      role: "claim",
    }),
  );
  const temporaryObservationHierarchy = source.temporaryObservations.map(
    (observation, index): KnowledgeHierarchyEntry => ({
      id: temporaryObservationPresentationId(observation.id),
      parentId: context.temporaryObservationsSubjectId,
      order: 100 + index,
      role: "temporary",
    }),
  );
  const subjectHierarchy = context.subjects.map(
    (subject): KnowledgeHierarchyEntry => ({
      id: subject.id,
      parentId: subject.parentId,
      order: subject.order,
      role: subject.role,
    }),
  );
  const hierarchy = [
    ...subjectHierarchy,
    ...claimHierarchy,
    ...temporaryObservationHierarchy,
  ];
  const taxonomyEdges = hierarchy
    .filter(
      (
        entry,
      ): entry is KnowledgeHierarchyEntry & { parentId: string } =>
        entry.parentId !== null,
    )
    .map((entry) => taxonomyEdge(entry.id, entry.parentId));
  // Transient display references: a Temporary Observations leaf may point at
  // the active claims it is about (authority-supplied relatedClaimIds).
  // Owner decision 2026-07-30: they render exactly like attested cross-links
  // (curved + dashed), NOT like radial taxonomy branches — the straight
  // branch-colored treatment made the reference line stand out across the
  // graph. They stay synthetic internally: excluded from attestedEdgeCount
  // and never fed back to trust, review, or retrieval; they vanish with the
  // entry.
  const projectedClaimIds = new Set(source.nodes.map((node) => node.id));
  const temporaryReferenceEdges = source.temporaryObservations.flatMap(
    (observation) =>
      (observation.relatedClaimIds ?? [])
        .map((claimId) => subjectIdByArticleClaimId.get(claimId) ?? claimId)
        .filter(
          (targetId) =>
            projectedClaimIds.has(targetId) ||
            context.subjects.some((subject) => subject.id === targetId),
        )
        .map((targetId) => ({
          id: `temporary-ref:${observation.id}:${targetId}`,
          source: temporaryObservationPresentationId(observation.id),
          target: targetId,
          type: "related_to" as const,
        })),
  );
  const directDegree = new Map<string, number>();
  for (const edge of taxonomyEdges) {
    directDegree.set(edge.source, (directDegree.get(edge.source) ?? 0) + 1);
    directDegree.set(edge.target, (directDegree.get(edge.target) ?? 0) + 1);
  }
  for (const subjectId of subjectArticleBySubjectId.keys()) {
    directDegree.set(subjectId, (directDegree.get(subjectId) ?? 0) + 1);
  }
  const subjects = context.subjects.map((definition) =>
    subjectNode(
      definition,
      directDegree.get(definition.id) ?? 0,
      subjectArticleBySubjectId.get(definition.id),
    ),
  );
  const temporaryObservationNodes = source.temporaryObservations.map(
    (observation) =>
      temporaryObservationNode(
        observation,
        directDegree.get(temporaryObservationPresentationId(observation.id)) ??
          0,
      ),
  );
  // The context's design-time auto-curated lanes (see
  // MAIN_AUTO_CURATED_SUBJECT_IDS) seed the ring-marker set.
  const autoCuratedNodeIds = new Set<string>(context.autoCuratedSubjectIds);
  for (const node of source.nodes) {
    if (node.tags?.includes("auto-curate")) autoCuratedNodeIds.add(node.id);
  }
  for (const [subjectId, article] of subjectArticleBySubjectId) {
    if (article.tags?.includes("auto-curate")) autoCuratedNodeIds.add(subjectId);
  }
  // Auto-curation CASCADES down the taxonomy to EVERY descendant (owner
  // 2026-08-04: checking auto-curate on an agent's root node must turn
  // every child node's ring on — the daemon materializes the lane on new
  // arrivals, and the marker shows the EFFECTIVE policy for existing
  // ones; owner 2026-08-03: a subject nested inside an auto-curated lane
  // cannot be review-gated on its own). The cascade never climbs upward.
  let cascadeGrew = true;
  while (cascadeGrew) {
    cascadeGrew = false;
    for (const entry of hierarchy) {
      if (
        entry.parentId !== null &&
        autoCuratedNodeIds.has(entry.parentId) &&
        !autoCuratedNodeIds.has(entry.id)
      ) {
        autoCuratedNodeIds.add(entry.id);
        cascadeGrew = true;
      }
    }
  }
  const temporaryObservationNodeIds = new Set(
    temporaryObservationNodes.map((node) => node.id),
  );
  const nodes = [...subjects, ...visibleClaims, ...temporaryObservationNodes];
  const roleById = new Map(
    hierarchy.map((entry) => [entry.id, entry.role] as const),
  );
  const parentById = new Map(
    hierarchy
      .filter(
        (
          entry,
        ): entry is KnowledgeHierarchyEntry & { parentId: string } =>
          entry.parentId !== null,
      )
      .map((entry) => [entry.id, entry.parentId] as const),
  );
  const taxonomyEdgeByChildId = new Map(
    taxonomyEdges.map((edge) => [edge.source, edge.id] as const),
  );

  return {
    snapshot: {
      ...source,
      nodes,
      edges: [
        ...taxonomyEdges,
        ...temporaryReferenceEdges,
        ...projectedAttestedEdges,
      ],
    },
    hierarchy,
    subjectNodeIds: subjects.map((node) => node.id),
    subjectArticleBySubjectId,
    subjectIdByArticleClaimId,
    taxonomyEdgeIds: new Set(taxonomyEdges.map((edge) => edge.id)),
    roleById,
    parentById,
    taxonomyEdgeByChildId,
    breadcrumbById: buildBreadcrumbs(nodes, hierarchy),
    temporaryObservationNodeIds,
    autoCuratedNodeIds,
    claimCount: source.nodes.length,
    temporaryObservationCount: temporaryObservationNodes.length,
    attestedEdgeCount: source.edges.length,
  };
}

export function buildWorkstationKnowledgeProjection(
  rawSource: KnowledgeGraphSnapshot,
): WorkstationKnowledgeProjection {
  return buildWorkstationKnowledgeProjectionIn(
    mainKnowledgeOntologyContext,
    rawSource,
  );
}

/**
 * Build the Reader's ephemeral navigation view without weakening graph
 * admission. A live authority snapshot may contain newly accepted claims
 * that still need an operator category; the ambient canvas correctly keeps
 * displaying its complete last-known-good projection in that case. The
 * Reader must nevertheless be able to open a node from that displayed graph.
 *
 * This helper drops only the unrelated, explicitly unassigned accepted
 * claims (and their incident edges) for this one read. It is never cached,
 * rendered as a new graph revision, or used as authority/retrieval input.
 */
export function buildReadableWorkstationKnowledgeProjectionIn(
  context: KnowledgeOntologyContext,
  source: KnowledgeGraphSnapshot,
): WorkstationKnowledgeProjection {
  const unassignedClaimIds = new Set(
    unassignedWorkstationClaimIdsIn(context, source),
  );
  if (unassignedClaimIds.size === 0) {
    return buildWorkstationKnowledgeProjectionIn(context, source);
  }
  const nodes = source.nodes.filter(
    (node) => !unassignedClaimIds.has(node.id),
  );
  const nodeIds = new Set(nodes.map((node) => node.id));
  return buildWorkstationKnowledgeProjectionIn(context, {
    ...source,
    nodes,
    edges: source.edges.filter(
      (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
    ),
  });
}

export function admitWorkstationKnowledgeProjectionIn(
  context: KnowledgeOntologyContext,
  source: KnowledgeGraphSnapshot,
): WorkstationKnowledgeProjectionAdmission {
  const unassignedClaimIds = unassignedWorkstationClaimIdsIn(context, source);
  return unassignedClaimIds.length > 0
    ? { projection: null, unassignedClaimIds }
    : {
        projection: buildWorkstationKnowledgeProjectionIn(context, source),
        unassignedClaimIds: [],
      };
}

export function admitWorkstationKnowledgeProjection(
  source: KnowledgeGraphSnapshot,
): WorkstationKnowledgeProjectionAdmission {
  return admitWorkstationKnowledgeProjectionIn(
    mainKnowledgeOntologyContext,
    source,
  );
}

export function retainLastWorkstationKnowledgeProjection(
  previous: WorkstationKnowledgeProjection | null,
  admission: WorkstationKnowledgeProjectionAdmission | null,
): WorkstationKnowledgeProjection | null {
  return admission?.projection ?? previous;
}

export interface KnowledgeFocusSelection {
  nodeIds: string[];
  edgeIds: string[];
}

export function expandKnowledgeFocusToAncestors(
  projection: WorkstationKnowledgeProjection,
  selectedNodeIds: readonly string[],
  selectedEdgeIds: readonly string[],
  nodeLimit: number,
  edgeLimit: number,
): KnowledgeFocusSelection {
  const nodeIds: string[] = [];
  const edgeIds: string[] = [];
  const nodeSet = new Set<string>();
  const edgeSet = new Set<string>();

  const addNode = (id: string) => {
    if (nodeSet.has(id) || nodeIds.length >= nodeLimit) return false;
    nodeSet.add(id);
    nodeIds.push(id);
    return true;
  };
  const addEdge = (id: string) => {
    if (edgeSet.has(id) || edgeIds.length >= edgeLimit) return false;
    edgeSet.add(id);
    edgeIds.push(id);
    return true;
  };

  const displaySelectedNodeIds = selectedNodeIds.map(
    (id) => projection.subjectIdByArticleClaimId.get(id) ?? id,
  );
  for (const id of displaySelectedNodeIds) addNode(id);
  for (const id of selectedEdgeIds) addEdge(id);

  for (const selectedId of displaySelectedNodeIds) {
    const visited = new Set<string>();
    let childId: string | undefined = selectedId;
    while (childId && !visited.has(childId)) {
      visited.add(childId);
      const parentId = projection.parentById.get(childId);
      if (!parentId) break;
      const taxonomyEdgeId = projection.taxonomyEdgeByChildId.get(childId);
      if (taxonomyEdgeId) addEdge(taxonomyEdgeId);
      addNode(parentId);
      childId = parentId;
    }
  }

  return { nodeIds, edgeIds };
}
