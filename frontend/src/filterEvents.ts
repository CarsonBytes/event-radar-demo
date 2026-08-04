import type { EventItem, TagFilter } from './types'
import { termMatches } from './keywordMatch'

function matchesKeyword(event: EventItem, keyword: string): boolean {
  const q = keyword.trim()
  if (!q) return true
  return [event.title, event.title_native, event.description, event.category, event.venue_name, event.location]
    .filter(Boolean)
    .some((field) => termMatches(q, field!))
}

// Shared by the list view and the timeline view so both respect the same
// tag-click and keyword filters instead of drifting into two systems.
export function filterEvents(events: EventItem[], tagFilter: TagFilter | null, keywordFilter: string): EventItem[] {
  return events
    .filter((e) => !tagFilter || (tagFilter.type === 'category' ? e.category : e.source) === tagFilter.value)
    .filter((e) => matchesKeyword(e, keywordFilter))
}

// How many events a given interest term would filter down to, using the
// exact same predicate as the keyword filter -- so a "suggested keyword"
// chip's usefulness can be judged before it's clicked.
export function countKeywordMatches(events: EventItem[], keyword: string): number {
  return events.reduce((count, e) => count + (matchesKeyword(e, keyword) ? 1 : 0), 0)
}
