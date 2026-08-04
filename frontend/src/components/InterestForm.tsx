import { useEffect, useRef, useState } from 'react'
import { useLanguage } from '../i18n'
import type { InterestProfile } from '../types'

// Mirrors the backend's naive split (app/interests.py::_naive_parse) so the
// initial chip list, derived from whatever raw_text already exists, lines up
// with how the same text would be parsed server-side.
const SPLIT_RE = /[,;\n]| and /i

function splitToItems(text: string): string[] {
  return text
    .split(SPLIT_RE)
    .map((s) => s.trim())
    .filter(Boolean)
}

function dedupeAppend(existing: string[], incoming: string[]): string[] {
  const seen = new Set(existing.map((s) => s.toLowerCase()))
  const merged = [...existing]
  for (const item of incoming) {
    if (!seen.has(item.toLowerCase())) {
      seen.add(item.toLowerCase())
      merged.push(item)
    }
  }
  return merged
}

// Shown only when the chip list is empty -- a first-time visitor otherwise
// lands on a blank form with no cue for what a good interest even looks
// like. Picked to span what the two connectors actually carry (URBTIX +
// HKTDC), so every suggestion returns real results, not a dead end.
const STARTER_SUGGESTION_KEYS = [
  'onboarding.liveMusic',
  'onboarding.theatre',
  'onboarding.artExhibitions',
  'onboarding.familyFriendly',
  'onboarding.food',
  'onboarding.bookFairs',
  'onboarding.tech',
  'onboarding.dance',
]

export default function InterestForm({
  profile,
  onSave,
}: {
  profile: InterestProfile | null
  onSave: (rawText: string, excludedKeywords: string[]) => Promise<void>
}) {
  const { t } = useLanguage()
  const [items, setItems] = useState<string[]>([])
  const [newItemText, setNewItemText] = useState('')
  const [pasteText, setPasteText] = useState('')
  const [showPaste, setShowPaste] = useState(false)
  const [excludedItems, setExcludedItems] = useState<string[]>([])
  const [newExcludedText, setNewExcludedText] = useState('')
  const [saving, setSaving] = useState(false)
  const [expanded, setExpanded] = useState(true)

  // A returning visitor already has a profile -- showing the full editor
  // every visit pushed every event below the fold (measured: on a 812px
  // mobile viewport, the tab bar itself didn't start until 719px down).
  // Collapse to a one-line summary once there's something to summarize;
  // a first-time visitor with no profile yet still lands on the full
  // editor, since there's nothing to collapse to. Only decided once, off
  // the first profile load -- not on every subsequent update, since
  // submit() below owns re-collapsing after a save.
  const initializedRef = useRef(false)
  useEffect(() => {
    if (!profile || initializedRef.current) return
    initializedRef.current = true
    setExpanded(!profile.raw_text.trim())
  }, [profile])

  // Re-sync from the server only when the underlying text actually differs
  // from what these chips already represent — avoids clobbering in-progress
  // local edits every time `profile` re-renders for an unrelated reason.
  useEffect(() => {
    if (!profile) return
    if (profile.raw_text.trim() === items.join(', ')) return
    setItems(splitToItems(profile.raw_text))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.raw_text])

  useEffect(() => {
    if (!profile) return
    if (profile.excluded_keywords.join(', ') === excludedItems.join(', ')) return
    setExcludedItems(profile.excluded_keywords)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.excluded_keywords])

  const addItem = () => {
    const text = newItemText.trim()
    if (!text) return
    setItems((prev) => dedupeAppend(prev, [text]))
    setNewItemText('')
  }

  const addSuggestion = (text: string) => {
    setItems((prev) => dedupeAppend(prev, [text]))
  }

  const removeItem = (index: number) => {
    setItems((prev) => prev.filter((_, i) => i !== index))
  }

  const editItem = (index: number) => {
    setNewItemText(items[index])
    removeItem(index)
  }

  const addFromPaste = () => {
    const parsed = splitToItems(pasteText)
    if (parsed.length === 0) return
    setItems((prev) => dedupeAppend(prev, parsed))
    setPasteText('')
    setShowPaste(false)
  }

  const addExcluded = () => {
    const text = newExcludedText.trim()
    if (!text) return
    setExcludedItems((prev) => dedupeAppend(prev, [text]))
    setNewExcludedText('')
  }

  const removeExcluded = (index: number) => {
    setExcludedItems((prev) => prev.filter((_, i) => i !== index))
  }

  const submit = async () => {
    if (items.length === 0) return
    setSaving(true)
    try {
      await onSave(items.join(', '), excludedItems)
      setExpanded(false)
    } finally {
      setSaving(false)
    }
  }

  // Adding/removing/editing a chip only touches local state -- nothing
  // reaches the server (and no rerank fires) until Save is clicked. Without
  // a visible cue, that's easy to miss: a removed chip disappears from the
  // list looking "done," so surface it explicitly rather than relying on
  // the user to remember an implicit save step.
  const isDirty =
    items.join(', ') !== (profile?.raw_text.trim() ?? '') ||
    excludedItems.join(', ') !== (profile?.excluded_keywords.join(', ') ?? '')

  if (!expanded && items.length > 0) {
    return (
      <div className="rounded-lg border border-black/10 dark:border-white/10 p-3 flex items-center justify-between gap-3">
        <p className="text-sm min-w-0 truncate">
          <span className="text-black/40 dark:text-white/40">{t('interests.heading')}: </span>
          {items.join('、')}
          {excludedItems.length > 0 && (
            <span className="text-black/40 dark:text-white/40">
              {'  '}
              {t('interests.excludeSummaryLabel')} {excludedItems.join('、')}
            </span>
          )}
        </p>
        <button
          onClick={() => setExpanded(true)}
          className="shrink-0 text-sm font-medium text-purple-600 dark:text-purple-400 hover:underline"
        >
          {t('interests.summaryEdit')}
        </button>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-black/10 dark:border-white/10 p-4 flex flex-col gap-3">
      <div>
        <h2 className="font-display font-semibold">{t('interests.heading')}</h2>
        <p className="text-sm text-black/60 dark:text-white/60">{t('interests.description')}</p>
      </div>

      {items.length === 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-black/40 dark:text-white/40">{t('onboarding.getStarted')}</span>
          {STARTER_SUGGESTION_KEYS.map((key) => (
            <button
              key={key}
              onClick={() => addSuggestion(t(key))}
              className="px-2.5 py-1 rounded-full bg-black/5 dark:bg-white/10 text-black/70 dark:text-white/70 hover:bg-black/10 dark:hover:bg-white/20"
            >
              {t(key)}
            </button>
          ))}
        </div>
      )}

      {items.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item, i) => (
            <span
              key={`${item}-${i}`}
              className="inline-flex items-center gap-1.5 pl-3 pr-1.5 py-1 rounded-full bg-purple-600/10 text-purple-700 dark:text-purple-300 text-sm"
            >
              <button
                onClick={() => editItem(i)}
                title={t('interests.clickToEdit')}
                className="hover:underline"
              >
                {item}
              </button>
              <button
                onClick={() => removeItem(i)}
                aria-label={t('interests.remove', { item })}
                className="w-4 h-4 flex items-center justify-center rounded-full hover:bg-purple-600/20"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={newItemText}
          onChange={(e) => setNewItemText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              addItem()
            }
          }}
          placeholder={t('interests.addPlaceholder')}
          className="flex-1 rounded-md border border-black/10 dark:border-white/10 bg-transparent px-3 py-2 text-sm"
        />
        <button
          onClick={addItem}
          disabled={!newItemText.trim()}
          className="px-3 py-2 rounded-md border border-black/10 dark:border-white/10 text-sm font-medium disabled:opacity-40"
        >
          {t('interests.add')}
        </button>
      </div>

      {showPaste ? (
        <div className="flex flex-col gap-2 rounded-md border border-black/10 dark:border-white/10 p-3">
          <p className="text-xs text-black/50 dark:text-white/50">{t('interests.pasteHint')}</p>
          <textarea
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            rows={2}
            placeholder={t('interests.pastePlaceholder')}
            className="w-full rounded-md border border-black/10 dark:border-white/10 bg-transparent p-2 text-sm resize-none"
          />
          <div className="flex gap-2">
            <button
              onClick={addFromPaste}
              disabled={!pasteText.trim()}
              className="px-3 py-1.5 rounded-md bg-black/5 dark:bg-white/10 text-sm font-medium disabled:opacity-40"
            >
              {t('interests.splitButton')}
            </button>
            <button
              onClick={() => {
                setShowPaste(false)
                setPasteText('')
              }}
              className="px-3 py-1.5 rounded-md text-sm text-black/50 dark:text-white/50 hover:underline"
            >
              {t('interests.cancel')}
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setShowPaste(true)}
          className="self-start text-xs text-black/50 dark:text-white/50 hover:underline"
        >
          {t('interests.pasteToggle')}
        </button>
      )}

      <div className="border-t border-black/10 dark:border-white/10 pt-3 flex flex-col gap-2">
        <div>
          <h3 className="font-display text-sm font-medium text-black/70 dark:text-white/70">{t('interests.excludeHeading')}</h3>
          <p className="text-xs text-black/50 dark:text-white/50">{t('interests.excludeDescription')}</p>
        </div>

        {excludedItems.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {excludedItems.map((item, i) => (
              <span
                key={`${item}-${i}`}
                className="inline-flex items-center gap-1.5 pl-3 pr-1.5 py-1 rounded-full bg-black/5 dark:bg-white/10 text-black/60 dark:text-white/60 text-sm"
              >
                <span className="line-through decoration-black/30 dark:decoration-white/30">{item}</span>
                <button
                  onClick={() => removeExcluded(i)}
                  aria-label={t('interests.removeExcluded', { item })}
                  className="w-4 h-4 flex items-center justify-center rounded-full hover:bg-black/10 dark:hover:bg-white/20"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <input
            type="text"
            value={newExcludedText}
            onChange={(e) => setNewExcludedText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addExcluded()
              }
            }}
            placeholder={t('interests.excludeAddPlaceholder')}
            className="flex-1 rounded-md border border-black/10 dark:border-white/10 bg-transparent px-3 py-2 text-sm"
          />
          <button
            onClick={addExcluded}
            disabled={!newExcludedText.trim()}
            className="px-3 py-2 rounded-md border border-black/10 dark:border-white/10 text-sm font-medium disabled:opacity-40"
          >
            {t('interests.add')}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={submit}
          disabled={saving || items.length === 0}
          className={`self-start px-4 py-2 rounded-md text-white text-sm font-medium disabled:opacity-50 ${
            isDirty && !saving ? 'bg-purple-600 ring-2 ring-purple-400 dark:ring-purple-300' : 'bg-purple-600'
          }`}
        >
          {saving ? t('interests.saving') : t('interests.save')}
        </button>
        {isDirty && !saving && (
          <span className="text-xs text-amber-600 dark:text-amber-400">{t('interests.unsaved')}</span>
        )}
      </div>
    </div>
  )
}
