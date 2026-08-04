export const HKT_TIMEZONE = 'Asia/Hong_Kong'

// Date formatting follows the app's selected display language, not the
// browser's ambient locale -- `toLocaleString(undefined, ...)` used to pick
// up whatever the browser/OS was set to regardless of the in-app EN/中文
// toggle, so switching to English left dates still rendered in Chinese
// numeral format (or vice versa) if the browser's own locale disagreed.
export const DATE_LOCALE: Record<'zh-Hant' | 'en', string> = { 'zh-Hant': 'zh-Hant-HK', en: 'en-US' }

// Backend timestamps are naive ISO strings with no "Z"/offset (Python's
// datetime.utcnow(), serialized as-is) representing UTC instants -- but the
// JS Date constructor treats a marker-less ISO string as LOCAL time per
// spec, silently misinterpreting these by the viewer's own UTC offset (an
// ~8h error for anyone not already sitting in UTC+8, which can even shift
// the displayed calendar date). Every raw backend timestamp must go through
// this instead of a bare `new Date(iso)`.
export function parseUtc(iso: string): Date {
  const hasZone = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso)
  return new Date(hasZone ? iso : `${iso}Z`)
}

function hktParts(date: Date): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: HKT_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value)
  return { year: get('year'), month: get('month'), day: get('day') }
}

// This is a Hong Kong events app -- "today", day boundaries, and week
// groupings should follow Hong Kong's calendar day, not whichever
// timezone a given visitor's browser happens to be in.
export function isSameDay(a: Date, b: Date): boolean {
  const pa = hktParts(a)
  const pb = hktParts(b)
  return pa.year === pb.year && pa.month === pb.month && pa.day === pb.day
}

// "YYYYMMDD" for the HKT calendar day `d` falls on -- e.g. for all-day ICS
// export, where the date itself matters but a fabricated time-of-day would
// mislead (see ics.ts).
export function hktDateDigits(d: Date): string {
  const { year, month, day } = hktParts(d)
  return `${year}${String(month).padStart(2, '0')}${String(day).padStart(2, '0')}`
}

// Returns a Date whose real instant *is* 00:00:00 HKT on the same HKT
// calendar day as `d` (HKT has no DST, always UTC+8, so this is exact) --
// not a "wall clock" trick object, a genuine instant. Safe to both do
// day-difference math on (daysBetween) and to format later with an
// explicit Asia/Hong_Kong timeZone if ever needed.
export function startOfDay(d: Date): Date {
  const { year, month, day } = hktParts(d)
  return new Date(Date.UTC(year, month - 1, day, -8, 0, 0, 0))
}

const DAY_MS = 24 * 60 * 60 * 1000

export function daysBetween(a: Date, b: Date): number {
  return Math.round((startOfDay(b).getTime() - startOfDay(a).getTime()) / DAY_MS)
}

// Multi-day events (e.g. a week-long fair) get a date range instead of a
// single timestamp -- most of these listings carry a fixed placeholder
// time-of-day (midnight, 4pm, ...) that isn't a real "doors open" time, so
// showing it alongside a multi-day span reads as noise. Same-day events
// keep the full date+time as before. Always displayed in HKT, regardless of
// the viewer's own timezone -- this is Hong Kong event data.
// "3 minutes ago" / "3分鐘前" -- Intl.RelativeTimeFormat handles the actual
// localized phrasing, so this only needs to pick a sensible unit.
export function formatRelativeTime(iso: string, lang: 'zh-Hant' | 'en'): string {
  const then = parseUtc(iso).getTime()
  const diffSec = Math.round((then - Date.now()) / 1000)
  const rtf = new Intl.RelativeTimeFormat(DATE_LOCALE[lang], { numeric: 'auto' })
  const abs = Math.abs(diffSec)
  if (abs < 60) return rtf.format(diffSec, 'second')
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), 'hour')
  return rtf.format(Math.round(diffSec / 86400), 'day')
}

export function formatEventDate(startIso: string, endIso: string | null, lang: 'zh-Hant' | 'en'): string {
  const locale = DATE_LOCALE[lang]
  const start = parseUtc(startIso)
  // Whether to print a year at all is judged against *today's* year, not
  // just against the event's own start/end years matching each other --
  // an event entirely within 2027 has startYear === endYear, so the old
  // "only show a year when they differ" rule printed no year at all for
  // it. Reasonable most of the time (this year's events are the common
  // case), but reads as this-year-and-therefore-already-past for anything
  // date-only far enough out to actually be next year -- confirmed live: a
  // "4月13日 – 4月16日" HKTDC listing for April *2027*, viewed in July
  // 2026, was mistaken for an already-passed April date with no year
  // shown to disambiguate.
  const currentYear = hktParts(new Date()).year
  const timeOpts = { timeZone: HKT_TIMEZONE, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' } as const
  if (!endIso) {
    const year = hktParts(start).year
    return start.toLocaleString(locale, { ...timeOpts, year: year !== currentYear ? 'numeric' : undefined })
  }
  const end = parseUtc(endIso)
  if (isSameDay(start, end)) {
    const year = hktParts(start).year
    return start.toLocaleString(locale, { ...timeOpts, year: year !== currentYear ? 'numeric' : undefined })
  }
  const startYear = hktParts(start).year
  const endYear = hktParts(end).year
  const showStartYear = startYear !== currentYear
  const showEndYear = endYear !== currentYear || startYear !== endYear
  const startStr = start.toLocaleDateString(locale, {
    timeZone: HKT_TIMEZONE, month: 'short', day: 'numeric', year: showStartYear ? 'numeric' : undefined,
  })
  const endStr = end.toLocaleDateString(locale, {
    timeZone: HKT_TIMEZONE, month: 'short', day: 'numeric', year: showEndYear ? 'numeric' : undefined,
  })
  return `${startStr} – ${endStr}`
}
