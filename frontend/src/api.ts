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
  startInvestigation: (question: string) =>
    request<{ id: string }>('/api/investigations', {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),
  investigations: () => request<RunSummary[]>('/api/investigations'),
  audit: () => request<AuditEntry[]>('/api/audit?limit=200'),
}

// ---------- types (mirror the backend) ----------

export interface ServiceStatus {
  ok: boolean
  tools?: number
  error?: string
  last_discovery?: string | null
}

export interface Health {
  executor: 'live' | 'replay'
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

export type RunEvent =
  | { type: 'started'; question: string; tools: string[]; at_ms: number }
  | { type: 'thought'; text: string; tools: string[]; at_ms: number }
  | {
      type: 'tool_call'
      id: string
      tool: string
      server: string
      args: Record<string, unknown>
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
      at_ms: number
    }
  | {
      type: 'report'
      report: Report
      confidence: 'high' | 'medium' | 'low'
      confidence_reasons: string[]
      tool_calls: number
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
