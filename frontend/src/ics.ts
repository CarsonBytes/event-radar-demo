import { hktDateDigits, isSameDay, parseUtc } from './dateUtils'
import type { EventItem } from './types'

function icsDateTime(d: Date): string {
  return d.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z'
}

// ICS text fields need backslash/semicolon/comma escaped and literal
// newlines turned into the two-char \n escape (RFC 5545 §3.3.11).
function escapeIcsText(s: string): string {
  return s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n')
}

// Multi-day events (a week-long fair) export as an all-day span, not a
// timed event -- most of these listings carry a fixed placeholder
// time-of-day that isn't a real "doors open" time (same reasoning as
// dateUtils.formatEventDate), and stamping that fake time into someone's
// calendar would be actively misleading. Same-day events keep their given
// time, since that's the one case where it might be real. Shared by both
// the .ics export and the Google Calendar link so they never disagree.
function calendarDateRange(event: EventItem): { allDay: boolean; start: Date; end: Date } {
  const start = parseUtc(event.start)
  const end = event.end ? parseUtc(event.end) : null
  const allDay = end !== null && !isSameDay(start, end)
  if (allDay) {
    // Exclusive end (the day *after* the last day) -- both ICS's
    // VALUE=DATE and Google's all-day `dates=` param use this convention.
    return { allDay: true, start, end: new Date((end as Date).getTime() + 24 * 60 * 60 * 1000) }
  }
  return { allDay: false, start, end: end ?? new Date(start.getTime() + 60 * 60 * 1000) }
}

// Builds one VCALENDAR containing every event given -- shared by the
// single-event export and the Saved-tab "export all" so both stay
// RFC-5545-identical.
function buildIcsCalendar(entries: { event: EventItem; title: string; location: string }[]): string {
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Event Radar//EN', 'CALSCALE:GREGORIAN']
  for (const { event, title, location } of entries) {
    const { allDay, start, end } = calendarDateRange(event)
    lines.push(
      'BEGIN:VEVENT',
      `UID:${event.source}-${event.id}@event-radar`,
      `DTSTAMP:${icsDateTime(new Date())}`,
      allDay ? `DTSTART;VALUE=DATE:${hktDateDigits(start)}` : `DTSTART:${icsDateTime(start)}`,
      allDay ? `DTEND;VALUE=DATE:${hktDateDigits(end)}` : `DTEND:${icsDateTime(end)}`,
      `SUMMARY:${escapeIcsText(title)}`,
    )
    if (location) lines.push(`LOCATION:${escapeIcsText(location)}`)
    if (event.description) lines.push(`DESCRIPTION:${escapeIcsText(event.description)}`)
    if (event.source_url) lines.push(`URL:${event.source_url}`)
    lines.push('END:VEVENT')
  }
  lines.push('END:VCALENDAR')
  return lines.join('\r\n')
}

function downloadText(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function downloadIcs(event: EventItem, title: string, location: string): void {
  const text = buildIcsCalendar([{ event, title, location }])
  downloadText(new Blob([text], { type: 'text/calendar;charset=utf-8' }), `${event.source}-${event.id}.ics`)
}

// One .ics covering everything saved -- imports into Outlook/Apple Calendar
// as a batch instead of N separate downloads.
export function downloadIcsMultiple(entries: { event: EventItem; title: string; location: string }[], filename: string): void {
  const text = buildIcsCalendar(entries)
  downloadText(new Blob([text], { type: 'text/calendar;charset=utf-8' }), filename)
}

// Google's "quick add" URL -- opens Calendar pre-filled with the event, one
// click away from saved. No OAuth/API integration needed (and no way to
// skip that last click -- Google doesn't expose a save-without-confirmation
// flow to third-party sites), which is as automatic as this can get without
// asking users to grant Event Radar write access to their calendar.
export function googleCalendarUrl(event: EventItem, title: string, location: string): string {
  const { allDay, start, end } = calendarDateRange(event)
  const dates = allDay ? `${hktDateDigits(start)}/${hktDateDigits(end)}` : `${icsDateTime(start)}/${icsDateTime(end)}`

  const details = [event.description, event.source_url].filter(Boolean).join('\n\n')

  const params = new URLSearchParams({ action: 'TEMPLATE', text: title, dates, ctz: 'Asia/Hong_Kong' })
  if (details) params.set('details', details)
  if (location) params.set('location', location)

  return `https://calendar.google.com/calendar/render?${params.toString()}`
}

// Same "no API/OAuth needed" reasoning as googleCalendarUrl above -- a
// plain Maps search URL, not the Places/Geocoding API, so a venue name
// that doesn't resolve to an exact pin still lands on a useful results
// page rather than erroring.
export function googleMapsUrl(venue: string, location: string): string {
  const query = [venue, location].filter(Boolean).join(', ')
  return `https://www.google.com/maps/search/?${new URLSearchParams({ api: '1', query }).toString()}`
}
