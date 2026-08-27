import { useEffect, useRef, useState } from 'react'
import {
  getDebugStatus,
  getEvent,
  getInsights,
  getInterests,
  listEvents,
  listSaved,
  runIngest,
  saveEvent,
  searchEvents,
  setInterests,
  submitFeedback,
  unsaveEvent,
} from './api'
import AskBar from './components/AskBar'
import DisclaimerView from './components/DisclaimerView'
import EventCard from './components/EventCard'
import EventDetailModal from './components/EventDetailModal'
import Footer from './components/Footer'
import InsightsPanel from './components/InsightsPanel'
import InterestForm from './components/InterestForm'
import RerankStatusBar from './components/RerankStatusBar'
import SkeletonCard from './components/SkeletonCard'
import SuggestionsView from './components/SuggestionsView'
import TimelineView from './components/TimelineView'
import { countKeywordMatches, filterEvents } from './filterEvents'
import { downloadIcsMultiple } from './ics'
import { canonicalKey } from './keywordMatch'
import { useLanguage, type Lang } from './i18n'
import type { DebugStatus, EventItem, EventStatus, Insights, InterestProfile, TagFilter } from './types'
import { parseUtc, startOfDay } from './dateUtils'

type Tab = 'suggestions' | 'events' | 'timeline' | 'saved' | 'insights' | 'disclaimer'
type SortBy = 'score' | 'date'
type DatePreset = 'all' | 'weekend' | '7days' | 'month'

function inDatePreset(ev: EventItem, preset: DatePreset): boolean {
  if (preset === 'all') return true
  const today = startOfDay(new Date())

  const start = startOfDay(parseUtc(ev.start))
  const startDays = Math.round((start.getTime() - today.getTime()) / 86400000)

  let endDays = startDays
  if (ev.end) {
    const end = startOfDay(parseUtc(ev.end))
    endDays = Math.round((end.getTime() - today.getTime()) / 86400000)
  }

  // Include if event hasn't ended yet (end >= today) and either
  // start or end falls within the preset range.
  const ongoing = endDays >= 0
  const startOk = startDays >= 0 && (
    (preset === '7days' && startDays <= 7) ||
    (preset === 'month' && startDays <= 30)
  )
  const endOk = ongoing && (
    (preset === '7days' && endDays <= 7) ||
    (preset === 'month' && endDays <= 30)
  )

  if (preset === '7days' || preset === 'month') return startOk || endOk

  // weekend: next Sat (6) / Sun (0) in HKT — same approach as the
  // original: get UTC day of HKT midnight, adjust for UTC-8 offset.
  const todayUtcDow = today.getUTCDay()
  const todayHktDow = (todayUtcDow + 1) % 7
  const daysToSat = (6 - todayHktDow + 7) % 7
  const satOffset = daysToSat === 0 ? 0 : daysToSat
  const inWeekend = (d: number) => d >= satOffset && d <= satOffset + 1
  return inWeekend(startDays) || (ongoing && inWeekend(endDays))
}
// Suggestions leads -- "what should I actually go to" is the question a
// returning user has, ahead of browsing everything ongoing/upcoming/past.
// Ongoing/Upcoming/Past used to be three separate top-level tabs, but
// they're really one dataset with a status filter, not three different
// views -- collapsed into one "Events" tab with a segmented filter inside
// it (see eventsStatusFilter below), the same pattern Suggestions already
// uses for its list/swipe toggle. Cut the tab bar from 7 entries to 5,
// which matters most on mobile where it was previously wide enough to
// force wrapping/scrolling on its own.
const TABS: Tab[] = ['suggestions', 'events', 'timeline', 'saved', 'insights', 'disclaimer']
const EVENT_STATUS_FILTERS: EventStatus[] = ['ongoing', 'upcoming', 'far_future', 'past']
const TAB_SET: Set<string> = new Set(TABS)

// B1 -- hash routing. Tab / status filter / sort / tag filter / open-modal
// event id all live in the URL, so a view is bookmarkable/shareable and
// the browser's Back/Forward buttons work across tab changes and modal
// opens instead of leaving the site. Hash-based (not the History API's
// path mode) so it needs zero server-side fallback config.
type ParsedRoute = {
  tab?: Tab
  status?: EventStatus
  sort?: SortBy
  tagType?: 'category' | 'source'
  tagValue?: string
  eventId?: number
}

function parseHash(): ParsedRoute {
  if (typeof window === 'undefined') return {}
  const raw = window.location.hash.replace(/^#\/?/, '')
  if (!raw) return {}
  const [pathPart, queryPart] = raw.split('?')
  const segments = pathPart.split('/').filter(Boolean)
  const params = new URLSearchParams(queryPart ?? '')
  const out: ParsedRoute = {}
  const first = segments[0]
  if (first && TAB_SET.has(first)) out.tab = first as Tab
  if (first === 'events') {
    const status = segments[1] as EventStatus | undefined
    if (status && EVENT_STATUS_FILTERS.includes(status)) out.status = status
  }
  const sort = params.get('sort')
  if (sort === 'score' || sort === 'date') out.sort = sort
  const tag = params.get('tag')
  if (tag) {
    const idx = tag.indexOf(':')
    const type = idx === -1 ? '' : tag.slice(0, idx)
    const value = idx === -1 ? '' : decodeURIComponent(tag.slice(idx + 1))
    if ((type === 'category' || type === 'source') && value) {
      out.tagType = type
      out.tagValue = value
    }
  }
  const eventParam = params.get('event')
  if (eventParam && /^\d+$/.test(eventParam)) out.eventId = Number(eventParam)
  return out
}

function buildHash(
  tab: Tab,
  status: EventStatus,
  sortBy: SortBy,
  tagFilter: TagFilter | null,
  eventId: number | null,
): string {
  let path = `/${tab}`
  if (tab === 'events') path += `/${status}`
  const params = new URLSearchParams()
  if (tab === 'events' && sortBy !== 'score') params.set('sort', sortBy)
  if (tagFilter) params.set('tag', `${tagFilter.type}:${encodeURIComponent(tagFilter.value)}`)
  if (eventId != null) params.set('event', String(eventId))
  const qs = params.toString()
  return `#${path}${qs ? `?${qs}` : ''}`
}

function applyHash(hash: string, mode: 'replace' | 'push'): void {
  if (window.location.hash === hash) return
  if (mode === 'push') window.history.pushState(null, '', hash)
  else window.history.replaceState(null, '', hash)
}

// Below this, a "match" isn't confident enough to call out as a
// suggestion -- every event still gets a full listing in its own
// ongoing/upcoming tab regardless, this only gates the curated view.
const HIGH_MATCH_THRESHOLD = 70

// Collapses terms that stem to the same tokens (e.g. "book fair" and "book
// fairs" -- one from the LLM-derived categories, one from the user's own
// keywords) into a single chip. First occurrence wins, so callers order
// `terms` by which source they'd rather display.
function dedupeTerms(terms: string[]): string[] {
  const seen = new Map<string, string>()
  for (const term of terms) {
    const trimmed = term.trim()
    if (!trimmed) continue
    const key = canonicalKey(trimmed)
    if (key && !seen.has(key)) seen.set(key, trimmed)
  }
  return Array.from(seen.values())
}

// 'score' matches the order the backend already returns (highest match
// first, unscored last) -- made explicit here rather than left implicit,
// since 'date' needs an actual client-side sort and the two need to be
// interchangeable from the same list. Nulls sort last in both directions:
// an unscored event has no meaningful "match" to rank by, so it belongs
// at the bottom of a score-sorted list the same way it would if the
// backend's own ordering were left untouched.
function sortEvents(events: EventItem[], sortBy: SortBy): EventItem[] {
  const sorted = [...events]
  if (sortBy === 'date') {
    sorted.sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime())
  } else {
    sorted.sort((a, b) => (b.llm_score ?? -1) - (a.llm_score ?? -1))
  }
  return sorted
}

function App() {
  const { lang, setLang, t } = useLanguage()
  // B1: cold-load state is seeded from the URL hash, so a deep link like
  // #/events/upcoming?sort=date&event=42 restores exactly that view.
  const [initialRoute] = useState(parseHash)
  const [profile, setProfile] = useState<InterestProfile | null>(null)
  const [tab, setTab] = useState<Tab>(initialRoute.tab ?? 'suggestions')
  const [eventsStatusFilter, setEventsStatusFilter] = useState<EventStatus>(initialRoute.status ?? 'ongoing')
  const [sortBy, setSortBy] = useState<SortBy>(initialRoute.sort ?? 'score')
  const [events, setEvents] = useState<EventItem[]>([])
  const [loading, setLoading] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [status, setStatus] = useState('')
  const [insightsRefreshSignal, setInsightsRefreshSignal] = useState(0)
  const [tagFilter, setTagFilter] = useState<TagFilter | null>(
    initialRoute.tagType && initialRoute.tagValue ? { type: initialRoute.tagType, value: initialRoute.tagValue } : null,
  )
  const [keywordFilter, setKeywordFilter] = useState('')
  const [filterOpen, setFilterOpen] = useState(false)
  const [datePreset, setDatePreset] = useState<DatePreset>('all')

  // A4: global search across the whole catalog (server-side), distinct
  // from the client-side keyword filter which only narrows the loaded tab.
  const [globalQuery, setGlobalQuery] = useState('')
  const [searchResults, setSearchResults] = useState<EventItem[] | null>(null)
  const [searching, setSearching] = useState(false)

  // B2: card lists render in chunks; reset whenever what's being listed changes.
  const PAGE_SIZE = 30
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  // A3: "new since your last visit" badge on the Suggestions tab --
  // client-side only, no accounts/infra. The timestamp is written the
  // moment you actually visit Suggestions, so it means "unseen picks".
  const LAST_VISIT_KEY = 'event-radar-last-visit'
  const [lastVisitTs] = useState(() => Number(window.localStorage.getItem(LAST_VISIT_KEY) ?? 0))
  const [suggestionsSeen, setSuggestionsSeen] = useState(false)
  const [timelineEvents, setTimelineEvents] = useState<EventItem[]>([])
  const [savedEvents, setSavedEvents] = useState<EventItem[]>([])
  const [debugStatus, setDebugStatus] = useState<DebugStatus | null>(null)
  const [quotaInsights, setQuotaInsights] = useState<Insights | null>(null)

  // The one shared destination for "show me this event's own card" from
  // anywhere that isn't already a card list -- Timeline's Gantt bars and
  // the ask box's referenced events. A modal rather than switching tabs,
  // since the target event isn't guaranteed to be in whatever list the
  // current tab has loaded. Opening from an id (ask box) fetches that one
  // event fresh; opening from an already-loaded EventItem (Timeline, which
  // has the full object in hand already) skips the round trip entirely.
  const [modalOpen, setModalOpen] = useState(false)
  const [modalEvent, setModalEvent] = useState<EventItem | null>(null)
  const [modalLoading, setModalLoading] = useState(false)

  const openEventModal = async (eventOrId: EventItem | number) => {
    setModalOpen(true)
    if (typeof eventOrId === 'number') {
      setModalLoading(true)
      setModalEvent(null)
      try {
        setModalEvent(await getEvent(eventOrId))
      } catch {
        setModalEvent(null)
      } finally {
        setModalLoading(false)
      }
    } else {
      setModalEvent(eventOrId)
    }
  }
  const closeEventModal = () => {
    setModalOpen(false)
    setModalEvent(null)
  }

  // Deliberately doesn't touch `loading` itself -- it's called both on tab
  // switch (where a loading state makes sense) and from silent background
  // refreshes/polls (where flashing "Loading…" every 15s would be a bug,
  // not a feature). Callers that want the spinner wrap this themselves.
  const loadEvents = async (s: EventStatus) => {
    setEvents(await listEvents(s))
  }

  // Read inside the poll callback below instead of closing over `tab`
  // directly -- a setInterval callback captures whatever `tab` was at the
  // moment it was created, so without this it would keep refreshing
  // whichever tab you saved *from*, even after you'd switched away.
  const tabRef = useRef(tab)
  useEffect(() => {
    tabRef.current = tab
  }, [tab])
  // Same stale-closure reason as tabRef -- pollForFreshScores's interval
  // callback is created once and lives for ~2.5 min, so it needs a way to
  // read the *current* status filter rather than whatever it was when the
  // poll started.
  const eventsStatusFilterRef = useRef(eventsStatusFilter)
  useEffect(() => {
    eventsStatusFilterRef.current = eventsStatusFilter
  }, [eventsStatusFilter])
  const pollTimerRef = useRef<number | null>(null)

  const refetchActiveTab = async (activeTab: Tab) => {
    if (activeTab === 'insights' || activeTab === 'disclaimer') return
    if (activeTab === 'timeline' || activeTab === 'suggestions') {
      const [ongoing, upcoming] = await Promise.all([listEvents('ongoing'), listEvents('upcoming')])
      setTimelineEvents([...ongoing, ...upcoming])
    } else if (activeTab === 'saved') {
      setSavedEvents(await listSaved())
    } else if (activeTab === 'events') {
      await loadEvents(eventsStatusFilterRef.current)
    }
  }

  // A rerank triggered by a save or Refresh runs as an async background job
  // on the server -- several sequential LLM calls, up to ~2 minutes for the
  // full catalog. Refetching once right after triggering it just shows
  // whatever was there before (this was the actual bug: scores looked
  // "stuck" because nothing ever re-fetched once the rerank actually
  // finished). Poll a few times over that window instead of requiring a
  // manually-remembered second Refresh click.
  const pollForFreshScores = () => {
    if (pollTimerRef.current !== null) window.clearInterval(pollTimerRef.current)
    let attempts = 0
    const maxAttempts = 10 // ~2.5 min at 15s apart
    pollTimerRef.current = window.setInterval(() => {
      attempts += 1
      refetchActiveTab(tabRef.current)
      setInsightsRefreshSignal((n) => n + 1)
      if (attempts >= maxAttempts && pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
        setStatus('')
      }
    }, 15000)
  }

  useEffect(() => {
    return () => {
      if (pollTimerRef.current !== null) window.clearInterval(pollTimerRef.current)
    }
  }, [])

  // Runs continuously, independent of pollForFreshScores above -- that one
  // is bounded (~2.5 min, only after a save/refresh) and refetches the
  // heavier event list; this one is a cheap status read that should stay
  // current any time the app is open, not just right after you triggered
  // something, so the "last rerank" line is trustworthy even if you just
  // arrived on the page.
  // Also detects when a background (scheduled) rerank finishes and
  // auto-refreshes the active tab, so a tab left open picks up fresh scores
  // without requiring the bounded 2.5-min poll window pollForFreshScores
  // sets up (which only ever runs after a user's own save/refresh action).
  //
  // Compares last_rerank.at (a timestamp that only ever changes when a
  // rerank actually completes) rather than watching rerank.in_progress for
  // a true→false transition -- the previous version did that, and real
  // scheduled reranks in this app's own logs regularly finish in well under
  // 10 seconds (e.g. a "nothing changed" pass, a few hundred ms), so the
  // 10s poll interval could easily land on two consecutive "false" reads
  // and never observe the brief "true" in between, silently never
  // refreshing at all. A timestamp comparison can't miss a fast rerank the
  // same way a boolean-transition check can.
  const lastRerankAtRef = useRef<string | null>(null)
  useEffect(() => {
    const fetchStatus = () => {
      getDebugStatus().then((ds) => {
        setDebugStatus(ds)
        const at = ds.last_rerank?.at ?? null
        if (lastRerankAtRef.current !== null && at !== null && at !== lastRerankAtRef.current) {
          refetchActiveTab(tabRef.current)
          setInsightsRefreshSignal((n) => n + 1)
        }
        lastRerankAtRef.current = at
      }).catch(() => {})
      getInsights().then(setQuotaInsights).catch(() => {})
    }
    fetchStatus()
    const id = window.setInterval(fetchStatus, 10000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    getInterests().then(setProfile)
  }, [])

  // B1: reflect tab/filter state in the URL (replace -- these are view
  // tweaks, not navigation). Modal event param handled by its own effect
  // below, which pushes a history entry so Back closes the modal.
  useEffect(() => {
    applyHash(buildHash(tab, eventsStatusFilter, sortBy, tagFilter, modalOpen ? (modalEvent?.id ?? null) : null), 'replace')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, eventsStatusFilter, sortBy, tagFilter])

  // B1: opening the modal adds a history entry; closing it strips the
  // ?event= param so a refresh doesn't re-open it.
  const modalEventId = modalEvent?.id ?? null
  useEffect(() => {
    if (modalOpen) {
      applyHash(buildHash(tab, eventsStatusFilter, sortBy, tagFilter, modalEventId), 'push')
    } else if (window.location.hash.includes('event=')) {
      applyHash(buildHash(tab, eventsStatusFilter, sortBy, tagFilter, null), 'replace')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modalOpen])

  // B1: Back/Forward (or a manual hash edit) re-derives all view state
  // from the URL, including opening/closing the deep-linked modal.
  useEffect(() => {
    const onHashChange = () => {
      const r = parseHash()
      if (r.tab) setTab(r.tab)
      if (r.status) setEventsStatusFilter(r.status)
      if (r.sort) setSortBy(r.sort)
      setTagFilter(r.tagType && r.tagValue ? { type: r.tagType, value: r.tagValue } : null)
      if (r.eventId != null) {
        openEventModal(r.eventId)
      } else {
        setModalLoading(false)
        setModalEvent(null)
        setModalOpen(false)
      }
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // B1: a cold load whose URL carries ?event=NN opens that event's modal.
  useEffect(() => {
    if (initialRoute.eventId != null) openEventModal(initialRoute.eventId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // A4: debounced global search. A sequence counter guards against a slow
  // earlier response landing after a newer one and clobbering results.
  const searchSeq = useRef(0)
  useEffect(() => {
    const q = globalQuery.trim()
    if (q.length < 2) {
      setSearchResults(null)
      setSearching(false)
      return
    }
    setSearching(true)
    const seq = ++searchSeq.current
    const timer = window.setTimeout(() => {
      searchEvents(q)
        .then((res) => {
          if (searchSeq.current === seq) setSearchResults(res)
        })
        .catch(() => {
          if (searchSeq.current === seq) setSearchResults([])
        })
        .finally(() => {
          if (searchSeq.current === seq) setSearching(false)
        })
    }, 300)
    return () => window.clearTimeout(timer)
  }, [globalQuery])

  useEffect(() => {
    setVisibleCount(PAGE_SIZE)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, eventsStatusFilter, tagFilter, keywordFilter, globalQuery, datePreset])

  useEffect(() => {
    if (tab === 'insights') {
      setInsightsRefreshSignal((n) => n + 1)
      return
    }
    if (tab === 'disclaimer') return
    setLoading(true)
    refetchActiveTab(tab).finally(() => setLoading(false))
    // eventsStatusFilter only ever changes while tab === 'events' (the
    // segmented control that changes it only renders there), so adding it
    // here doesn't cause a refetch on unrelated tabs -- it's what makes
    // switching Ongoing/Upcoming/Past *within* the Events tab actually load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, eventsStatusFilter])

  const handleSaveInterests = async (rawText: string, excludedKeywords: string[]) => {
    const updated = await setInterests(rawText, excludedKeywords)
    setProfile(updated)
    setStatus(t('status.savedReranking'))
    pollForFreshScores()
  }

  const handleRefresh = async () => {
    setIngesting(true)
    setStatus(t('status.fetching'))
    try {
      const summary = await runIngest()
      setStatus(t('status.fetchedSummary', { fetched: summary.fetched, new: summary.new, updated: summary.updated }))
      await refetchActiveTab(tab)
      setInsightsRefreshSignal((n) => n + 1)
      pollForFreshScores()
    } finally {
      setIngesting(false)
    }
  }

  const handleFeedback = async (id: number, signal: 'up' | 'down' | 'none') => {
    await submitFeedback(id, signal)
    // Updates in place rather than removing the card -- the vote itself is
    // now visible on the card (see EventCard), so there's no need to yank a
    // 👎'd event out of the list; that used to happen with zero explanation
    // and no way to undo a misclick.
    const patch = (list: EventItem[]) =>
      list.map((e) => (e.id === id ? { ...e, user_signal: signal === 'none' ? null : signal } : e))
    setEvents(patch)
    setTimelineEvents(patch)
    setSavedEvents(patch)
    setModalEvent((prev) => (prev && patch([prev])[0]) || prev)
  }

  const handleToggleSave = async (id: number, shouldSave: boolean) => {
    await (shouldSave ? saveEvent(id) : unsaveEvent(id))
    const patch = (list: EventItem[]) => list.map((e) => (e.id === id ? { ...e, saved: shouldSave } : e))
    setEvents(patch)
    setTimelineEvents(patch)
    // Unsaving drops it from the Saved tab's own list immediately (that IS
    // the point of the action there); saving a not-yet-loaded item into that
    // list isn't needed -- switching to the tab re-fetches it fresh anyway.
    setSavedEvents((prev) => (shouldSave ? prev.map((e) => (e.id === id ? { ...e, saved: true } : e)) : prev.filter((e) => e.id !== id)))
    setModalEvent((prev) => (prev && prev.id === id ? { ...prev, saved: shouldSave } : prev))
  }

  const handleTagClick = (f: TagFilter) => {
    setTagFilter((prev) => (prev && prev.type === f.type && prev.value === f.value ? null : f))
  }

  const handleTabClick = (tabKey: Tab) => {
    setTab(tabKey)
    if (tabKey === 'suggestions' && !suggestionsSeen) {
      setSuggestionsSeen(true)
      window.localStorage.setItem(LAST_VISIT_KEY, String(Date.now()))
    }
  }

  const handleExportSaved = () => {
    downloadIcsMultiple(
      savedEvents.map((e) => ({
        event: e,
        title: (lang === 'zh-Hant' && e.title_native) || e.title,
        location: [
          (lang === 'zh-Hant' && e.venue_name_native) || e.venue_name,
          (lang === 'zh-Hant' && e.location_native) || e.location,
        ]
          .filter(Boolean)
          .join(', '),
      })),
      'event-radar-saved.ics',
    )
  }

  const handleInterestChipClick = (term: string) => {
    setKeywordFilter((prev) => (prev.toLowerCase() === term.toLowerCase() ? '' : term))
  }

  // Only surface a suggested-keyword chip if it actually narrows things down
  // to more than one event -- a term that matches 0 or 1 events isn't a
  // useful shortcut and just clutters the row. Counted against whatever the
  // active tab already has loaded (timeline/suggestions share one list).
  const activeEventList = tab === 'timeline' || tab === 'suggestions' ? timelineEvents : tab === 'saved' ? savedEvents : events
  const interestTerms = profile ? dedupeTerms([...profile.keywords, ...profile.categories]) : []
  const suggestedKeywords = interestTerms.filter((term) => countKeywordMatches(activeEventList, term) > 1)
  // Every distinct category currently loaded, not just the ones an event
  // card happens to be visible for -- the whole point is making a category
  // like "Film" clickable even when nothing in it has scored high enough
  // to appear near the top of a score-sorted list yet. Unlike
  // suggestedKeywords above, deliberately NOT threshold-filtered: a
  // category with only one event is still worth being able to jump to.
  const availableCategories = Array.from(new Set(activeEventList.map((e) => e.category))).sort()

  const baseDisplayedEvents = sortEvents(filterEvents(tab === 'saved' ? savedEvents : events, tagFilter, keywordFilter), sortBy)
  const displayedEvents = baseDisplayedEvents.filter((e) => inDatePreset(e, datePreset))
  const baseTimelineEvents = filterEvents(timelineEvents, tagFilter, keywordFilter)
  const displayedTimelineEvents = baseTimelineEvents.filter((e) => inDatePreset(e, datePreset))
  // Ongoing+upcoming, high-confidence matches only, best score first --
  // the "what should I actually go to" view. Everything below the
  // threshold is still fully browsable in Ongoing/Upcoming, just not
  // singled out here.
  const displayedSuggestions = [...displayedTimelineEvents]
    .filter((e) => e.llm_score != null && e.llm_score >= HIGH_MATCH_THRESHOLD)
    .sort((a, b) => (b.llm_score ?? 0) - (a.llm_score ?? 0))
  const cardListEvents = tab === 'suggestions' ? displayedSuggestions : displayedEvents
  const emptyMessage =
    tagFilter || keywordFilter
      ? t('empty.noMatch')
      : tab === 'suggestions'
        ? t('empty.noSuggestions')
        : tab === 'saved'
          ? t('empty.noSaved')
          : t('empty.noEvents')

  // A3: suggestions created in the catalog after the visitor's last
  // recorded visit -- surfaced as a small count badge on the Suggestions
  // tab until it's actually visited.
  const newSuggestionCount = suggestionsSeen
    ? 0
    : displayedSuggestions.filter((e) => Date.parse(e.created_at) > lastVisitTs).length

  // B2: chunked rendering for every long card list (Events / Saved /
  // Suggestions list mode). Timeline keeps its full dataset -- it's a chart.
  const paginatedCardList = cardListEvents.slice(0, visibleCount)
  const remainingCards = Math.max(0, cardListEvents.length - visibleCount)
  const loadMoreButton =
    remainingCards > 0 ? (
      <button
        onClick={() => setVisibleCount((n) => n + PAGE_SIZE)}
        className="self-center px-4 py-2 rounded-md border border-black/10 dark:border-white/10 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10"
      >
        {t('list.loadMore', { n: remainingCards })}
      </button>
    ) : null

  // A4: search results replace the active tab's own content while active.
  const trimmedQuery = globalQuery.trim()
  const searchActive = trimmedQuery.length >= 2 && (searching || searchResults !== null)

  // The Timeline/Gantt view wants the full browser width to be readable
  // (it's a horizontally-scrolling chart, not prose) -- everything else
  // stays in the narrow reading-width column. Header/interests/tabs/filters
  // always stay narrow; only the content area below switches width.
  const contentWidthClass = tab === 'timeline' ? 'w-full px-4' : 'max-w-3xl mx-auto w-full px-4'

  return (
    <div className="py-8 flex flex-col gap-6">
      <div className="max-w-3xl mx-auto w-full px-4 flex flex-col gap-6">
        <header className="flex items-center justify-between gap-2 sm:gap-3">
          <div>
            <h1 className="font-display text-xl sm:text-2xl font-bold">{t('app.title')}</h1>
            <p className="text-xs sm:text-sm text-black/60 dark:text-white/60">{t('app.tagline')}</p>
            <p className="hidden sm:block text-xs text-black/40 dark:text-white/40">{t('app.taglineNote')}</p>
          </div>
          <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
            <div className="inline-flex rounded-md border border-black/10 dark:border-white/10 overflow-hidden text-sm">
              {(['zh-Hant', 'en'] as Lang[]).map((l) => (
                <button
                  key={l}
                  onClick={() => setLang(l)}
                  className={`px-2 sm:px-2.5 py-1.5 font-medium ${
                    lang === l
                      ? 'bg-purple-600 text-white'
                      : 'bg-transparent text-black/60 dark:text-white/60 hover:bg-black/5 dark:hover:bg-white/10'
                  }`}
                >
                  {l === 'zh-Hant' ? t('lang.zh') : t('lang.en')}
                </button>
              ))}
            </div>
            {/* B5: on narrow screens the full label wrapped the header onto
                two rows -- an icon-only button keeps it one row; the label
                stays for screen readers and wider viewports. */}
            <button
              onClick={handleRefresh}
              disabled={ingesting}
              aria-label={ingesting ? t('refreshing') : t('refresh')}
              className="px-3 py-2 rounded-md bg-black text-white dark:bg-white dark:text-black text-sm font-medium disabled:opacity-50"
            >
              <span aria-hidden="true" className="sm:hidden">{ingesting ? '…' : '↻'}</span>
              <span className="hidden sm:inline">{ingesting ? t('refreshing') : t('refresh')}</span>
            </button>
          </div>
        </header>

        <RerankStatusBar debugStatus={debugStatus} insights={quotaInsights} />

        {status && <p className="text-sm text-black/50 dark:text-white/50">{status}</p>}

        <InterestForm profile={profile} onSave={handleSaveInterests} />

        <AskBar onOpenEvent={openEventModal} />
      </div>

      {/* Sticky controls — stays pinned while scrolling long lists (outside the narrow container so sticky isn't clipped by its parent's bounds) */}
      <div className="sticky top-0 z-20 bg-white/95 dark:bg-black/95 backdrop-blur supports-[backdrop-filter]:bg-white/80 supports-[backdrop-filter]:dark:bg-black/80 border-y border-black/10 dark:border-white/10">
        <div className="max-w-3xl mx-auto w-full px-4 py-2 flex flex-col gap-2">
          <div className="flex gap-1 overflow-x-auto overflow-y-hidden -mb-2 -mx-1 px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {TABS.map((tabKey) => (
              <button
                key={tabKey}
                onClick={() => handleTabClick(tabKey)}
                className={`px-3 py-2 text-sm font-medium border-b-2 whitespace-nowrap shrink-0 -mb-px ${
                  tab === tabKey
                    ? 'border-purple-600 text-purple-600 dark:text-purple-400'
                    : 'border-transparent text-black/50 dark:text-white/50'
                }`}
              >
                {t(`tab.${tabKey}`)}
                {tabKey === 'suggestions' && newSuggestionCount > 0 && (
                  <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-purple-600 text-white text-[10px] font-semibold align-middle">
                    {t('tab.newBadge', { n: newSuggestionCount })}
                  </span>
                )}
              </button>
            ))}
          </div>

          {tab === 'events' && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex self-start rounded-md border border-black/10 dark:border-white/10 overflow-hidden text-sm">
                {EVENT_STATUS_FILTERS.map((status) => (
                  <button
                    key={status}
                    onClick={() => setEventsStatusFilter(status)}
                    className={`px-3 py-1.5 font-medium transition-colors ${
                      eventsStatusFilter === status
                        ? 'bg-purple-600 text-white'
                        : 'text-black/60 dark:text-white/60 hover:bg-black/5 dark:hover:bg-white/10'
                    }`}
                  >
                    {t(`tab.${status}`)}
                  </button>
                ))}
              </div>
              <div className="inline-flex self-start rounded-md border border-black/10 dark:border-white/10 overflow-hidden text-sm">
                {(['score', 'date'] as SortBy[]).map((s) => (
                  <button
                    key={s}
                    onClick={() => setSortBy(s)}
                    className={`px-3 py-1.5 font-medium transition-colors ${
                      sortBy === s
                        ? 'bg-purple-600 text-white'
                        : 'text-black/60 dark:text-white/60 hover:bg-black/5 dark:hover:bg-white/10'
                    }`}
                  >
                    {t(`sort.${s}`)}
                  </button>
                ))}
              </div>
            </div>
          )}

          {tab !== 'insights' && tab !== 'disclaimer' && (
            <div className="flex flex-col gap-2">
              {(() => {
                const activeCount = (tagFilter ? 1 : 0) + (keywordFilter ? 1 : 0) + (datePreset !== 'all' ? 1 : 0)
                return (
                  <>
                    <div className="flex gap-2 items-center">
                      <div className="relative flex-1 max-w-[320px]">
                        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/30 text-sm" aria-hidden="true">⌕</span>
                        <input
                          type="search"
                          value={globalQuery}
                          onChange={(e) => setGlobalQuery(e.target.value)}
                          placeholder={t('search.placeholder')}
                          aria-label={t('search.placeholder')}
                          className="w-full rounded-full border border-black/10 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] pl-9 pr-8 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500/20 focus:border-purple-300"
                        />
                        {globalQuery && (
                          <button
                            onClick={() => setGlobalQuery('')}
                            aria-label={t('search.clear')}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-black/40 dark:text-white/40 hover:opacity-70"
                          >
                            ×
                          </button>
                        )}
                      </div>
                      <button
                        onClick={() => setFilterOpen((v) => !v)}
                        aria-expanded={filterOpen}
                        className="shrink-0 inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-full border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10"
                      >
                        {t('filter.toggle')} {activeCount > 0 && <span className="px-1.5 py-0.5 rounded-full bg-purple-600 text-white text-[10px]">{activeCount}</span>} <span aria-hidden="true">{filterOpen ? '▴' : '▾'}</span>
                      </button>
                    </div>
                    {filterOpen && (
                      <div className="rounded-lg border border-black/10 dark:border-white/10 bg-black/[0.02] dark:bg-white/[0.03] p-3 flex flex-col gap-3">
                        <div className="relative">
                          <input
                            type="text"
                            value={keywordFilter}
                            onChange={(e) => setKeywordFilter(e.target.value)}
                            placeholder={t('filter.placeholder')}
                            className="w-full rounded-md border border-black/10 dark:border-white/10 bg-white dark:bg-black px-3 py-2 pr-8 text-sm"
                          />
                          {keywordFilter && (
                            <button
                              onClick={() => setKeywordFilter('')}
                              aria-label={t('filter.clear')}
                              className="absolute right-2 top-1/2 -translate-y-1/2 text-black/40 dark:text-white/40 hover:opacity-70"
                            >
                              ×
                            </button>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center gap-1.5 text-xs">
                          <span className="text-black/40 dark:text-white/40">{t('filter.dateLabel')}</span>
                          {(['all', 'weekend', '7days', 'month'] as DatePreset[]).map((p) => (
                            <button
                              key={p}
                              onClick={() => setDatePreset(p)}
                              className={`px-2.5 py-1 rounded-full font-medium ${datePreset === p ? 'bg-purple-600 text-white' : 'bg-white dark:bg-black border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10'}`}
                            >
                              {t(`filter.date.${p}`)}
                            </button>
                          ))}
                        </div>

                        {suggestedKeywords.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5 text-xs">
                            <span className="text-black/40 dark:text-white/40">{t('filter.suggestedKeywords')}</span>
                            {suggestedKeywords.map((term) => (
                              <button
                                key={term}
                                onClick={() => handleInterestChipClick(term)}
                                className={`px-2 py-0.5 rounded-full ${keywordFilter.toLowerCase() === term.toLowerCase() ? 'bg-purple-600 text-white' : 'bg-white dark:bg-black border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10'}`}
                              >
                                {term}
                              </button>
                            ))}
                          </div>
                        )}

                        {availableCategories.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5 text-xs">
                            <span className="text-black/40 dark:text-white/40">{t('filter.categories')}</span>
                            {availableCategories.map((category) => (
                              <button
                                key={category}
                                onClick={() => handleTagClick({ type: 'category', value: category })}
                                className={`px-2 py-0.5 rounded-full flex items-center gap-1 ${tagFilter?.type === 'category' && tagFilter.value === category ? 'bg-purple-600 text-white' : 'bg-white dark:bg-black border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10'}`}
                              >
                                <span className={`w-2 h-2 rounded-full ${tagFilter?.type === 'category' && tagFilter.value === category ? 'bg-white/80' : 'bg-purple-500/60'}`} aria-hidden="true" />
                                {category}
                              </button>
                            ))}
                          </div>
                        )}

                        {tagFilter && (
                          <div className="flex items-center gap-2 text-sm">
                            <span className="text-black/50 dark:text-white/50">{t('filter.filteringBy')}</span>
                            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-purple-600 text-white">
                              {tagFilter.value}
                              <button onClick={() => setTagFilter(null)} aria-label={t('filter.clearTag')} className="hover:opacity-70">×</button>
                            </span>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )
              })()}
            </div>
          )}
        </div>
      </div>

      <div className={contentWidthClass}>
        {tab === 'insights' ? (
          <InsightsPanel refreshSignal={insightsRefreshSignal} />
        ) : tab === 'disclaimer' ? (
          <DisclaimerView debugStatus={debugStatus} />
        ) : searchActive ? (
          // A4: global-search results, rendered with the same card list so
          // feedback/save/open-detail all behave identically here.
          <div className="flex flex-col gap-3">
            {searching && searchResults === null ? (
              [0, 1, 2].map((i) => <SkeletonCard key={i} />)
            ) : searchResults !== null && searchResults.length === 0 ? (
              <p className="text-sm text-black/50 dark:text-white/50">{t('search.noResults', { q: trimmedQuery })}</p>
            ) : (
              <>
                {searchResults !== null && !searching && (
                  <p className="text-sm text-black/50 dark:text-white/50">
                    {t('search.resultsCount', { n: searchResults.length, q: trimmedQuery })}
                  </p>
                )}
                {(searchResults ?? []).map((event) => (
                  <EventCard
                    key={`s-${event.id}`}
                    event={event}
                    profile={profile}
                    onFeedback={handleFeedback}
                    onToggleSave={handleToggleSave}
                    activeFilter={tagFilter}
                    onTagClick={handleTagClick}
                    onOpenDetail={openEventModal}
                  />
                ))}
              </>
            )}
          </div>
        ) : loading ? (
          // B4: layout-matched skeletons instead of a bare "Loading…" line,
          // so the switch to real cards doesn't shift the page around.
          <div className="flex flex-col gap-3">
            {[0, 1, 2].map((i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : tab === 'timeline' ? (
          <TimelineView events={displayedTimelineEvents} onEventClick={openEventModal} />
        ) : tab === 'suggestions' ? (
          <>
            <SuggestionsView
              events={paginatedCardList}
              profile={profile}
              onFeedback={handleFeedback}
              onToggleSave={handleToggleSave}
              activeFilter={tagFilter}
              onTagClick={handleTagClick}
              emptyMessage={emptyMessage}
              onOpenDetail={openEventModal}
            />
            {loadMoreButton}
          </>
        ) : cardListEvents.length === 0 ? (
          <p className="text-sm text-black/50 dark:text-white/50">{emptyMessage}</p>
        ) : (
          <div className="flex flex-col gap-3">
            {/* A5: one .ics covering every saved event, instead of N
                separate per-card downloads. */}
            {tab === 'saved' && savedEvents.length > 0 && (
              <button
                onClick={handleExportSaved}
                className="self-start px-3 py-1.5 rounded-md border border-black/10 dark:border-white/10 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10"
              >
                {t('saved.exportAll')}
              </button>
            )}
            {paginatedCardList.map((event) => (
              <EventCard
                key={event.id}
                event={event}
                profile={profile}
                onFeedback={handleFeedback}
                onToggleSave={handleToggleSave}
                activeFilter={tagFilter}
                onTagClick={handleTagClick}
                onOpenDetail={openEventModal}
              />
            ))}
            {loadMoreButton}
          </div>
        )}
      </div>

      {modalOpen && (
        <EventDetailModal
          event={modalEvent}
          loading={modalLoading}
          profile={profile}
          onFeedback={handleFeedback}
          onToggleSave={handleToggleSave}
          onClose={closeEventModal}
        />
      )}

      <Footer debugStatus={debugStatus} onOpenDisclaimer={() => setTab('disclaimer')} />
    </div>
  )
}

export default App
