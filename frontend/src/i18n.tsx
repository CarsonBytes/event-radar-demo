import { createContext, useContext, useState, type ReactNode } from 'react'

export type Lang = 'zh-Hant' | 'en'

const STORAGE_KEY = 'event-radar-lang'

// Defaults to Traditional Chinese -- this is a Hong Kong events app, and
// most of the underlying source data (URBTIX) is Traditional Chinese
// natively; English is the secondary/switchable option, not the other way
// around.
const DEFAULT_LANG: Lang = 'zh-Hant'

const STRINGS: Record<Lang, Record<string, string>> = {
  'zh-Hant': {
    'app.title': '活動雷達',
    'app.tagline': '為你挑選的即將舉行、進行中及剛結束的活動。',
    'app.taglineNote': '活動資訊彙整自公開數據，請以官方公告為準。',
    refresh: '重新整理',
    refreshing: '重新整理中…',
    loading: '載入中…',

    'tab.suggestions': '推薦',
    'tab.events': '活動',
    'tab.upcoming': '即將舉行',
    'tab.ongoing': '進行中',
    'tab.far_future': '將舉辦',
    'tab.past': '已結束',
    'tab.timeline': '時間軸',
    'tab.saved': '收藏',
    'tab.insights': '數據洞察',
    'tab.disclaimer': '免責聲明與資料來源',

    'suggestions.modeList': '列表',
    'suggestions.modeSwipe': '滑動',
    'swipe.pass': '不感興趣',
    'swipe.save': '收藏',
    'swipe.remaining': '剩餘 {n} 個',
    'swipe.done': '已經看完今次嘅推薦，稍後再回來看看新配對！',

    'status.upcoming': '即將舉行',
    'status.ongoing': '進行中',
    'status.far_future': '將舉辦',
    'status.past': '已結束',

    'filter.placeholder': '以關鍵字篩選 — 標題、分類、場地…',
    'filter.clear': '清除關鍵字篩選',
    'filter.suggestedKeywords': '建議關鍵字：',
    'filter.filteringBy': '篩選條件：',
    'filter.clearTag': '清除篩選',
    'filter.categories': '瀏覽分類：',

    'search.placeholder': '搜尋全部活動…',
    'search.clear': '清除搜尋',
    'search.resultsCount': '找到 {n} 個符合「{q}」的活動（搜尋整個目錄）',
    'search.noResults': '整個目錄都沒有符合「{q}」的活動。',
    'search.minChars': '請輸入至少兩個字元。',

    'list.loadMore': '顯示更多（還有 {n} 個）',

    'saved.exportAll': '匯出全部 (.ics)',

    'tab.newBadge': '+{n} 新',

    'sort.score': '配對分數',
    'sort.date': '日期',

    'empty.noMatch': '沒有符合篩選條件的活動。',
    'empty.noEvents': '暫無活動 — 請在上方設定你的興趣並按重新整理。',
    'empty.noSaved': '尚未收藏任何活動 — 按活動卡片右上角的 📑 即可收藏。',
    'empty.noSuggestions': '暫時沒有高度符合的活動 — 請在上方新增更多興趣，或查看「進行中」／「即將舉行」瀏覽全部活動。',

    'event.matchTier.high': '高度符合',
    'event.matchTier.mid': '中度符合',
    'event.matchTier.low': '較低符合',
    'event.matchUnscored': '尚未評分',
    'event.matchUnscoredHint': '這個活動未進入本輪 AI 評分的候選名單（依關鍵字/語意分數排序），並非配對度低。',
    'event.matchedOn': '配對依據：',
    'event.match': '配對分數 {score}',
    'event.viewSource': '查看來源 →',
    'event.addToCalendar': '加入日曆',
    'event.addToCalendarIcs': '下載 .ics（Outlook / Apple 日曆用）',
    'event.save': '收藏',
    'event.unsave': '取消收藏',
    'event.startingSoon': '已收藏活動即將開始：{time}',
    'event.moreLikeThis': '更多同類',
    'event.lessLikeThis': '較少同類',
    'event.venueTba': '場地待定',
    'event.viewOnMap': '在 Google 地圖查看',
    'event.notFound': '找不到這個活動（可能已被移除）。',

    'modal.close': '關閉',

    'ask.placeholder': '問問題，例如：呢個週末有咩免費戶外活動？',
    'ask.submit': '發問',
    'ask.quotaExhausted': '今日免費 AI 配額已用完，請於配額重置後再試。',
    'ask.error': '暫時無法回答，請稍後再試。',
    'ask.historyShow': '歷史紀錄',
    'ask.historyHide': '收起歷史紀錄',
    'ask.historyEmpty': '暫無提問紀錄。',
    'ask.suggestion.weekend': '呢個週末有咩活動？',
    'ask.suggestion.free': '有咩免費活動？',
    'ask.suggestion.now': '而家有咩活動進行緊？',
    'ask.suggestion.concerts': '呢個月有咩演唱會？',
    'ask.suggestion.new': '有咩新加入嘅活動？',

    'interests.heading': '你的興趣',
    'interests.description': '逐項新增你感興趣的內容 — 藝人、類型、運動隊伍、主題。',
    'onboarding.getStarted': '不知從何入手？試試：',
    'onboarding.liveMusic': '音樂演出',
    'onboarding.theatre': '舞台劇',
    'onboarding.artExhibitions': '藝術展覽',
    'onboarding.familyFriendly': '親子活動',
    'onboarding.food': '美食',
    'onboarding.bookFairs': '書展',
    'onboarding.tech': '科技展',
    'onboarding.dance': '舞蹈',
    'interests.addPlaceholder': '例如：獨立搖滾演唱會',
    'interests.add': '新增',
    'interests.clickToEdit': '點擊編輯',
    'interests.remove': '移除 {item}',
    'interests.pasteToggle': '+ 改為貼上完整描述',
    'interests.pasteHint': '貼上完整描述，系統會自動拆分成個別興趣項目。',
    'interests.pastePlaceholder': '例如：獨立搖滾及電子音樂節、AI/ML研討會、NBA賽事、當代藝術',
    'interests.splitButton': '拆分為興趣項目',
    'interests.cancel': '取消',
    'interests.excludeHeading': '不想看到的內容',
    'interests.excludeDescription': '明確列出的話，即使關鍵字或分類相符，這些活動都不會進入 AI 評分名單。',
    'interests.excludeAddPlaceholder': '例如：體育賽事、親子活動',
    'interests.removeExcluded': '移除「{item}」',
    'interests.summaryEdit': '編輯',
    'interests.excludeSummaryLabel': '不看：',
    'interests.save': '儲存興趣',
    'interests.saving': '儲存中…',
    'interests.unsaved': '有未儲存的變更 — 按上方按鈕儲存後才會影響配對結果',

    'status.savedReranking':
      '興趣已儲存 — 系統正在背景重新為所有活動評分（處理全部活動可能需要一至兩分鐘）。請稍後查看，或按重新整理。',
    'status.fetching': '正在擷取最新活動…',
    'status.fetchedSummary': '已擷取 {fetched} 個活動（{new} 個新增，{updated} 個更新）。系統正在背景重新評分 — 請稍後查看最新配對分數。',

    'debug.rerankInProgress': '重新評分中…',
    'debug.rerankInProgressWithBatches': '重新評分中…（{done}/{total} 批次）',
    'debug.rerankSkippedNotDue': '配對分數已是最新，暫不需要重新評分',
    'debug.lastRerank': '上次重新評分：{time}（{outcome}）',
    'debug.outcomeOk': '成功',
    'debug.outcomeError': '發生錯誤',
    'debug.outcomeSkipped': '已略過',
    'debug.neverReranked': '尚未執行過重新評分',
    'debug.quotaUsage': '今日 AI 用量：{used}/{cap}',
    'debug.quotaExhausted':
      '⚠️ 今日免費 AI 配額已用完（每日 200 次請求上限，跨專案共用），部分活動的配對分數可能未完全更新，將於配額重置後自動恢復。',

    'footer.lastUpdated': '最後更新：{time}',
    'footer.demoBanner': '示範版本 — 僅展示 DATA.GOV.HK 公開開放數據',
    'footer.demoDisclaimer':
      '免責聲明：本網站為個人作品集示範網站，展示之活動資訊全部來自 DATA.GOV.HK（香港政府一站式數據平台）所提供之公開數據，原始資料由康樂及文化事務署（LCSD）透過城市售票網（URBTIX）發布。根據 DATA.GOV.HK 使用條款，該等數據可作商業及非商業用途自由使用，惟須註明出處及確認政府之知識產權。本網站不對數據之準確性、完整性或即時性作出任何保證，一切以 DATA.GOV.HK 及康樂及文化事務署之原始資料為準。',
    'footer.copyright': '© 2026 Event Radar. Created by Carson Ng. All rights reserved.',
    'footer.disclaimerLink': '免責聲明與資料來源',

    'timeline.byScore': '按配對分數',
    'timeline.byCategory': '按分類',
    'timeline.showUnscored': '顯示未評分（{n}）',
    'timeline.tier.great': '高度配對 (70+)',
    'timeline.tier.good': '良好配對 (40-69)',
    'timeline.tier.some': '略有關聯 (1-39)',
    'timeline.tier.unscored': '未評分',
    'timeline.longRunning': '{n} 項長期票證／常設展覽（超過45天）未顯示 — 請查看列表檢視。',
    'timeline.noEvents': '沒有即將舉行或進行中的活動可在時間軸顯示。',
    'timeline.uncategorized': '未分類',

    'insights.noData': '暫無數據。',
    'insights.rankingQuality': '排名品質（以回饋為指標）',
    'insights.overall': '總計：{up} 👍 / {down} 👎',
    'insights.noFeedback': '暫無回饋',
    'insights.llmUsage': '本應用的 LLM 使用量',
    'insights.today': '今日',
    'insights.totalCalls': '總呼叫次數',
    'insights.totalCost': '總花費',
    'insights.avgLatency': '平均延遲',
    'insights.sharedQuota': '共享 LLM 額度（quant + study + events）',
    'insights.todayAllProjects': '今日，所有專案',
    'insights.costTodayAllProjects': '今日花費，所有專案',
    'insights.thisAppsShare': '本應用的份額',
    'insights.calls': '{n} 次呼叫',
    'insights.ingestRuns': '擷取記錄',
    'insights.noIngestRuns': '暫無擷取記錄。',
    'insights.ingestSummary': '已擷取 {fetched} · 新增 {new} · 更新 {updated} · 已評分 {ranked}',

    'lang.zh': '中文',
    'lang.en': 'EN',
  },
  en: {
    'app.title': 'Event Radar',
    'app.tagline': 'Upcoming, ongoing, and just-past events picked for you.',
    'app.taglineNote': 'Event information is aggregated from public data — please refer to official announcements for the latest details.',
    refresh: 'Refresh',
    refreshing: 'Refreshing…',
    loading: 'Loading…',

    'tab.suggestions': 'Suggestions',
    'tab.events': 'Events',
    'tab.upcoming': 'Upcoming',
    'tab.ongoing': 'Ongoing',
    'tab.far_future': 'Far Future',
    'tab.past': 'Past',
    'tab.timeline': 'Timeline',
    'tab.saved': 'Saved',
    'tab.insights': 'Insights',
    'tab.disclaimer': 'Disclaimer & Data Sources',

    'suggestions.modeList': 'List',
    'suggestions.modeSwipe': 'Swipe',
    'swipe.pass': 'Not interested',
    'swipe.save': 'Save',
    'swipe.remaining': '{n} left',
    'swipe.done': "You've been through today's picks — check back later for new matches!",

    'status.upcoming': 'upcoming',
    'status.ongoing': 'ongoing',
    'status.far_future': 'far future',
    'status.past': 'past',

    'filter.placeholder': 'Filter by keyword — title, category, venue…',
    'filter.clear': 'Clear keyword filter',
    'filter.suggestedKeywords': 'Suggested keywords:',
    'filter.filteringBy': 'Filtering by',
    'filter.clearTag': 'Clear filter',

    'search.placeholder': 'Search all events…',
    'search.clear': 'Clear search',
    'search.resultsCount': '{n} matches for "{q}" (searching the whole catalog)',
    'search.noResults': 'No events in the whole catalog match "{q}".',
    'search.minChars': 'Type at least two characters.',

    'list.loadMore': 'Load more ({n} more)',

    'saved.exportAll': 'Export all (.ics)',

    'tab.newBadge': '+{n} new',

    'empty.noMatch': 'No events match your filter.',
    'empty.noEvents': 'No events yet — set your interests above and hit Refresh.',
    'empty.noSaved': "Nothing saved yet — tap 📑 in an event card's top corner to save it.",
    'empty.noSuggestions': 'No high-confidence matches yet — add more interests above, or browse Ongoing/Upcoming for everything.',

    'event.matchTier.high': 'Great match',
    'event.matchTier.mid': 'Good match',
    'event.matchTier.low': 'Loose match',
    'event.matchUnscored': 'Not yet scored',
    'event.matchUnscoredHint': "This event wasn't in this round's AI-scoring candidate pool (ranked by keyword/semantic score) — it's not a low match, it just wasn't checked.",
    'event.matchedOn': 'Matched on:',
    'event.match': 'Match score {score}',
    'event.viewSource': 'View source →',
    'event.addToCalendar': 'Add to calendar',
    'event.addToCalendarIcs': 'Download .ics (Outlook / Apple Calendar)',
    'event.save': 'Save',
    'event.unsave': 'Remove from saved',
    'event.startingSoon': 'Saved event starting {time}',
    'event.moreLikeThis': 'More like this',
    'event.lessLikeThis': 'Less like this',
    'event.venueTba': 'Venue TBA',
    'event.viewOnMap': 'View on Google Maps',
    'event.notFound': "Couldn't find this event (it may have been removed).",

    'modal.close': 'Close',

    'ask.placeholder': 'Ask a question, e.g. any free outdoor events this weekend?',
    'ask.submit': 'Ask',
    'ask.quotaExhausted': "Today's free AI quota is used up — try again after it resets.",
    'ask.error': "Couldn't get an answer right now — try again shortly.",
    'ask.historyShow': 'History',
    'ask.historyHide': 'Hide history',
    'ask.historyEmpty': 'No questions asked yet.',
    'ask.suggestion.weekend': "What's on this weekend?",
    'ask.suggestion.free': 'Any free events?',
    'ask.suggestion.now': "What's happening right now?",
    'ask.suggestion.concerts': 'Any concerts this month?',
    'ask.suggestion.new': 'Any newly added events?',

    'interests.heading': 'Your interests',
    'interests.description': "Add what you're into, one at a time — artists, genres, sports teams, topics.",
    'onboarding.getStarted': "Not sure where to start? Try:",
    'onboarding.liveMusic': 'Live Music',
    'onboarding.theatre': 'Theatre',
    'onboarding.artExhibitions': 'Art Exhibitions',
    'onboarding.familyFriendly': 'Family Friendly',
    'onboarding.food': 'Food & Drink',
    'onboarding.bookFairs': 'Book Fairs',
    'onboarding.tech': 'Tech Expos',
    'onboarding.dance': 'Dance',
    'interests.addPlaceholder': 'e.g. indie rock concerts',
    'interests.add': 'Add',
    'interests.clickToEdit': 'Click to edit',
    'interests.remove': 'Remove {item}',
    'interests.pasteToggle': '+ paste a longer description instead',
    'interests.pasteHint': "Paste a longer description and it'll be split into separate interests automatically.",
    'interests.pastePlaceholder':
      'e.g. indie rock and electronic music festivals, AI/ML conferences, NBA games, contemporary art',
    'interests.splitButton': 'Split into interests',
    'interests.cancel': 'Cancel',
    'interests.excludeHeading': "Things you don't want to see",
    'interests.excludeDescription':
      "Listed here, an event won't enter the AI-scoring candidate pool at all, even if it also matches a keyword or category above.",
    'interests.excludeAddPlaceholder': 'e.g. sports events, kids activities',
    'interests.removeExcluded': 'Remove "{item}"',
    'interests.summaryEdit': 'Edit',
    'interests.excludeSummaryLabel': 'Excluding:',
    'interests.save': 'Save interests',
    'interests.saving': 'Saving…',
    'interests.unsaved': "Unsaved changes — won't affect matches until you save",

    'status.savedReranking':
      'Interests saved — re-ranking every event against them now in the background (the full catalog can take a minute or two). Check back shortly, or hit Refresh.',
    'status.fetching': 'Fetching latest events…',
    'status.fetchedSummary':
      'Fetched {fetched} events ({new} new, {updated} updated). Re-ranking runs in the background — check back in a bit for updated match scores.',

    'debug.rerankInProgress': 'Reranking…',
    'debug.rerankInProgressWithBatches': 'Reranking… ({done}/{total} batches)',
    'debug.rerankSkippedNotDue': 'Match scores are already up to date — no rerank needed right now',
    'debug.lastRerank': 'Last rerank: {time} ({outcome})',
    'debug.outcomeOk': 'succeeded',
    'debug.outcomeError': 'failed',
    'debug.outcomeSkipped': 'skipped',
    'debug.neverReranked': 'No rerank has run yet',
    'debug.quotaUsage': "Today's AI usage: {used}/{cap}",
    'debug.quotaExhausted':
      "⚠️ Today's free AI quota is used up (200 requests/day, shared across projects) — some match scores may not be fully updated until it resets.",

    'footer.lastUpdated': 'Last updated: {time}',
    'footer.demoBanner': 'Demo build — showing DATA.GOV.HK open data only',
    'footer.demoDisclaimer':
      "Disclaimer: This site is a personal portfolio demonstration displaying event data sourced entirely from DATA.GOV.HK, Hong Kong's official open data portal. The underlying data is published by the Leisure and Cultural Services Department (LCSD) via URBTIX. Under DATA.GOV.HK's Terms of Use, this data may be freely used for both commercial and non-commercial purposes, provided the source is acknowledged and the Government's intellectual property rights are recognized. No guarantee is made as to the accuracy, completeness, or timeliness of the information shown — DATA.GOV.HK and LCSD's original data always take precedence.",
    'footer.copyright': '© 2026 Event Radar. Created by Carson Ng. All rights reserved.',
    'footer.disclaimerLink': 'Disclaimer & Terms & Privacy Policy',

    'timeline.byScore': 'By match score',
    'timeline.byCategory': 'By category',
    'timeline.showUnscored': 'Show unscored ({n})',
    'timeline.tier.great': 'Great match (70+)',
    'timeline.tier.good': 'Good match (40-69)',
    'timeline.tier.some': 'Some overlap (1-39)',
    'timeline.tier.unscored': 'Unscored',
    'timeline.longRunning': '{n} long-running passes/permanent exhibits (45+ days) not shown — see the list view instead.',
    'timeline.noEvents': 'No upcoming or ongoing events to show on the timeline.',
    'timeline.uncategorized': 'Uncategorized',

    'insights.noData': 'No data yet.',
    'insights.rankingQuality': 'Ranking quality (feedback-based proxy)',
    'insights.overall': 'Overall: {up} 👍 / {down} 👎',
    'insights.noFeedback': 'no feedback yet',
    'insights.llmUsage': "This app's LLM usage",
    'insights.today': 'Today',
    'insights.totalCalls': 'Total calls',
    'insights.totalCost': 'Total cost',
    'insights.avgLatency': 'Avg latency',
    'insights.sharedQuota': 'Shared LLM quota (quant + study + events)',
    'insights.todayAllProjects': 'Today, all projects',
    'insights.costTodayAllProjects': 'Cost today, all projects',
    'insights.thisAppsShare': "This app's share",
    'insights.calls': '{n} calls',
    'insights.ingestRuns': 'Ingest runs',
    'insights.noIngestRuns': 'No ingest runs yet.',
    'insights.ingestSummary': '{fetched} fetched · {new} new · {updated} updated · {ranked} ranked',

    'lang.zh': '中文',
    'lang.en': 'EN',
  },
}

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, key) => (key in params ? String(params[key]) : match))
}

type LanguageContextValue = {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (key: string, params?: Record<string, string | number>) => string
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

function loadInitialLang(): Lang {
  if (typeof window === 'undefined') return DEFAULT_LANG
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'en' || stored === 'zh-Hant' ? stored : DEFAULT_LANG
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(loadInitialLang)

  const setLang = (next: Lang) => {
    setLangState(next)
    window.localStorage.setItem(STORAGE_KEY, next)
  }

  const t = (key: string, params?: Record<string, string | number>) =>
    interpolate(STRINGS[lang][key] ?? STRINGS.en[key] ?? key, params)

  return <LanguageContext.Provider value={{ lang, setLang, t }}>{children}</LanguageContext.Provider>
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext)
  if (!ctx) throw new Error('useLanguage must be used within a LanguageProvider')
  return ctx
}
