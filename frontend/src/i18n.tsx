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
    'app.title': '瘣餃??琿?',
    'app.tagline': '?箔???撠?銵脰?銝剖?????瘣餃???,
    refresh: '??渡?',
    refreshing: '??渡?銝凌?,
    loading: '頛銝凌?,

    'tab.suggestions': '?刻',
    'tab.events': '瘣餃?',
    'tab.upcoming': '?喳???',
    'tab.ongoing': '?脰?銝?,
    'tab.far_future': '撠?颲?,
    'tab.past': '撌脩???,
    'tab.timeline': '??頠?,
    'tab.saved': '?嗉?',
    'tab.insights': '?豢?瘣?',

    'suggestions.modeList': '?”',
    'suggestions.modeSwipe': '皛?',
    'swipe.pass': '銝??閎',
    'swipe.save': '?嗉?',
    'swipe.remaining': '?拚? {n} ??,
    'swipe.done': '撌脩???隞活??佗?蝔???靘????嚗?,

    'status.upcoming': '?喳???',
    'status.ongoing': '?脰?銝?,
    'status.far_future': '撠?颲?,
    'status.past': '撌脩???,

    'filter.placeholder': '隞仿??萄?蝭拚 ??璅???憿?售?,
    'filter.clear': '皜?摮祟??,
    'filter.suggestedKeywords': '撱箄降?摮?',
    'filter.filteringBy': '蝭拚璇辣嚗?,
    'filter.clearTag': '皜蝭拚',

    'empty.noMatch': '瘝?蝚血?蝭拚璇辣?暑??,
    'empty.noEvents': '?怎瘣餃? ??隢銝閮剖?雿??閎銝行???渡???,
    'empty.noSaved': '撠?嗉?隞颱?瘣餃? ???暑??銝????? ?喳?嗉???,
    'empty.noSuggestions': '?急?瘝?擃漲蝚血??暑????隢銝?啣??游??閎嚗??亦??脰?銝准??撠?銵汗?券瘣餃???,

    'event.matchTier.high': '擃漲蝚血?',
    'event.matchTier.mid': '銝剖漲蝚血?',
    'event.matchTier.low': '頛?蝚血?',
    'event.matchUnscored': '撠閰?',
    'event.matchUnscoredHint': '?暑??脣?祈憚 AI 閰???嚗??摮?隤????嚗?銝阡???摨虫???,
    'event.matchedOn': '??靘?嚗?,
    'event.match': '??? {score}',
    'event.viewSource': '?亦?靘? ??,
    'event.addToCalendar': '??交?',
    'event.addToCalendarIcs': '銝? .ics嚗utlook / Apple ?交??剁?',
    'event.save': '?嗉?',
    'event.unsave': '???嗉?',
    'event.startingSoon': '撌脫?暑?撠?憪?{time}',
    'event.moreLikeThis': '?游???',
    'event.lessLikeThis': '頛???',
    'event.venueTba': '?游敺?',
    'event.viewOnMap': '??Google ?啣??亦?',
    'event.notFound': '?曆??圈暑???航撌脰◤蝘駁嚗?,

    'modal.close': '??',

    'ask.placeholder': '??憿?靘?嚗?望??祥?嗅?瘣餃?嚗?,
    'ask.submit': '?澆?',
    'ask.quotaExhausted': '隞?祥 AI ??撌脩摰?隢???蔭敺?閰艾?,
    'ask.error': '?急??⊥???嚗?蝔??岫??,
    'ask.historyShow': '甇瑕蝝??,
    'ask.historyHide': '?嗉絲甇瑕蝝??,
    'ask.historyEmpty': '?怎??蝝??,
    'ask.suggestion.weekend': '?Ｗ望?瘣餃?嚗?,
    'ask.suggestion.free': '??祥瘣餃?嚗?,
    'ask.suggestion.now': '?振?瘣餃??脰?蝺?',
    'ask.suggestion.concerts': '?Ｗ??瞍??',
    'ask.suggestion.new': '??啣??亙?瘣餃?嚗?,

    'interests.heading': '雿??閎',
    'interests.description': '???啣?雿??閎?摰????犖??????隡蜓憿?,
    'onboarding.getStarted': '銝敺??交?嚗岫閰佗?',
    'onboarding.liveMusic': '?單?瞍',
    'onboarding.theatre': '???,
    'onboarding.artExhibitions': '??撅汗',
    'onboarding.familyFriendly': '閬芸?瘣餃?',
    'onboarding.food': '蝢?',
    'onboarding.bookFairs': '?詨?',
    'onboarding.tech': '蝘?撅?,
    'onboarding.dance': '??',
    'interests.addPlaceholder': '靘?嚗蝡?皛暹??望?',
    'interests.add': '?啣?',
    'interests.clickToEdit': '暺?蝺刻摩',
    'interests.remove': '蝘駁 {item}',
    'interests.pasteToggle': '+ ?寧鞎潔?摰?膩',
    'interests.pasteHint': '鞎潔?摰?膩嚗頂蝯望??芸?????閎???,
    'interests.pastePlaceholder': '靘?嚗蝡?皛曉??餃??單?蝭?I/ML???BA鞈賭??隞??銵?,
    'interests.splitButton': '???箄?頞????,
    'interests.cancel': '??',
    'interests.excludeHeading': '銝??摰?,
    'interests.excludeDescription': '?Ⅱ??店嚗雿輸??萄???憿蝚佗???瘣餃??賭??脣 AI 閰????,
    'interests.excludeAddPlaceholder': '靘?嚗??脰魚鈭扛摮暑??,
    'interests.removeExcluded': '蝘駁?item}??,
    'interests.summaryEdit': '蝺刻摩',
    'interests.excludeSummaryLabel': '銝?嚗?,
    'interests.save': '?脣??閎',
    'interests.saving': '?脣?銝凌?,
    'interests.unsaved': '??脣??????????寞??摮???敶梢??蝯?',

    'status.savedReranking':
      '?閎撌脣摮???蝟餌絞甇????箸??暑???????券瘣餃??航?閬??喳??嚗?蝔??亦?嚗????唳??,
    'status.fetching': '甇??瑕???唳暑??,
    'status.fetchedSummary': '撌脫??{fetched} ?暑??{new} ?憓?{updated} ??堆??頂蝯望迤?刻??舫??啗?????隢?敺???圈?撠??詻?,

    'debug.rerankInProgress': '?閰?銝凌?,
    'debug.rerankInProgressWithBatches': '?閰?銝凌佗?{done}/{total} ?寞活嚗?,
    'debug.rerankSkippedNotDue': '???撌脫??堆??思??閬??啗???,
    'debug.lastRerank': '銝活?閰?嚗time}嚗outcome}嚗?,
    'debug.outcomeOk': '??',
    'debug.outcomeError': '?潛??航炊',
    'debug.outcomeSkipped': '撌脩??,
    'debug.neverReranked': '撠?瑁????啗???,
    'debug.quotaUsage': '隞 AI ?券?嚗used}/{cap}',
    'debug.quotaExhausted':
      '?? 隞?祥 AI ??撌脩摰?瘥 200 甈∟?瘙???頝典?獢?剁?嚗?暑??????航?芸??冽?堆?撠???蔭敺?敺押?,

    'footer.lastUpdated': '?敺?堆?{time}',
    'footer.demoBanner': '蝷箇?? ????蝷?DATA.GOV.HK ?祇???豢?',
    'footer.demoDisclaimer':
      '?痊?脫?嚗蝬脩??箏犖雿??內蝭雯蝡?撅內銋暑??閮?其???DATA.GOV.HK嚗?皜舀摨?蝡??豢?撟喳嚗???銋?????鞈??勗熒璅???鈭?蝵莎?LCSD嚗????桃巨蝬莎?URBTIX嚗撣??DATA.GOV.HK 雿輻璇狡嚗府蝑?雿?璆剖???璆剔??曹蝙?剁???閮餅??箄??Ⅱ隤摨??亥??Ｘ??蝬脩?銝??豢?銋?蝣箸扼??湔扳??單??找??箔遙雿?霅?銝?誑 DATA.GOV.HK ?熒璅???鈭?蝵脖???鞈??箸???,

    'timeline.byScore': '??撠???,
    'timeline.byCategory': '??憿?,
    'timeline.showUnscored': '憿舐內?芾???{n}嚗?,
    'timeline.tier.great': '擃漲?? (70+)',
    'timeline.tier.good': '?臬末?? (40-69)',
    'timeline.tier.some': '?交?? (1-39)',
    'timeline.tier.unscored': '?芾???,
    'timeline.longRunning': '{n} ??巨霅?撣貉身撅汗嚗???5憭抬??芷＊蝷???隢??銵冽炎閬?,
    'timeline.noEvents': '瘝??喳????脰?銝剔?瘣餃??臬??頠賊＊蝷箝?,
    'timeline.uncategorized': '?芸?憿?,

    'insights.noData': '?怎?豢???,
    'insights.rankingQuality': '???釭嚗誑???箸?璅?',
    'insights.overall': '蝮質?嚗up} ?? / {down} ??',
    'insights.noFeedback': '?怎??',
    'insights.llmUsage': '?祆??函? LLM 雿輻??,
    'insights.today': '隞',
    'insights.totalCalls': '蝮賢?急活??,
    'insights.totalCost': '蝮質鞎?,
    'insights.avgLatency': '撟喳?撱園',
    'insights.sharedQuota': '?曹澈 LLM 憿漲嚗uant + study + events嚗?,
    'insights.todayAllProjects': '隞嚗???獢?,
    'insights.costTodayAllProjects': '隞?梯祥嚗???獢?,
    'insights.thisAppsShare': '?祆??函?隞賡?',
    'insights.calls': '{n} 甈∪??,
    'insights.ingestRuns': '?瑕?閮?',
    'insights.noIngestRuns': '?怎?瑕?閮???,
    'insights.ingestSummary': '撌脫??{fetched} 繚 ?啣? {new} 繚 ?湔 {updated} 繚 撌脰???{ranked}',

    'lang.zh': '銝剜?',
    'lang.en': 'EN',
  },
  en: {
    'app.title': 'Event Radar',
    'app.tagline': 'Upcoming, ongoing, and just-past events picked for you.',
    refresh: 'Refresh',
    refreshing: 'Refreshing??,
    loading: 'Loading??,

    'tab.suggestions': 'Suggestions',
    'tab.events': 'Events',
    'tab.upcoming': 'Upcoming',
    'tab.ongoing': 'Ongoing',
    'tab.far_future': 'Far Future',
    'tab.past': 'Past',
    'tab.timeline': 'Timeline',
    'tab.saved': 'Saved',
    'tab.insights': 'Insights',

    'suggestions.modeList': 'List',
    'suggestions.modeSwipe': 'Swipe',
    'swipe.pass': 'Not interested',
    'swipe.save': 'Save',
    'swipe.remaining': '{n} left',
    'swipe.done': "You've been through today's picks ??check back later for new matches!",

    'status.upcoming': 'upcoming',
    'status.ongoing': 'ongoing',
    'status.far_future': 'far future',
    'status.past': 'past',

    'filter.placeholder': 'Filter by keyword ??title, category, venue??,
    'filter.clear': 'Clear keyword filter',
    'filter.suggestedKeywords': 'Suggested keywords:',
    'filter.filteringBy': 'Filtering by',
    'filter.clearTag': 'Clear filter',

    'empty.noMatch': 'No events match your filter.',
    'empty.noEvents': 'No events yet ??set your interests above and hit Refresh.',
    'empty.noSaved': "Nothing saved yet ??tap ?? in an event card's top corner to save it.",
    'empty.noSuggestions': 'No high-confidence matches yet ??add more interests above, or browse Ongoing/Upcoming for everything.',

    'event.matchTier.high': 'Great match',
    'event.matchTier.mid': 'Good match',
    'event.matchTier.low': 'Loose match',
    'event.matchUnscored': 'Not yet scored',
    'event.matchUnscoredHint': "This event wasn't in this round's AI-scoring candidate pool (ranked by keyword/semantic score) ??it's not a low match, it just wasn't checked.",
    'event.matchedOn': 'Matched on:',
    'event.match': 'Match score {score}',
    'event.viewSource': 'View source ??,
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
    'ask.quotaExhausted': "Today's free AI quota is used up ??try again after it resets.",
    'ask.error': "Couldn't get an answer right now ??try again shortly.",
    'ask.historyShow': 'History',
    'ask.historyHide': 'Hide history',
    'ask.historyEmpty': 'No questions asked yet.',
    'ask.suggestion.weekend': "What's on this weekend?",
    'ask.suggestion.free': 'Any free events?',
    'ask.suggestion.now': "What's happening right now?",
    'ask.suggestion.concerts': 'Any concerts this month?',
    'ask.suggestion.new': 'Any newly added events?',

    'interests.heading': 'Your interests',
    'interests.description': "Add what you're into, one at a time ??artists, genres, sports teams, topics.",
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
    'interests.saving': 'Saving??,
    'interests.unsaved': "Unsaved changes ??won't affect matches until you save",

    'status.savedReranking':
      'Interests saved ??re-ranking every event against them now in the background (the full catalog can take a minute or two). Check back shortly, or hit Refresh.',
    'status.fetching': 'Fetching latest events??,
    'status.fetchedSummary':
      'Fetched {fetched} events ({new} new, {updated} updated). Re-ranking runs in the background ??check back in a bit for updated match scores.',

    'debug.rerankInProgress': 'Reranking??,
    'debug.rerankInProgressWithBatches': 'Reranking??({done}/{total} batches)',
    'debug.rerankSkippedNotDue': 'Match scores are already up to date ??no rerank needed right now',
    'debug.lastRerank': 'Last rerank: {time} ({outcome})',
    'debug.outcomeOk': 'succeeded',
    'debug.outcomeError': 'failed',
    'debug.outcomeSkipped': 'skipped',
    'debug.neverReranked': 'No rerank has run yet',
    'debug.quotaUsage': "Today's AI usage: {used}/{cap}",
    'debug.quotaExhausted':
      "?? Today's free AI quota is used up (200 requests/day, shared across projects) ??some match scores may not be fully updated until it resets.",

    'footer.lastUpdated': 'Last updated: {time}',
    'footer.demoBanner': 'Demo build ??showing DATA.GOV.HK open data only',
    'footer.demoDisclaimer':
      "Disclaimer: This site is a personal portfolio demonstration displaying event data sourced entirely from DATA.GOV.HK, Hong Kong's official open data portal. The underlying data is published by the Leisure and Cultural Services Department (LCSD) via URBTIX. Under DATA.GOV.HK's Terms of Use, this data may be freely used for both commercial and non-commercial purposes, provided the source is acknowledged and the Government's intellectual property rights are recognized. No guarantee is made as to the accuracy, completeness, or timeliness of the information shown ??DATA.GOV.HK and LCSD's original data always take precedence.",

    'timeline.byScore': 'By match score',
    'timeline.byCategory': 'By category',
    'timeline.showUnscored': 'Show unscored ({n})',
    'timeline.tier.great': 'Great match (70+)',
    'timeline.tier.good': 'Good match (40-69)',
    'timeline.tier.some': 'Some overlap (1-39)',
    'timeline.tier.unscored': 'Unscored',
    'timeline.longRunning': '{n} long-running passes/permanent exhibits (45+ days) not shown ??see the list view instead.',
    'timeline.noEvents': 'No upcoming or ongoing events to show on the timeline.',
    'timeline.uncategorized': 'Uncategorized',

    'insights.noData': 'No data yet.',
    'insights.rankingQuality': 'Ranking quality (feedback-based proxy)',
    'insights.overall': 'Overall: {up} ?? / {down} ??',
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
    'insights.ingestSummary': '{fetched} fetched 繚 {new} new 繚 {updated} updated 繚 {ranked} ranked',

    'lang.zh': '銝剜?',
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
