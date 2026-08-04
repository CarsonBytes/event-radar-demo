import { formatRelativeTime } from '../dateUtils'
import { useLanguage } from '../i18n'
import type { DebugStatus, Insights } from '../types'

// Answers the exact confusion that prompted this: clicking Refresh gave one
// status line that vanished after ~2.5 min with no way to tell "it's still
// working," "nothing needed to happen," and "it silently failed" apart.
// This reads live state from /api/debug/status (already built for
// debugging this app) instead of guessing from the fetch/ingest summary
// alone.
export default function RerankStatusBar({
  debugStatus,
  insights,
}: {
  debugStatus: DebugStatus | null
  insights: Insights | null
}) {
  const { t, lang } = useLanguage()

  if (!debugStatus) return null
  const { rerank, last_rerank } = debugStatus

  let mainLine: string
  if (rerank.in_progress) {
    mainLine =
      rerank.batches_total != null
        ? t('debug.rerankInProgressWithBatches', { done: rerank.batches_done, total: rerank.batches_total })
        : t('debug.rerankInProgress')
  } else if (rerank.last_result === 'skipped') {
    mainLine = t('debug.rerankSkippedNotDue')
  } else if (last_rerank) {
    const outcomeKey =
      last_rerank.level === 'error' ? 'debug.outcomeError' : last_rerank.message.startsWith('rerank skipped') ? 'debug.outcomeSkipped' : 'debug.outcomeOk'
    mainLine = t('debug.lastRerank', { time: formatRelativeTime(last_rerank.at, lang), outcome: t(outcomeKey) })
  } else {
    mainLine = t('debug.neverReranked')
  }

  const quotaExhausted = rerank.quota_exhausted || last_rerank?.detail?.quota_exhausted === true
  const cap = insights?.llm_daily_cap
  const quotaLine = cap != null ? t('debug.quotaUsage', { used: insights!.shared_calls_today, cap }) : null

  return (
    <div className="flex flex-col gap-1 text-xs text-black/50 dark:text-white/50">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span>{mainLine}</span>
        {quotaLine && (
          <>
            <span className="opacity-50">·</span>
            <span>{quotaLine}</span>
          </>
        )}
      </div>
      {quotaExhausted && (
        <p className="text-amber-600 dark:text-amber-400">{t('debug.quotaExhausted')}</p>
      )}
    </div>
  )
}
