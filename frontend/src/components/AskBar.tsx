import { useState } from 'react'
import { askQuestion, getAskHistory } from '../api'
import { formatRelativeTime } from '../dateUtils'
import { useLanguage } from '../i18n'
import type { AskReferencedEvent, AskHistoryItem, EventItem } from '../types'

function ReferencedEvents({
  events,
  onOpenEvent,
}: {
  events: AskReferencedEvent[]
  onOpenEvent: (eventOrId: EventItem | number) => void
}) {
  const { lang } = useLanguage()
  if (events.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5 mt-1.5">
      {events.map((ev) => (
        <button
          key={ev.id}
          onClick={() => onOpenEvent(ev.id)}
          className="px-2 py-0.5 rounded-full bg-purple-600/10 text-purple-700 dark:text-purple-300 text-xs hover:bg-purple-600/20"
        >
          {(lang === 'zh-Hant' && ev.title_native) || ev.title}
        </button>
      ))}
    </div>
  )
}

// Shown only while the input is empty and untouched -- an empty ask box
// with just an italic placeholder gives no sense of what's actually worth
// asking (the placeholder shows exactly one example and disappears the
// moment you start typing). Static, not LLM-generated: keeps ask() at
// exactly one real call per question asked, not one more just to produce
// examples. Same "only show when there's nothing there yet" pattern as
// InterestForm's onboarding suggestion chips.
const ASK_SUGGESTION_KEYS = [
  'ask.suggestion.weekend',
  'ask.suggestion.free',
  'ask.suggestion.now',
  'ask.suggestion.concerts',
  'ask.suggestion.new',
]

// Sits alongside the structured interest chips, not instead of them --
// those are the precise, editable long-term profile; this is for
// one-off, disposable questions the chip model can't express well
// ("this weekend", "free", "outdoor"). One real LLM call per ask (see
// app/ask.py), so it's deliberately a single input + single reply, not a
// running chat thread that could rack up requests silently.
export default function AskBar({ onOpenEvent }: { onOpenEvent: (eventOrId: EventItem | number) => void }) {
  const { lang, t } = useLanguage()
  const [query, setQuery] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<string | null>(null)
  const [referencedEvents, setReferencedEvents] = useState<AskReferencedEvent[]>([])
  const [quotaExhausted, setQuotaExhausted] = useState(false)
  const [failed, setFailed] = useState(false)

  // Collapsed by default -- a look-back/audit list, not a running chat
  // thread. Fetched lazily on first expand (and refetched after every new
  // ask while already expanded) rather than on mount, since most visits
  // never open it at all.
  const [showHistory, setShowHistory] = useState(false)
  const [history, setHistory] = useState<AskHistoryItem[] | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)

  const loadHistory = async () => {
    setHistoryLoading(true)
    try {
      const result = await getAskHistory()
      setHistory(result.items)
    } catch {
      setHistory([])
    } finally {
      setHistoryLoading(false)
    }
  }

  const toggleHistory = () => {
    const next = !showHistory
    setShowHistory(next)
    if (next && history === null) loadHistory()
  }

  const submit = async () => {
    const q = query.trim()
    if (!q || asking) return
    setAsking(true)
    setQuotaExhausted(false)
    setFailed(false)
    setAnswer(null)
    setReferencedEvents([])
    try {
      const result = await askQuestion(q)
      if (result.answer) {
        setAnswer(result.answer)
        setReferencedEvents(result.referenced_events)
      } else if (result.quota_exhausted) {
        setQuotaExhausted(true)
      } else {
        setFailed(true)
      }
      if (showHistory) loadHistory()
    } catch {
      setFailed(true)
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 rounded-full border border-purple-500/20 bg-purple-500/5 dark:bg-purple-500/10 pl-3 pr-1.5 py-1.5">
        <span className="shrink-0 text-base" aria-hidden="true">✨</span>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              submit()
            }
          }}
          placeholder={t('ask.placeholder')}
          className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:italic placeholder:text-black/40 dark:placeholder:text-white/40"
        />
        <button
          onClick={submit}
          disabled={asking || !query.trim()}
          aria-label={t('ask.submit')}
          className="w-8 h-8 rounded-full bg-purple-600 text-white flex items-center justify-center disabled:opacity-40 shrink-0 text-sm"
        >
          {asking ? '…' : '→'}
        </button>
      </div>
      {!query.trim() && !asking && (
        <div className="flex flex-wrap gap-1.5">
          {ASK_SUGGESTION_KEYS.map((key) => (
            <button
              key={key}
              onClick={() => setQuery(t(key))}
              className="px-2.5 py-1 rounded-full bg-black/5 dark:bg-white/10 text-black/70 dark:text-white/70 text-xs hover:bg-black/10 dark:hover:bg-white/20"
            >
              {t(key)}
            </button>
          ))}
        </div>
      )}
      {answer && (
        <div className="rounded-md bg-purple-500/5 dark:bg-purple-500/10 border border-purple-500/10 px-3 py-2 text-sm leading-relaxed">
          {answer}
          <ReferencedEvents events={referencedEvents} onOpenEvent={onOpenEvent} />
        </div>
      )}
      {quotaExhausted && <p className="text-xs text-amber-600 dark:text-amber-400">{t('ask.quotaExhausted')}</p>}
      {failed && <p className="text-xs text-red-600 dark:text-red-400">{t('ask.error')}</p>}

      <button
        onClick={toggleHistory}
        className="self-start text-xs text-black/40 dark:text-white/40 hover:underline"
      >
        {showHistory ? t('ask.historyHide') : t('ask.historyShow')}
      </button>

      {showHistory && (
        <div className="flex flex-col gap-2">
          {historyLoading ? (
            <p className="text-xs text-black/40 dark:text-white/40">{t('loading')}</p>
          ) : !history || history.length === 0 ? (
            <p className="text-xs text-black/40 dark:text-white/40">{t('ask.historyEmpty')}</p>
          ) : (
            history.map((item) => (
              <div key={item.id} className="rounded-md bg-black/[0.02] dark:bg-white/[0.04] px-3 py-2 text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="font-medium">{item.query}</p>
                  <span className="shrink-0 text-xs text-black/40 dark:text-white/40">
                    {formatRelativeTime(item.created_at, lang)}
                  </span>
                </div>
                <p className="text-black/60 dark:text-white/60 mt-0.5">
                  {item.answer || (item.quota_exhausted ? t('ask.quotaExhausted') : t('ask.error'))}
                </p>
                <ReferencedEvents events={item.referenced_events} onOpenEvent={onOpenEvent} />
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
