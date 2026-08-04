import { useRef, useState } from 'react'
import { formatEventDate } from '../dateUtils'
import { useLanguage } from '../i18n'
import type { EventItem } from '../types'
import { EventArt, matchTier, TIER_STYLES } from './EventCard'

// Drag right = save, drag left = not interested -- deliberately not
// up/down thumbs, since saving ("I mean to go") and feedback ("show me
// more like this") are a real, existing distinction in this app (see
// SavedEvent vs Feedback on the backend); the two swipe directions map
// onto that existing split rather than inventing a third signal type.
const SWIPE_THRESHOLD = 90

export default function SwipeDeck({
  events,
  onFeedback,
  onToggleSave,
}: {
  events: EventItem[]
  onFeedback: (id: number, signal: 'up' | 'down' | 'none') => void
  onToggleSave: (id: number, saved: boolean) => void
}) {
  const { lang, t } = useLanguage()
  const [index, setIndex] = useState(0)
  const [dragX, setDragX] = useState(0)
  const draggingRef = useRef(false)
  const startXRef = useRef(0)

  const stack = events.slice(index, index + 3)
  const current = stack[0]

  const commit = (direction: 'left' | 'right') => {
    if (!current) return
    if (direction === 'right') onToggleSave(current.id, true)
    else onFeedback(current.id, 'down')
    setDragX(0)
    setIndex((i) => i + 1)
  }

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = true
    startXRef.current = e.clientX
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return
    setDragX(e.clientX - startXRef.current)
  }
  const onPointerUp = () => {
    if (!draggingRef.current) return
    draggingRef.current = false
    if (Math.abs(dragX) > SWIPE_THRESHOLD) commit(dragX > 0 ? 'right' : 'left')
    else setDragX(0)
  }

  if (!current) {
    return (
      <div className="flex flex-col items-center gap-1 py-16 text-center text-black/50 dark:text-white/50">
        <p className="text-2xl">✨</p>
        <p className="text-sm">{t('swipe.done')}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center gap-4 py-2">
      <div className="relative w-full max-w-sm" style={{ height: 260 }}>
        {stack
          .map((ev, stackIndex) => {
            // z-index (not DOM order) handles stacking, so no need to
            // reverse this array -- the top card (stackIndex 0) always
            // paints above the rest via its own z-index value below.
            const isTop = stackIndex === 0
            const rotation = isTop ? dragX / 20 : 0
            return (
              <div
                key={ev.id}
                onPointerDown={isTop ? onPointerDown : undefined}
                onPointerMove={isTop ? onPointerMove : undefined}
                onPointerUp={isTop ? onPointerUp : undefined}
                onPointerCancel={isTop ? onPointerUp : undefined}
                className="absolute inset-x-0 top-0 rounded-lg border border-black/10 dark:border-white/10 bg-white dark:bg-black overflow-hidden shadow-sm select-none"
                style={{
                  transform: isTop
                    ? `translateX(${dragX}px) rotate(${rotation}deg)`
                    : `translateY(${stackIndex * 8}px) scale(${1 - stackIndex * 0.04})`,
                  opacity: isTop ? 1 : 1 - stackIndex * 0.3,
                  zIndex: 10 - stackIndex,
                  cursor: isTop ? 'grab' : 'default',
                  touchAction: 'none',
                }}
              >
                <EventArt event={ev} category={ev.category_native || ev.category} />
                <div className="p-3">
                  <h3 className="font-semibold text-sm leading-snug">{ev.title_native || ev.title}</h3>
                  <p className="text-xs text-black/50 dark:text-white/50 mt-0.5">
                    {formatEventDate(ev.start, ev.end, lang)} · {ev.venue_name_native || ev.venue_name}
                  </p>
                  {ev.llm_score !== null && (
                    <span
                      className={`inline-block mt-2 px-2 py-0.5 rounded-full text-xs font-medium ${TIER_STYLES[matchTier(ev.llm_score)]}`}
                    >
                      {t(`event.matchTier.${matchTier(ev.llm_score)}`)} ·{' '}
                      <span className="font-display">{Math.round(ev.llm_score)}</span>
                    </span>
                  )}
                </div>
              </div>
            )
          })}
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={() => commit('left')}
          aria-label={t('swipe.pass')}
          title={t('swipe.pass')}
          className="w-11 h-11 rounded-full border border-black/10 dark:border-white/10 text-lg hover:bg-black/5 dark:hover:bg-white/10"
        >
          ✕
        </button>
        <button
          onClick={() => commit('right')}
          aria-label={t('swipe.save')}
          title={t('swipe.save')}
          className="w-11 h-11 rounded-full border border-amber-500/40 bg-amber-500/10 text-lg hover:bg-amber-500/20"
        >
          🔖
        </button>
      </div>
      <p className="text-xs text-black/40 dark:text-white/40">{t('swipe.remaining', { n: events.length - index })}</p>
    </div>
  )
}
