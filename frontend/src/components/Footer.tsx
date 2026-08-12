import { formatRelativeTime } from '../dateUtils'
import { useLanguage } from '../i18n'
import type { DebugStatus } from '../types'

// Full legal text lives in its own tab now (DisclaimerView) -- this is
// deliberately just a one-line copyright bar plus a link there, not a
// second copy of the text. Freshness (last_ingest, already polled every
// 10s by App.tsx -- see there) and the demo-scope banner stay here since
// they're page-footer-appropriate, not disclaimer content.
export default function Footer({
  debugStatus,
  onOpenDisclaimer,
}: {
  debugStatus: DebugStatus | null
  onOpenDisclaimer: () => void
}) {
  const { t, lang } = useLanguage()
  const lastIngestAt = debugStatus?.last_ingest?.at ?? null
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
      <p className="text-xs text-black/50 dark:text-white/50">
        {t('footer.copyright')}{' '}
        <button onClick={onOpenDisclaimer} className="underline hover:text-black/80 dark:hover:text-white/80">
          {t('footer.disclaimerLink')}
        </button>
      </p>
    </footer>
  )
}
