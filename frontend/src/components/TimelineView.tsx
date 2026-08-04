import { useEffect, useMemo, useRef, useState } from 'react'
import { DATE_LOCALE, HKT_TIMEZONE, daysBetween, parseUtc, startOfDay } from '../dateUtils'
import { useLanguage } from '../i18n'
import type { EventItem } from '../types'

const DAY_WIDTH = 28 // px per day -- wide enough for a week-label to sit above a 7-day span
const ROW_HEIGHT = 30

type ScoreTierKey = 'great' | 'good' | 'some'

const SCORE_TIERS: { key: ScoreTierKey; labelKey: string; min: number; bar: string }[] = [
  { key: 'great', labelKey: 'timeline.tier.great', min: 70, bar: 'bg-purple-600' },
  { key: 'good', labelKey: 'timeline.tier.good', min: 40, bar: 'bg-blue-500' },
  { key: 'some', labelKey: 'timeline.tier.some', min: 1, bar: 'bg-slate-400' },
]

function tierFor(score: number | null): ScoreTierKey | 'unscored' {
  if (score === null) return 'unscored'
  for (const tier of SCORE_TIERS) {
    if (score >= tier.min) return tier.key
  }
  return 'unscored'
}

function barColor(score: number | null): string {
  if (score === null) return 'bg-black/15 dark:bg-white/15'
  const tier = SCORE_TIERS.find((t) => score >= t.min)
  return tier?.bar ?? 'bg-black/15 dark:bg-white/15'
}

type GroupBy = 'score' | 'category'

// Greedy interval packing: events that don't overlap in time share a row,
// so a lane with e.g. 150 mostly-single-day events collapses to a handful
// of rows instead of 150 stacked ones. Standard "assign to first row whose
// last event has already ended" scheduling -- events are pre-sorted by
// start so each row's own events stay chronological.
function packRows(sorted: EventItem[]): EventItem[][] {
  const rows: EventItem[][] = []
  const rowEnds: number[] = []
  for (const ev of sorted) {
    const start = parseUtc(ev.start).getTime()
    const end = parseUtc(ev.end || ev.start).getTime()
    const rowIdx = rowEnds.findIndex((rowEnd) => rowEnd < start)
    if (rowIdx === -1) {
      rows.push([ev])
      rowEnds.push(end)
    } else {
      rows[rowIdx].push(ev)
      rowEnds[rowIdx] = end
    }
  }
  return rows
}

// Some listings (museum passes, "permanent exhibition" tickets, season-long
// runs) span months or years -- they're standing offerings, not a
// scheduled "when should I go" decision, and including them stretches the
// whole domain across years around one outlier bar (e.g. "e-Museum Pass",
// 2024-12-31 to 2026-09-30). Excluded from the Gantt entirely rather than
// just clamped, since a multi-year bar wouldn't be meaningful even drawn.
const MAX_SPAN_DAYS = 45

// Leaves two weeks of recent-past space before "today" (see the auto-scroll
// effect below, which parks today at the start of the visible area with
// this space scrollable-back-into) rather than starting exactly wherever
// the earliest ongoing event happens to begin -- that could be just a day
// or two back, leaving no room to check what recently wrapped up.
const LOOKBACK_DAYS = 14

export default function TimelineView({
  events,
  onEventClick,
}: {
  events: EventItem[]
  onEventClick: (event: EventItem) => void
}) {
  const { lang, t } = useLanguage()
  const [groupBy, setGroupBy] = useState<GroupBy>('score')
  const [showUnscored, setShowUnscored] = useState(false)

  const ganttable = useMemo(
    () => events.filter((e) => daysBetween(parseUtc(e.start), parseUtc(e.end || e.start)) <= MAX_SPAN_DAYS),
    [events],
  )
  const longRunningCount = events.length - ganttable.length

  const { domainStart, totalDays, groups } = useMemo(() => {
    if (ganttable.length === 0) {
      return {
        domainStart: startOfDay(new Date()),
        totalDays: 0,
        groups: [] as { label: string; events: EventItem[]; rows: EventItem[][] }[],
      }
    }

    const today = startOfDay(new Date())
    const lookback = new Date(today.getTime() - LOOKBACK_DAYS * 24 * 60 * 60 * 1000)
    const starts = ganttable.map((e) => startOfDay(parseUtc(e.start)))
    const ends = ganttable.map((e) => startOfDay(parseUtc(e.end || e.start)))
    const minStart = new Date(Math.min(lookback.getTime(), ...starts.map((d) => d.getTime())))
    const maxEnd = new Date(Math.max(...ends.map((d) => d.getTime())))
    const span = daysBetween(minStart, maxEnd) + 1

    const visible = showUnscored ? ganttable : ganttable.filter((e) => e.llm_score !== null)

    let grouped: { label: string; events: EventItem[] }[]
    if (groupBy === 'score') {
      grouped = [
        ...SCORE_TIERS.map((tier) => ({
          label: t(tier.labelKey),
          events: visible.filter((e) => tierFor(e.llm_score) === tier.key),
        })),
        ...(showUnscored
          ? [{ label: t('timeline.tier.unscored'), events: visible.filter((e) => tierFor(e.llm_score) === 'unscored') }]
          : []),
      ].filter((g) => g.events.length > 0)
    } else {
      const categoryOf = (e: EventItem) =>
        (lang === 'zh-Hant' && e.category_native) || e.category || t('timeline.uncategorized')
      const categories = Array.from(new Set(visible.map(categoryOf))).sort()
      grouped = categories.map((c) => ({ label: c, events: visible.filter((e) => categoryOf(e) === c) }))
    }
    // within each lane, earliest-starting first, then packed into rows
    grouped.forEach((g) => g.events.sort((a, b) => parseUtc(a.start).getTime() - parseUtc(b.start).getTime()))
    const withRows = grouped.map((g) => ({ ...g, rows: packRows(g.events) }))

    return { domainStart: minStart, totalDays: span, groups: withRows }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `t` is intentionally omitted (new identity every render); `lang` covers it
  }, [ganttable, groupBy, showUnscored, lang])

  const unscoredCount = ganttable.filter((e) => e.llm_score === null).length
  const totalWidth = totalDays * DAY_WIDTH
  const todayOffset = daysBetween(domainStart, startOfDay(new Date())) * DAY_WIDTH

  // Ongoing events can start well before today, pushing the domain's left
  // edge back -- without this, "today" could land off-screen to the right
  // on first load, behind however much history an ongoing event dragged in.
  // Scroll it into view (with one day of lead-in, not glued to the exact
  // pixel edge) as soon as the chart's width is known.
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = Math.max(0, todayOffset - DAY_WIDTH)
    }
  }, [todayOffset])

  const weekTicks = useMemo(() => {
    const ticks: { offset: number; label: string }[] = []
    for (let d = 0; d < totalDays; d += 7) {
      const date = new Date(domainStart.getTime() + d * 24 * 60 * 60 * 1000)
      ticks.push({
        offset: d * DAY_WIDTH,
        label: date.toLocaleDateString(DATE_LOCALE[lang], { timeZone: HKT_TIMEZONE, month: 'short', day: 'numeric' }),
      })
    }
    return ticks
  }, [domainStart, totalDays, lang])

  if (ganttable.length === 0) {
    return <p className="text-sm text-black/50 dark:text-white/50">{t('timeline.noEvents')}</p>
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 text-sm flex-wrap">
        <div className="inline-flex rounded-md border border-black/10 dark:border-white/10 overflow-hidden">
          {(['score', 'category'] as GroupBy[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setGroupBy(mode)}
              className={`px-3 py-1.5 font-medium ${
                groupBy === mode
                  ? 'bg-purple-600 text-white'
                  : 'bg-transparent text-black/60 dark:text-white/60 hover:bg-black/5 dark:hover:bg-white/10'
              }`}
            >
              {mode === 'score' ? t('timeline.byScore') : t('timeline.byCategory')}
            </button>
          ))}
        </div>
        {unscoredCount > 0 && (
          <label className="flex items-center gap-1.5 text-black/50 dark:text-white/50">
            <input type="checkbox" checked={showUnscored} onChange={(e) => setShowUnscored(e.target.checked)} />
            {t('timeline.showUnscored', { n: unscoredCount })}
          </label>
        )}
        <div className="flex items-center gap-3 ml-auto text-xs text-black/50 dark:text-white/50">
          {SCORE_TIERS.map((tier) => (
            <span key={tier.key} className="flex items-center gap-1">
              <span className={`w-2.5 h-2.5 rounded-sm ${tier.bar}`} />
              {t(tier.labelKey)}
            </span>
          ))}
        </div>
      </div>

      {longRunningCount > 0 && (
        <p className="text-xs text-black/40 dark:text-white/40">{t('timeline.longRunning', { n: longRunningCount })}</p>
      )}

      <div ref={scrollRef} className="overflow-x-auto rounded-lg border border-black/10 dark:border-white/10">
        <div style={{ width: totalWidth + 180 }}>
          {/* header: week ticks */}
          <div className="relative h-8 border-b border-black/10 dark:border-white/10" style={{ marginLeft: 180 }}>
            {weekTicks.map((tick) => (
              <div
                key={tick.offset}
                className="absolute top-0 h-full border-l border-black/5 dark:border-white/10 text-[11px] text-black/40 dark:text-white/40 pl-1 pt-1.5"
                style={{ left: tick.offset }}
              >
                {tick.label}
              </div>
            ))}
            {todayOffset >= 0 && todayOffset <= totalWidth && (
              <div className="absolute top-0 h-full border-l-2 border-red-500/60" style={{ left: todayOffset }} />
            )}
          </div>

          {groups.map((group) => (
            <div key={group.label} className="flex border-b border-black/5 dark:border-white/10 last:border-0">
              <div
                className="sticky left-0 z-10 shrink-0 w-[180px] px-2 py-2 text-xs font-medium text-black/60 dark:text-white/60 bg-white dark:bg-black border-r border-black/5 dark:border-white/10"
              >
                {group.label}
                <span className="text-black/35 dark:text-white/35"> ({group.events.length})</span>
              </div>
              <div className="relative" style={{ width: totalWidth, minHeight: ROW_HEIGHT }}>
                {todayOffset >= 0 && todayOffset <= totalWidth && (
                  <div className="absolute top-0 bottom-0 border-l-2 border-red-500/40 pointer-events-none" style={{ left: todayOffset }} />
                )}
                {group.rows.map((row, rowIdx) =>
                  row.map((ev) => {
                    const left = daysBetween(domainStart, startOfDay(parseUtc(ev.start))) * DAY_WIDTH
                    const spanDays = Math.max(1, daysBetween(parseUtc(ev.start), parseUtc(ev.end || ev.start)) + 1)
                    const width = Math.max(DAY_WIDTH - 4, spanDays * DAY_WIDTH - 4)
                    const displayTitle = (lang === 'zh-Hant' && ev.title_native) || ev.title
                    const tooltip = `${displayTitle}${ev.llm_score !== null ? ` — ${t('event.match', { score: Math.round(ev.llm_score) })}` : ''}${
                      ev.why_match ? `\n${ev.why_match}` : ''
                    }`
                    return (
                      <button
                        key={ev.id}
                        onClick={() => onEventClick(ev)}
                        title={tooltip}
                        className={`absolute rounded text-[11px] leading-none text-white px-1.5 py-1.5 truncate text-left hover:opacity-80 ${barColor(
                          ev.llm_score,
                        )}`}
                        style={{ left: left + 2, top: rowIdx * ROW_HEIGHT + 3, width }}
                      >
                        {displayTitle}
                      </button>
                    )
                  }),
                )}
                <div style={{ height: group.rows.length * ROW_HEIGHT }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
