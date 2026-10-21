// Talking to the AINOPS API (backend/src/ainops/api/app.py). Vite forwards /api to it in development.

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(detail || `request failed (${response.status})`, response.status)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<Health>('/api/health'),
  topology: () => request<Topology>('/api/topology'),
  tools: () => request<ToolCatalog>('/api/tools'),
  callTool: (server: string, tool: string, args: Record<string, unknown>) =>
    request<ToolCallResult>(`/api/tools/${server}/${tool}`, {
      method: 'POST',
      body: JSON.stringify({ arguments: args }),
    }),
  startDiscovery: () => request<{ id: string }>('/api/discovery', { method: 'POST' }),
  /** `trySkill`: start it to try a skill that is not live yet ("Try this skill"). */
  startInvestigation: (question: string, trySkill?: string | null) =>
    request<{ id: string }>('/api/investigations', {
      method: 'POST',
      body: JSON.stringify(trySkill ? { question, try_skill: trySkill } : { question }),
    }),
  investigations: () => request<RunSummary[]>('/api/investigations'),
  inventory: () => request<InventoryList>('/api/inventory'),
  inventoryOptions: () => request<InventoryOptions>('/api/inventory/options'),
  addDevice: (device: NewDevice) =>
    request<InventoryRow>('/api/inventory', { method: 'POST', body: JSON.stringify(device) }),
  removeDevice: (name: string, removedBy: string) =>
    request<{ removed: string }>(`/api/inventory/${encodeURIComponent(name)}/remove`, {
      method: 'POST',
      body: JSON.stringify({ removed_by: removedBy }),
    }),
  inventoryDevice: (name: string) =>
    request<InventoryDetail>(`/api/inventory/${encodeURIComponent(name)}`),
  /** A follow-up in the conversation of an investigation: AINOPS replies in a new turn. */
  sendMessage: (runId: string, text: string) =>
    request<{ id: string; turn: number }>(`/api/runs/${runId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  stopRun: (runId: string) =>
    request<{ stopping: boolean }>(`/api/runs/${runId}/stop`, { method: 'POST' }),
  cases: (status?: CaseStatus) =>
    request<CaseList>(status ? `/api/cases?status=${status}` : '/api/cases'),
  case: (id: string) => request<Case>(`/api/cases/${id}`),
  /** The case of a conversation, and whether one can be made by hand now. */
  runCase: (runId: string) => request<RunCase>(`/api/runs/${runId}/case`),
  makeCase: (runId: string) => request<Case>(`/api/runs/${runId}/case`, { method: 'POST' }),
  reviewCase: (id: string, review: ReviewRequest) =>
    request<Case>(`/api/cases/${id}/review`, { method: 'POST', body: JSON.stringify(review) }),
  audit: () => request<AuditEntry[]>('/api/audit?limit=200'),
  skills: () => request<SkillCatalog>('/api/skills'),
  /** The skill as the form would save it; nothing is saved. */
  checkSkill: (form: SkillForm) =>
    request<SkillCheck>('/api/skills/check', { method: 'POST', body: JSON.stringify(form) }),
  createSkill: (save: SkillSave) =>
    request<SavedSkill>('/api/skills', { method: 'POST', body: JSON.stringify(save) }),
  editSkill: (name: string, save: SkillSave) =>
    request<SavedSkill>(`/api/skills/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(save),
    }),
  reviewSkill: (name: string, reviewer: string, version: string) =>
    request<SavedSkill>(`/api/skills/${encodeURIComponent(name)}/review`, {
      method: 'POST',
      body: JSON.stringify({ reviewer, version }),
    }),
  setSkillStatus: (name: string, status: SkillStatus, by: string, version: string) =>
    request<SavedSkill>(`/api/skills/${encodeURIComponent(name)}/status`, {
      method: 'POST',
      body: JSON.stringify({ status, by, version }),
    }),
  restoreSkill: (name: string, entry: string, by: string, version: string) =>
    request<SavedSkill>(`/api/skills/${encodeURIComponent(name)}/restore`, {
      method: 'POST',
      body: JSON.stringify({ entry, by, version }),
    }),
  skillHistory: (name: string) =>
    request<SkillHistoryEntry[]>(`/api/skills/${encodeURIComponent(name)}/history`),
  skillOldVersion: (name: string, id: string) =>
    request<OldSkill>(`/api/skills/${encodeURIComponent(name)}/history/${encodeURIComponent(id)}`),
}

// ---------- types (mirror the backend) ----------

export interface ServiceStatus {
  ok: boolean
  tools?: number
  error?: string
  last_discovery?: string | null
}

export interface Health {
  /** AINOPS only works on the live devices. */
  executor: 'live'
  /** The devices are the simulated copy of the lab on this laptop, not the real lab. */
  lab_simulated: boolean
  llm_model: string
  llm_configured: boolean
  mcp_network: ServiceStatus
  mcp_topology: ServiceStatus
  graph: ServiceStatus
}

export interface GraphInterface {
  name: string
  status: string
  ipv4: string[]
  /** Set when the device did not answer the last discovery: when this was last seen. */
  stale_since?: string | null
}

export interface GraphDevice {
  name: string
  site: string
  role: string
  platform: string
  description: string
  interfaces: GraphInterface[]
}

export interface GraphLink {
  key: string
  a: string
  a_interface: string
  a_status: string | null
  b: string
  b_interface: string
  b_status: string | null
  subnet: string | null
  sources: string[]
  /** Set when an end did not answer the last discovery: the link as last seen. */
  stale_since?: string | null
}

export interface Discovery {
  at: string
  source: string
  devices_ok: string[]
  devices_failed: string[]
  interface_count: number
  link_count: number
  findings: string[]
  added_links: string[]
  removed_links: string[]
  /** Devices that did not answer: their last known interfaces and links were kept. */
  devices_kept?: string[]
  /** False when no device answered and the graph was left as it was. */
  graph_updated?: boolean
}

export interface Topology {
  devices: GraphDevice[]
  links: GraphLink[]
  discovery: Discovery | null
}

export interface McpTool {
  name: string
  title?: string
  description?: string
  inputSchema: JsonSchema
  outputSchema?: JsonSchema
  annotations?: {
    readOnlyHint?: boolean
    destructiveHint?: boolean
    idempotentHint?: boolean
    openWorldHint?: boolean
  }
}

export interface JsonSchema {
  type?: string | string[]
  description?: string
  properties?: Record<string, JsonSchema>
  required?: string[]
  anyOf?: JsonSchema[]
  default?: unknown
  title?: string
  minimum?: number
  maximum?: number
}

export interface McpServer {
  url: string
  ok: boolean
  error?: string
  tools: McpTool[]
}

export interface ToolCatalog {
  servers: Record<string, McpServer>
}

export interface ToolCallResult {
  is_error: boolean
  structured: Record<string, unknown> | null
  text: string
}

export interface RunSummary {
  id: string
  kind: string
  title: string
  started_at: string
  done: boolean
  outcome: string | null
  confidence: string | null
  duration_ms: number | null
  /** Messages the engineer sent: the question plus each follow-up (missing in old answers). */
  messages?: number
  /** The conversation's case, if it has one (missing when Neo4j cannot be reached). */
  case_status?: CaseStatus | null
}

// ---------- inventory (backend inventory_view.py) ----------

export type DeviceState = 'reached' | 'not_reached' | 'not_discovered'

/** What the last discovery says about a device (no polling). */
export interface DeviceStatus {
  state: DeviceState
  /** When the last discovery ran. */
  at: string | null
  /** When the device last answered (for one that did not answer the last discovery). */
  last_seen: string | null
  /** Why the last discovery could not reach it. */
  error: string | null
}

export interface InventoryRow {
  name: string
  aliases: string[]
  site: string
  site_name: string
  role: string
  platform: string
  description: string
  /** How AINOPS reaches it, e.g. "EVE-NG console, port 32771". */
  connection: string
  /** Name of the login profile in .env; never the secret itself. Null: no login needed. */
  credential_ref: string | null
  /** Added on the Inventory page (and removable there); null: in the hand-written file. */
  added: { by: string; at: string } | null
  status: DeviceStatus
  interfaces: { total: number; addressed: number; addressed_down: number }
  /** Null when the cases could not be read. */
  cases: { total: number; pending: number } | null
}

/** What the "Add device" form can offer (backend /api/inventory/options). */
export interface InventoryOptions {
  sites: Record<string, string>
  roles: string[]
  platforms: string[]
  /** Login profiles configured in .env: names only, never the secrets. */
  credential_profiles: string[]
}

/** A device to add (backend inventory_edit.NewDevice). */
export interface NewDevice {
  name: string
  site: string
  site_name?: string
  role: string
  platform: string
  port: number
  aliases: string[]
  description: string
  credential_ref: string | null
  added_by: string
}

export interface InventoryList {
  devices: InventoryRow[]
  sites: Record<string, string>
  discovery: Discovery | null
  /** Why the knowledge graph could not be read (the devices are still listed). */
  graph_error: string | null
}

export interface InventoryDetail {
  row: InventoryRow
  interfaces: GraphInterface[]
  links: GraphLink[]
  ospf_peers: {
    device: string
    peer: string
    interface: string
    address: string
    neighbor_id: string
  }[]
  cases:
    | {
        id: string
        status: CaseStatus
        question: string
        root_cause: string | null
        updated_at: string
      }[]
    | null
  investigations: {
    id: string
    title: string
    started_at: string
    outcome: string | null
    checks: number
  }[]
  graph_error: string | null
}

// ---------- cases (backend cases.py): what an investigation found, reviewed by an engineer ----------

export type CaseStatus = 'pending' | 'approved' | 'rejected'

export interface CaseEvidence {
  id: string
  tool: string
  device: string | null
  summary: string
}

/** What AINOPS concluded, exactly as its reply said it; a review never changes it. */
export interface CaseDraft {
  outcome: Report['outcome']
  summary: string
  root_cause: string | null
  evidence: CaseEvidence[]
  confidence: string | null
  devices: string[]
  /** "IPLC-RTR-MAA Fa2/0" */
  interfaces: string[]
  path: string[]
  path_note: string | null
  skills: string[]
  suggested_fix: string[]
}

export interface CaseReview {
  action: 'approve' | 'correct' | 'reject'
  reviewer: string
  at: string
  root_cause: string | null
  fix_applied: string | null
  fix_worked: 'yes' | 'no' | 'unknown' | null
  reason: string | null
}

export interface Case {
  id: string
  run_id: string
  status: CaseStatus
  made_by: 'ainops' | 'engineer'
  created_at: string
  updated_at: string
  question: string
  draft: CaseDraft
  conversation: { message: string; outcome: string | null; root_cause: string | null }[]
  checks: number
  duration_ms: number
  /** What the AI read and wrote, all replies together (0 for cases made before it was counted). */
  tokens: number
  /** Similar past cases shown to the AI as hints in this conversation (ids). */
  hints_offered: string[]
  review: CaseReview | null
  /** The engineer's correction if there is one, else the AI's root cause. */
  root_cause: string | null
}

/** A similar past case as a hint (backend similar.py). */
export interface HintCase {
  case_id: string
  question: string
  root_cause: string
  /** The root cause is an engineer's correction. */
  corrected: boolean
  fix: string | null
  fix_worked: CaseReview['fix_worked']
  reviewer: string
  /** Why it matched, e.g. "same device IPLC-RTR-MAA". */
  reasons: string[]
  score: number
}

export interface CaseList {
  cases: Case[]
  counts: Record<CaseStatus, number>
}

export interface RunCase {
  case: Case | null
  can_make: boolean
}

export interface ReviewRequest {
  action: CaseReview['action']
  reviewer: string
  root_cause?: string
  fix_applied?: string
  fix_worked?: CaseReview['fix_worked']
  reason?: string
}

export interface AuditEntry {
  at: string
  tool: string
  device: string
  args: Record<string, unknown>
  command: string | null
  outcome: 'ok' | 'failed' | 'refused'
  reason?: string
  summary?: string
  source: string
  duration_ms: number
}

// ---------- investigation events (backend/src/ainops/agent/runner.py) ----------

export interface Evidence {
  command: string
  /** 'replay' only in investigations saved before AINOPS became live-only. */
  source: 'live' | 'replay'
  collected_at: string
  duration_ms: number
}

/** Verdict on a tool result, worked out by code from the parsed data (backend network/health.py). */
export interface HealthIssue {
  text: string
  interface: string | null
}

export interface ToolHealth {
  status: 'ok' | 'problem' | 'info'
  issues: HealthIssue[]
}

export interface Finding {
  text: string
  evidence: string[]
}

export interface NextStep {
  text: string
  kind: 'verify' | 'fix' | 'escalate'
}

export interface Report {
  outcome: 'diagnosed' | 'no_fault_found' | 'inconclusive' | 'refused' | 'answered'
  summary: string
  root_cause: string | null
  root_cause_evidence: string[]
  affected: string[]
  findings: Finding[]
  next_steps: NextStep[]
  limitations: string[]
}

/** An expert skill (backend agent/skills.py, files in skills/<name>/SKILL.md). */
export interface Skill {
  name: string
  description: string
  intro: string
  steps: string[]
  tools: string[]
  author: string
  /** Empty while the skill is a draft. */
  reviewed_by: string
  path: string
  /** Who saved it last on the Skills page, and when (empty: written by hand). */
  updated_by: string
  updated_at: string
  /** Only live skills are offered to the agent; a draft can be tried on purpose. */
  status: SkillStatus
  reviewed_at: string
}

export type SkillStatus = 'draft' | 'live' | 'off'

/** What the skill form holds (backend skill_book.py). */
export interface SkillForm {
  name: string
  description: string
  intro: string
  steps: string[]
}

export interface SkillSave {
  skill: SkillForm
  by: string
  /** The version the engineer opened; null for a new skill. */
  version: string | null
}

export interface SkillCheck {
  /** The skill as it would be saved; null when it has problems. */
  skill: Skill | null
  problems: string[]
  markdown: string
  /** False when the MCP servers are down: tool names cannot be checked, nothing can be saved. */
  tools_checked: boolean
}

export type SavedSkill = Skill & { version: string }

export interface SkillHistoryEntry {
  id: string
  replaced_at: string
  saved_by: string
  saved_at: string
  reviewed_by: string
}

export interface OldSkill {
  skill: Skill | null
  problems: string[]
  markdown: string
}

/** An investigation that opened a skill (backend skill_usage.py). */
export interface SkillRun {
  id: string
  title: string
  started_at: string
  /** How its latest reply ended; null while it runs. */
  outcome: string | null
}

export interface SkillUsage {
  /** Investigations that opened the skill. */
  count: number
  last_at: string | null
  /** The latest few, newest first. */
  recent: SkillRun[]
}

export interface SkillProblem {
  folder: string
  problems: string[]
}

export interface SkillCatalog {
  /** `version` identifies the file an edit starts from. */
  skills: (Skill & { usage: SkillUsage; version: string | null })[]
  /** Skills left out, with what to fix. */
  problems: SkillProblem[]
  /** False when the MCP servers were down: tool names could not be checked. */
  tools_checked: boolean
}

export type RunEvent =
  | {
      type: 'started'
      question: string
      tools: string[]
      skills?: string[]
      /** The skill this conversation was started to try, if any. */
      trying?: string | null
      /** Which message of the conversation this reply answers (missing before conversations). */
      turn?: number
      at_ms: number
    }
  /** A follow-up from the engineer: everything after it belongs to the next turn. */
  | { type: 'message'; turn: number; text: string; at: string }
  | { type: 'stopped'; message: string }
  /** Similar approved past cases, shown to the AI as hints (never evidence) at a reply's start. */
  | {
      type: 'hints'
      cases: HintCase[]
      /** How many approved cases were compared. */
      looked_at: number
      /** Why there was no lookup (e.g. Neo4j down). */
      error?: string | null
      at_ms: number
    }
  /** AINOPS's own check before answering: the root cause blamed something none of its cited
   *  checks showed, so the AI was sent back once to check it on that device. */
  | { type: 'recheck'; blamed: string[]; at_ms: number }
  /** After a reply that found a root cause: its case was drafted or updated (or not saved). */
  | { type: 'case'; id?: string; status?: CaseStatus; error?: string }
  | { type: 'thought'; text: string; tools: string[]; at_ms: number }
  | {
      type: 'tool_call'
      id: string
      tool: string
      server: string
      args: Record<string, unknown>
      why?: string
      /** Step of the open skill this call carries out; 0 = beyond it; null/missing = no skill. */
      skill_step?: number | null
      at_ms: number
    }
  | {
      type: 'skill'
      name: string
      description: string
      steps: string[]
      author: string
      reviewed_by: string
      /** Missing in runs from before skills had a status. */
      status?: SkillStatus
      why?: string
      at_ms: number
    }
  | {
      type: 'tool_result'
      id: string
      tool: string
      server: string
      device: string | null
      ok: boolean
      summary: string
      data: unknown
      evidence: Evidence | null
      health?: ToolHealth | null // missing in runs recorded before the verdict existed
      duration_ms: number
      at_ms: number
    }
  | {
      type: 'refused'
      tool: string
      args: Record<string, unknown>
      reason: string
      why?: string
      skill_step?: number | null
      at_ms: number
    }
  | {
      type: 'report'
      report: Report
      confidence: 'high' | 'medium' | 'low'
      confidence_reasons: string[]
      tool_calls: number
      skills_used?: string[]
      /** What the AI read and wrote for this reply (missing in older runs). */
      tokens?: { input: number; output: number }
      at_ms: number
    }
  | { type: 'error'; message: string }
  | { type: 'end' }
  // discovery
  | { type: 'device_started'; device: string }
  | {
      type: 'device_done'
      device: string
      ok: boolean
      interfaces: number
      neighbors: number
      error: string | null
    }
  | ({ type: 'discovery_done' } & Discovery)
