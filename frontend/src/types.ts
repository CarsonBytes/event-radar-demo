export type EventStatus = 'upcoming' | 'ongoing' | 'past' | 'far_future'

export type TagFilter = { type: 'category' | 'source'; value: string }

export interface EventItem {
  id: number
  source: string
  source_url: string
  title: string
  title_native: string | null
  native_lang: string | null
  description: string
  category: string
  category_native: string | null
  start: string
  end: string | null
  venue_name: string
  venue_name_native: string | null
  location: string
  location_native: string | null
  image_url: string
  raw_score: number
  llm_score: number | null
  why_match: string
  status: EventStatus
  user_signal: 'up' | 'down' | null
  saved: boolean
}

export interface InterestProfile {
  raw_text: string
  categories: string[]
  keywords: string[]
  excluded_keywords: string[]
  weights: Record<string, number>
  updated_at: string
}

export interface IngestSummary {
  fetched: number
  new: number
  updated: number
  ranked: number
}

export interface IngestRun {
  started_at: string
  duration_ms: number
  fetched: number
  new: number
  updated: number
  ranked: number
}

export interface LlmCall {
  created_at: string
  kind: string
  model: string
  input_tokens: number
  output_tokens: number
  latency_ms: number
  cost_usd: number
}

export interface PrecisionStat {
  label: string
  up: number
  down: number
  rate: number | null
}

export interface Insights {
  recent_ingest_runs: IngestRun[]
  recent_llm_calls: LlmCall[]
  llm_total_calls: number
  llm_total_cost_usd: number
  llm_avg_latency_ms: number
  llm_calls_today: number
  llm_cost_today_usd: number
  llm_daily_cap: number | null
  shared_calls_today: number
  shared_cost_today_usd: number
  shared_calls_by_project: Record<string, number>
  overall_precision: PrecisionStat
  precision_by_category: PrecisionStat[]
}

export interface RerankLiveStatus {
  in_progress: boolean
  trigger: string | null
  started_at: string | null
  finished_at: string | null
  last_result: 'ok' | 'error' | 'skipped' | null
  skip_reason: 'not_due' | null
  quota_exhausted: boolean
  batches_done: number
  batches_total: number | null
}

export interface LastRerankEvent {
  at: string
  level: 'info' | 'warning' | 'error'
  message: string
  detail: Record<string, unknown> | null
}

export interface DebugStatus {
  demo_mode: boolean
  rerank: RerankLiveStatus
  last_rerank: LastRerankEvent | null
  last_ingest: { at: string; fetched: number } | null
  profile: { updated_at: string | null; category_count: number; keyword_count: number }
}

export interface AskReferencedEvent {
  id: number
  title: string
  title_native: string | null
}

export interface AskResponse {
  answer: string
  quota_exhausted: boolean
  referenced_events: AskReferencedEvent[]
}

export interface AskHistoryItem {
  id: number
  created_at: string
  query: string
  answer: string
  quota_exhausted: boolean
  referenced_events: AskReferencedEvent[]
}
