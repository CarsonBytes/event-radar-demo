import { useState } from 'react'
import { useLanguage } from '../i18n'
import type { EventItem, InterestProfile, TagFilter } from '../types'
import EventCard from './EventCard'
import SwipeDeck from './SwipeDeck'

// Swipe mode only makes sense here, not on Ongoing/Upcoming's full
// unfiltered lists -- it's specifically a fast way to triage a
// *already-curated, already-sorted* top-matches set, which is exactly
// what Suggestions is and the others aren't.
export default function SuggestionsView({
  events,
  profile,
  onFeedback,
  onToggleSave,
  activeFilter,
  onTagClick,
  emptyMessage,
}: {
  events: EventItem[]
  profile: InterestProfile | null
  onFeedback: (id: number, signal: 'up' | 'down' | 'none') => void
  onToggleSave: (id: number, saved: boolean) => void
  activeFilter: TagFilter | null
  onTagClick: (filter: TagFilter) => void
  emptyMessage: string
}) {
  const { t } = useLanguage()
  const [mode, setMode] = useState<'list' | 'swipe'>('list')

  if (events.length === 0) {
    return <p className="text-sm text-black/50 dark:text-white/50">{emptyMessage}</p>
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="inline-flex self-start rounded-md border border-black/10 dark:border-white/10 overflow-hidden text-sm">
        <button
          onClick={() => setMode('list')}
          className={`px-3 py-1.5 font-medium transition-colors ${
            mode === 'list'
              ? 'bg-purple-600 text-white'
              : 'text-black/60 dark:text-white/60 hover:bg-black/5 dark:hover:bg-white/10'
          }`}
        >
          {t('suggestions.modeList')}
        </button>
        <button
          onClick={() => setMode('swipe')}
          className={`px-3 py-1.5 font-medium transition-colors ${
            mode === 'swipe'
              ? 'bg-purple-600 text-white'
              : 'text-black/60 dark:text-white/60 hover:bg-black/5 dark:hover:bg-white/10'
          }`}
        >
          {t('suggestions.modeSwipe')}
        </button>
      </div>

      {mode === 'swipe' ? (
        <SwipeDeck events={events} onFeedback={onFeedback} onToggleSave={onToggleSave} />
      ) : (
        <div className="flex flex-col gap-3">
          {events.map((event) => (
            <EventCard
              key={event.id}
              event={event}
              profile={profile}
              onFeedback={onFeedback}
              onToggleSave={onToggleSave}
              activeFilter={activeFilter}
              onTagClick={onTagClick}
            />
          ))}
        </div>
      )}
    </div>
  )
}
