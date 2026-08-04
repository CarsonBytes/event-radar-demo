import type { AskHistoryItem, AskResponse, DebugStatus, EventItem, EventStatus, IngestSummary, Insights, InterestProfile } from './types'

const BASE = '/api'

// Fire-and-forget by design -- reporting a failure must never itself throw
// or block the caller, and must never recurse into itself if /debug/client
// -error is the thing that's unreachable.
export function reportClientError(message: string, opts?: { stack?: string; context?: Record<string, unknown> }): void {
  fetch(`${BASE}/debug/client-error`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, stack: opts?.stack, url: location.href, context: opts?.context }),
  }).catch(() => {})
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (err) {
    const message = `${init?.method ?? 'GET'} ${path} network error: ${err instanceof Error ? err.message : String(err)}`
    reportClientError(message, { context: { path } })
    throw new Error(message)
  }
  if (!res.ok) {
    const message = `${init?.method ?? 'GET'} ${path} failed: ${res.status}`
    reportClientError(message, { context: { path, status: res.status } })
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

export const getInterests = () => request<InterestProfile>('/interests')

export const setInterests = (raw_text: string, excluded_keywords: string[] = []) =>
  request<InterestProfile>('/interests', {
    method: 'POST',
    body: JSON.stringify({ raw_text, excluded_keywords }),
  })

export const listEvents = (status?: EventStatus) =>
  request<EventItem[]>(`/events${status ? `?status=${status}` : ''}`)

export const getEvent = (event_id: number) => request<EventItem>(`/events/${event_id}`)

export const submitFeedback = (event_id: number, signal: 'up' | 'down' | 'none') =>
  request<{ ok: boolean }>('/feedback', {
    method: 'POST',
    body: JSON.stringify({ event_id, signal }),
  })

export const runIngest = () => request<IngestSummary>('/ingest', { method: 'POST' })

export const getInsights = () => request<Insights>('/insights')

export const listSaved = () => request<EventItem[]>('/saved')

export const saveEvent = (event_id: number) => request<{ ok: boolean }>(`/saved/${event_id}`, { method: 'POST' })

export const unsaveEvent = (event_id: number) => request<{ ok: boolean }>(`/saved/${event_id}`, { method: 'DELETE' })

export const getDebugStatus = () => request<DebugStatus>('/debug/status')

export const askQuestion = (query: string) =>
  request<AskResponse>('/ask', {
    method: 'POST',
    body: JSON.stringify({ query }),
  })

export const getAskHistory = () => request<{ items: AskHistoryItem[] }>('/ask/history')
