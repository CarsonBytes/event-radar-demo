import type { EventItem, InterestProfile } from './types'
import { termMatches } from './keywordMatch'

// Mirrors the backend's stage1_filter keyword-overlap check (app/ranking.py)
// so "why did this match" can show the actual interest terms found in the
// event, not just the LLM's free-text rationale. Matching runs against the
// English fields (title/description/category), same as stage1_filter --
// but note the parsed interest keywords aren't always English in practice
// (the LLM parser is asked to translate, but a proper noun like an artist
// name can come back untouched, e.g. "古天樂"), which is exactly why
// termMatches needs its own CJK substring fallback rather than assuming
// ASCII-only terms.
export function computeMatchingTags(event: EventItem, profile: InterestProfile | null): string[] {
  if (!profile) return []
  const terms = [...profile.categories, ...profile.keywords].filter((term) => term.trim())
  const haystack = `${event.title} ${event.description} ${event.category}`

  const seen = new Set<string>()
  const matched: string[] = []
  for (const term of terms) {
    const key = term.toLowerCase()
    if (!seen.has(key) && termMatches(term, haystack)) {
      seen.add(key)
      matched.push(term)
    }
  }
  return matched
}
