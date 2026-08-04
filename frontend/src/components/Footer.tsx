import { formatRelativeTime } from '../dateUtils'
import { useLanguage } from '../i18n'
import type { DebugStatus } from '../types'

// A public, unauthenticated app scraping several third-party sites needs
// two things visible at the bottom of every page: how fresh the data
// actually is (reused from /api/debug/status, already polled every 10s --
// see App.tsx -- so this needs no fetch of its own), and a clear,
// non-commercial-use disclaimer naming every real source. Deliberately
// small/muted -- fine print, not a headline.
export default function Footer({ debugStatus }: { debugStatus: DebugStatus | null }) {
  const { t, lang } = useLanguage()
  const lastIngestAt = debugStatus?.last_ingest?.at ?? null
  // Demo deployment restricts CONNECTORS to urbtix only at the backend
  // level (see ingest_job.py's DEMO_MODE) -- this flag only changes which
  // disclaimer text is honest to show, it isn't what's actually enforcing
  // the data restriction.
  const isDemo = debugStatus?.demo_mode ?? false

  return (
    <footer className="mt-8 pt-4 px-4 max-w-3xl mx-auto w-full border-t border-black/10 dark:border-white/10 flex flex-col items-center gap-2 text-center">
      {isDemo && (
        <p className="text-xs font-medium px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-700 dark:text-amber-400">
          {t('footer.demoBanner')}
        </p>
      )}
      {lastIngestAt && (
        <p className="text-xs text-black/50 dark:text-white/50">
          {t('footer.lastUpdated', { time: formatRelativeTime(lastIngestAt, lang) })}
        </p>
      )}
      <p className="text-[11px] leading-relaxed text-black/40 dark:text-white/40 max-w-2xl">
        {t(isDemo ? 'footer.demoDisclaimer' : 'footer.disclaimer')}
      </p>
    </footer>
  )
}
