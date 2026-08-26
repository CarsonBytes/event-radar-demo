import { useEffect, useRef } from 'react'
import { useLanguage } from '../i18n'
import type { EventItem, InterestProfile } from '../types'
import EventCard from './EventCard'

// The shared destination for every "jump to this event's own card" action
// in the app -- the Timeline Gantt bars (which used to only link straight
// to the external ticket page, a dead end for anything the app itself
// knows: match score, why_match, save state) and the ask box's referenced
// events (freeform LLM prose, otherwise no way to reach the actual card it
// was talking about). A modal rather than switching tabs/scrolling,
// because the referenced event isn't guaranteed to be in whatever list the
// current tab has loaded (e.g. a low-score event named in an answer isn't
// in Suggestions, a past reference isn't anywhere at all) -- the modal
// works the same regardless of where the event would otherwise live.
export default function EventDetailModal({
  event,
  loading,
  profile,
  onFeedback,
  onToggleSave,
  onClose,
}: {
  event: EventItem | null
  loading: boolean
  profile: InterestProfile | null
  onFeedback: (id: number, signal: 'up' | 'down' | 'none') => void
  onToggleSave: (id: number, saved: boolean) => void
  onClose: () => void
}) {
  const { t } = useLanguage()
  const dialogRef = useRef<HTMLDivElement>(null)
  // Restores focus to whichever element opened the modal on close --
  // keyboard users otherwise land back at <body> and lose their place.
  const previouslyFocused = useRef<HTMLElement | null>(null)

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null
    // Focus the dialog itself so Tab starts inside it.
    dialogRef.current?.focus()
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prevOverflow
      previouslyFocused.current?.focus?.()
    }
  }, [])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      // Minimal focus trap -- Tab / Shift+Tab cycle within the dialog
      // instead of escaping into the page behind the overlay.
      if (e.key !== 'Tab' || !dialogRef.current) return
      const focusables = dialogRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      if (focusables.length === 0) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-12"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={event?.title ?? t('loading')}
        tabIndex={-1}
        className="w-full max-w-lg outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-end mb-2">
          <button
            onClick={onClose}
            aria-label={t('modal.close')}
            className="w-8 h-8 rounded-full bg-white dark:bg-black border border-black/10 dark:border-white/10 text-lg hover:bg-black/5 dark:hover:bg-white/10"
          >
            ×
          </button>
        </div>
        {loading ? (
          <div className="rounded-lg border border-black/10 dark:border-white/10 bg-white dark:bg-black p-6 text-center text-sm text-black/50 dark:text-white/50">
            {t('loading')}
          </div>
        ) : !event ? (
          <div className="rounded-lg border border-black/10 dark:border-white/10 bg-white dark:bg-black p-6 text-center text-sm text-black/50 dark:text-white/50">
            {t('event.notFound')}
          </div>
        ) : (
          <div className="bg-white dark:bg-black rounded-lg">
            <EventCard
              event={event}
              profile={profile}
              onFeedback={onFeedback}
              onToggleSave={onToggleSave}
              activeFilter={null}
              onTagClick={() => {}}
              showDescription
            />
          </div>
        )}
      </div>
    </div>
  )
}
