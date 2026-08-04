import { useState } from 'react'
import { formatEventDate, formatRelativeTime, parseUtc } from '../dateUtils'
import { downloadIcs, googleCalendarUrl, googleMapsUrl } from '../ics'
import { useLanguage } from '../i18n'
import { computeMatchingTags } from '../matchTags'
import type { EventItem, InterestProfile, TagFilter } from '../types'

const langBadges: Record<string, string> = { 'zh-Hant': '中', 'zh-Hans': '中', zh: '中' }
const langBadge = (lang: string) => langBadges[lang] ?? lang.split('-')[0].toUpperCase()

// Real event posters exist for only ~13% of the catalog (hktdc; urbtix's
// feed doesn't carry them) -- this is the common case, not a rare
// fallback, so it's designed to look like a deliberate category treatment
// rather than a broken-image state. Hashing the category name (not the
// event id) means every card in the same category reads as visually
// related when you scroll past several of them.
const ART_GRADIENTS = [
  'from-[#4A3B8C] to-[#8F6FF0]',
  'from-[#C9781F] to-[#E3A75B]',
  'from-[#14795C] to-[#5FCBA3]',
  'from-[#8C3B5C] to-[#D97AA8]',
  'from-[#2E5C8C] to-[#6FA8E0]',
]

function categoryGradient(category: string): string {
  let hash = 0
  for (let i = 0; i < category.length; i++) hash = (hash * 31 + category.charCodeAt(i)) % 997
  return ART_GRADIENTS[hash % ART_GRADIENTS.length]
}

export function EventArt({ event, category }: { event: EventItem; category: string }) {
  const [broken, setBroken] = useState(false)
  if (event.image_url && !broken) {
    return (
      <img
        src={event.image_url}
        alt=""
        loading="lazy"
        onError={() => setBroken(true)}
        className="h-32 w-full object-cover"
      />
    )
  }
  return (
    <div className={`h-32 w-full bg-gradient-to-br ${categoryGradient(category)} flex items-end p-3`}>
      <svg width="30" height="30" viewBox="0 0 34 34" fill="none" className="opacity-80" aria-hidden="true">
        <rect x="4" y="14" width="4" height="16" fill="#fff" fillOpacity="0.55" />
        <rect x="11" y="8" width="4" height="22" fill="#fff" fillOpacity="0.75" />
        <rect x="18" y="17" width="4" height="13" fill="#fff" fillOpacity="0.55" />
        <rect x="25" y="4" width="4" height="26" fill="#fff" fillOpacity="0.9" />
      </svg>
    </div>
  )
}

export type MatchTier = 'high' | 'mid' | 'low'

export function matchTier(score: number): MatchTier {
  if (score >= 70) return 'high'
  if (score >= 40) return 'mid'
  return 'low'
}

export const TIER_STYLES: Record<MatchTier, string> = {
  high: 'bg-[#E1F3EB] text-[#14795C] dark:bg-[#1B3229] dark:text-[#5FCBA3]',
  mid: 'bg-[#FBEEDC] text-[#B06B12] dark:bg-[#332714] dark:text-[#E3A75B]',
  low: 'bg-black/5 text-black/50 dark:bg-white/10 dark:text-white/50',
}

function Tag({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-0.5 rounded-full transition-colors ${
        active
          ? 'bg-purple-600 text-white'
          : 'bg-black/5 dark:bg-white/10 hover:bg-black/10 dark:hover:bg-white/20'
      }`}
    >
      {label}
    </button>
  )
}

export default function EventCard({
  event,
  profile,
  onFeedback,
  onToggleSave,
  activeFilter,
  onTagClick,
}: {
  event: EventItem
  profile: InterestProfile | null
  onFeedback: (id: number, signal: 'up' | 'down' | 'none') => void
  onToggleSave: (id: number, saved: boolean) => void
  activeFilter: TagFilter | null
  onTagClick: (filter: TagFilter) => void
}) {
  const { lang, t } = useLanguage()
  const [showDetails, setShowDetails] = useState(false)
  // Clicking an already-active vote un-votes it, rather than needing a
  // separate control -- same toggle pattern as the match-details badge.
  const vote = (signal: 'up' | 'down') => onFeedback(event.id, event.user_signal === signal ? 'none' : signal)
  const matchingTags = event.llm_score !== null ? computeMatchingTags(event, profile) : []
  const statusStyles: Record<string, string> = {
    upcoming: 'bg-blue-500/10 text-blue-600 dark:text-blue-400',
    ongoing: 'bg-green-500/10 text-green-600 dark:text-green-400',
    past: 'bg-gray-500/10 text-gray-500 dark:text-gray-400',
    far_future: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  }

  // Which language leads depends on the user's selected display language,
  // not a fixed "native always wins" rule -- an event without a native
  // version (most HKTDC listings; that connector's source has no Chinese
  // data to offer) always falls back to English regardless of `lang`.
  const preferNative = lang === 'zh-Hant' && event.title_native
  const primaryTitle = preferNative ? event.title_native! : event.title
  const secondaryTitle = preferNative ? event.title : event.title_native
  const category = (preferNative && event.category_native) || event.category
  const venue = (preferNative && event.venue_name_native) || event.venue_name
  const location = (preferNative && event.location_native) || event.location

  // A saved event you're about to miss is exactly the kind of thing a
  // scrolling list has no follow-through for -- computed client-side from
  // data already on the card, no backend/push infra needed. Scoped to
  // "starting soon" specifically (not "ongoing, ending soon") since that's
  // the moment a nudge is actually actionable: before you've missed it.
  const hoursUntilStart = (parseUtc(event.start).getTime() - Date.now()) / 3_600_000
  const startingSoon = event.saved && event.status === 'upcoming' && hoursUntilStart >= 0 && hoursUntilStart <= 24

  return (
    <div className="rounded-lg border border-black/10 dark:border-white/10 overflow-hidden flex flex-col">
      <EventArt event={event} category={category} />
      <div className="p-4 flex flex-col gap-2">
      {startingSoon && (
        <div className="flex items-center gap-1.5 -mt-1 px-2 py-1 rounded-md bg-amber-500/10 text-amber-700 dark:text-amber-400 text-xs font-medium">
          <span aria-hidden="true">🔖</span>
          <span>{t('event.startingSoon', { time: formatRelativeTime(event.start, lang) })}</span>
        </div>
      )}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-base leading-snug flex items-center gap-1.5">
            {primaryTitle}
            {event.native_lang && (
              <span className="shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded bg-black/10 dark:bg-white/15 text-black/60 dark:text-white/60">
                {preferNative ? langBadge(event.native_lang) : 'EN'}
              </span>
            )}
          </h3>
          {secondaryTitle && <p className="text-sm text-black/50 dark:text-white/50">{secondaryTitle}</p>}
          <p className="text-sm text-black/60 dark:text-white/60">
            {formatEventDate(event.start, event.end, lang)} ·{' '}
            {venue ? (
              <a
                href={googleMapsUrl(venue, location)}
                target="_blank"
                rel="noopener noreferrer"
                title={t('event.viewOnMap')}
                className="hover:underline hover:text-black/80 dark:hover:text-white/80"
              >
                {venue}
              </a>
            ) : (
              t('event.venueTba')
            )}
            {location ? ` · ${location}` : ''}
          </p>
        </div>
        <div className="shrink-0 flex items-center gap-1.5">
          <span className={`text-xs font-medium px-2 py-1 rounded-full ${statusStyles[event.status]}`}>
            {t(`status.${event.status}`)}
          </span>
          <button
            onClick={() => onToggleSave(event.id, !event.saved)}
            aria-pressed={event.saved}
            aria-label={event.saved ? t('event.unsave') : t('event.save')}
            title={event.saved ? t('event.unsave') : t('event.save')}
            className={`w-7 h-7 rounded-full text-base transition-colors ${
              event.saved
                ? 'bg-amber-500/20 ring-2 ring-amber-500/60'
                : 'hover:bg-black/5 dark:hover:bg-white/10'
            }`}
          >
            {event.saved ? '🔖' : '📑'}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap text-xs">
        <Tag
          label={category}
          active={activeFilter?.type === 'category' && activeFilter.value === event.category}
          onClick={() => onTagClick({ type: 'category', value: event.category })}
        />
        <Tag
          label={event.source}
          active={activeFilter?.type === 'source' && activeFilter.value === event.source}
          onClick={() => onTagClick({ type: 'source', value: event.source })}
        />
        {event.llm_score !== null ? (
          <button
            onClick={() => setShowDetails((v) => !v)}
            aria-expanded={showDetails}
            className={`px-2 py-0.5 rounded-full font-medium transition-colors ${TIER_STYLES[matchTier(event.llm_score)]} ${
              showDetails ? 'ring-2 ring-current/40' : 'hover:brightness-95 dark:hover:brightness-110'
            }`}
          >
            {t(`event.matchTier.${matchTier(event.llm_score)}`)} ·{' '}
            <span className="font-display">{Math.round(event.llm_score)}</span> {showDetails ? '▴' : '▾'}
          </button>
        ) : (
          <span
            className="px-2 py-0.5 rounded-full font-medium border border-dashed border-black/15 dark:border-white/20 text-black/40 dark:text-white/40"
            title={t('event.matchUnscoredHint')}
          >
            {t('event.matchUnscored')}
          </span>
        )}
      </div>

      {showDetails && (event.why_match || matchingTags.length > 0) && (
        <div className="flex flex-col gap-1.5 rounded-md bg-black/[0.03] dark:bg-white/[0.05] p-2.5">
          {event.why_match && (
            <p className="text-sm italic text-black/70 dark:text-white/70">"{event.why_match}"</p>
          )}
          {matchingTags.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-black/40 dark:text-white/40">{t('event.matchedOn')}</span>
              {matchingTags.map((tag) => (
                <span
                  key={tag}
                  className="px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-700 dark:text-purple-300"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-between mt-1">
        <div className="flex items-center gap-3">
          {event.source_url ? (
            <a
              href={event.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
            >
              {t('event.viewSource')}
            </a>
          ) : (
            <span />
          )}
          <button
            onClick={() =>
              window.open(
                googleCalendarUrl(event, primaryTitle, [venue, location].filter(Boolean).join(', ')),
                '_blank',
                'noopener,noreferrer',
              )
            }
            className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
          >
            {t('event.addToCalendar')}
          </button>
          <button
            onClick={() => downloadIcs(event, primaryTitle, [venue, location].filter(Boolean).join(', '))}
            className="text-xs text-black/40 dark:text-white/40 hover:underline"
            title={t('event.addToCalendarIcs')}
          >
            .ics
          </button>
        </div>
        <div className="flex gap-1">
          <button
            onClick={() => vote('up')}
            aria-pressed={event.user_signal === 'up'}
            className={`w-8 h-8 rounded-full text-lg transition-colors ${
              event.user_signal === 'up'
                ? 'bg-green-500/20 ring-2 ring-green-500/60'
                : 'hover:bg-black/5 dark:hover:bg-white/10'
            }`}
            aria-label={t('event.moreLikeThis')}
            title={t('event.moreLikeThis')}
          >
            👍
          </button>
          <button
            onClick={() => vote('down')}
            aria-pressed={event.user_signal === 'down'}
            className={`w-8 h-8 rounded-full text-lg transition-colors ${
              event.user_signal === 'down'
                ? 'bg-red-500/20 ring-2 ring-red-500/60'
                : 'hover:bg-black/5 dark:hover:bg-white/10'
            }`}
            aria-label={t('event.lessLikeThis')}
            title={t('event.lessLikeThis')}
          >
            👎
          </button>
        </div>
      </div>
      </div>
    </div>
  )
}
