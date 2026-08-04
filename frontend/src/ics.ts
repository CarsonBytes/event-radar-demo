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

export function downloadIcs(event: EventItem, title: string, location: string): void {
  const { allDay, start, end } = calendarDateRange(event)

  const dtstartLine = allDay ? `DTSTART;VALUE=DATE:${hktDateDigits(start)}` : `DTSTART:${icsDateTime(start)}`
  const dtendLine = allDay ? `DTEND;VALUE=DATE:${hktDateDigits(end)}` : `DTEND:${icsDateTime(end)}`

  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Event Radar//EN',
    'CALSCALE:GREGORIAN',
    'BEGIN:VEVENT',
    `UID:${event.source}-${event.id}@event-radar`,
    `DTSTAMP:${icsDateTime(new Date())}`,
    dtstartLine,
    dtendLine,
    `SUMMARY:${escapeIcsText(title)}`,
    location && `LOCATION:${escapeIcsText(location)}`,
    event.description && `DESCRIPTION:${escapeIcsText(event.description)}`,
    event.source_url && `URL:${event.source_url}`,
    'END:VEVENT',
    'END:VCALENDAR',
  ].filter((line): line is string => Boolean(line))

  const blob = new Blob([lines.join('\r\n')], { type: 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${event.source}-${event.id}.ics`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
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
