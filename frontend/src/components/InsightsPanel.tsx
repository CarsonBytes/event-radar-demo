import { useEffect, useState } from 'react'
import { getInsights } from '../api'
import { DATE_LOCALE, HKT_TIMEZONE, parseUtc } from '../dateUtils'
import { useLanguage } from '../i18n'
import type { Insights } from '../types'

function fmtTime(iso: string, lang: 'zh-Hant' | 'en') {
  return parseUtc(iso).toLocaleString(DATE_LOCALE[lang], {
    timeZone: HKT_TIMEZONE,
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-black/10 dark:border-white/10 p-3 flex flex-col gap-1">
      <span className="text-xs text-black/50 dark:text-white/50">{label}</span>
      <span className="text-lg font-semibold">{value}</span>
    </div>
  )
}

function RateBar({ rate }: { rate: number | null }) {
  const { t } = useLanguage()
  if (rate === null) return <span className="text-xs text-black/40 dark:text-white/40">{t('insights.noFeedback')}</span>
  return (
    <div className="flex items-center gap-2 w-32">
      <div className="h-2 flex-1 rounded-full bg-black/10 dark:bg-white/10 overflow-hidden">
        <div className="h-full bg-purple-600" style={{ width: `${Math.round(rate * 100)}%` }} />
      </div>
      <span className="text-xs tabular-nums w-9 text-right">{Math.round(rate * 100)}%</span>
    </div>
  )
}

export default function InsightsPanel({ refreshSignal }: { refreshSignal: number }) {
  const { lang, t } = useLanguage()
  const [data, setData] = useState<Insights | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    getInsights()
      .then(setData)
      .finally(() => setLoading(false))
  }, [refreshSignal])

  if (loading) return <p className="text-sm text-black/50 dark:text-white/50">{t('loading')}</p>
  if (!data) return <p className="text-sm text-black/50 dark:text-white/50">{t('insights.noData')}</p>

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h3 className="font-semibold mb-2">{t('insights.rankingQuality')}</h3>
        <div className="flex items-center justify-between rounded-lg border border-black/10 dark:border-white/10 p-3 mb-2">
          <span className="text-sm">
            {t('insights.overall', { up: data.overall_precision.up, down: data.overall_precision.down })}
          </span>
          <RateBar rate={data.overall_precision.rate} />
        </div>
        {data.precision_by_category.length > 0 && (
          <div className="flex flex-col gap-1">
            {data.precision_by_category.map((p) => (
              <div key={p.label} className="flex items-center justify-between text-sm px-1">
                <span>{p.label}</span>
                <RateBar rate={p.rate} />
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="font-semibold mb-2">{t('insights.llmUsage')}</h3>
        {/* RESPONSIVE FIX 2026-07-15: 4 fixed columns left ~56px per cell after padding on a
            375px phone -- not overflow (grid fractions can't push past the container), but
            "$0.0042" in text-lg font-semibold has no room to breathe there. 2 cols on mobile,
            4 from the sm breakpoint up. */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
          <Stat
            label={t('insights.today')}
            value={data.llm_daily_cap ? `${data.llm_calls_today} / ${data.llm_daily_cap}` : String(data.llm_calls_today)}
          />
          <Stat label={t('insights.totalCalls')} value={String(data.llm_total_calls)} />
          <Stat label={t('insights.totalCost')} value={`$${data.llm_total_cost_usd.toFixed(4)}`} />
          <Stat label={t('insights.avgLatency')} value={`${Math.round(data.llm_avg_latency_ms)} ms`} />
        </div>
        {data.llm_daily_cap && (
          <div className="mb-3">
            <RateBar rate={Math.min(1, data.llm_calls_today / data.llm_daily_cap)} />
          </div>
        )}
        {data.recent_llm_calls.length > 0 && (
          <div className="text-sm flex flex-col gap-1">
            {data.recent_llm_calls.map((c, i) => (
              <div
                key={i}
                className="flex items-center justify-between px-2 py-1 rounded odd:bg-black/[0.03] dark:odd:bg-white/[0.03]"
              >
                <span className="text-black/60 dark:text-white/60">{fmtTime(c.created_at, lang)}</span>
                <span>{c.kind}</span>
                <span className="text-black/50 dark:text-white/50">
                  {c.input_tokens}→{c.output_tokens} tok
                </span>
                <span className="tabular-nums">{c.latency_ms}ms</span>
                <span className="tabular-nums">${c.cost_usd.toFixed(5)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="font-semibold mb-2">{t('insights.sharedQuota')}</h3>
        {/* RESPONSIVE FIX 2026-07-15: same cramped-cell issue as the grid above. */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-3">
          <Stat
            label={t('insights.todayAllProjects')}
            value={
              data.llm_daily_cap
                ? `${data.shared_calls_today} / ${data.llm_daily_cap}`
                : String(data.shared_calls_today)
            }
          />
          <Stat label={t('insights.costTodayAllProjects')} value={`$${data.shared_cost_today_usd.toFixed(4)}`} />
          <Stat label={t('insights.thisAppsShare')} value={t('insights.calls', { n: data.llm_calls_today })} />
        </div>
        {data.llm_daily_cap && (
          <div className="mb-3">
            <RateBar rate={Math.min(1, data.shared_calls_today / data.llm_daily_cap)} />
          </div>
        )}
        {Object.keys(data.shared_calls_by_project).length > 0 && (
          <div className="flex flex-col gap-1 text-sm">
            {Object.entries(data.shared_calls_by_project)
              .sort((a, b) => b[1] - a[1])
              .map(([project, count]) => (
                <div key={project} className="flex items-center justify-between px-1">
                  <span className="capitalize">{project}</span>
                  <span className="tabular-nums text-black/60 dark:text-white/60">{t('insights.calls', { n: count })}</span>
                </div>
              ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="font-semibold mb-2">{t('insights.ingestRuns')}</h3>
        {data.recent_ingest_runs.length === 0 ? (
          <p className="text-sm text-black/50 dark:text-white/50">{t('insights.noIngestRuns')}</p>
        ) : (
          <div className="text-sm flex flex-col gap-1">
            {data.recent_ingest_runs.map((r, i) => (
              <div
                key={i}
                className="flex items-center justify-between px-2 py-1 rounded odd:bg-black/[0.03] dark:odd:bg-white/[0.03]"
              >
                <span className="text-black/60 dark:text-white/60">{fmtTime(r.started_at, lang)}</span>
                <span>{t('insights.ingestSummary', { fetched: r.fetched, new: r.new, updated: r.updated, ranked: r.ranked })}</span>
                <span className="tabular-nums">{r.duration_ms}ms</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
