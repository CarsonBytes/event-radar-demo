import { useLanguage } from '../i18n'
import type { DebugStatus } from '../types'

// Moved out of the footer into its own tab -- the full text (data-source
// attribution, IP notice, liability/jurisdiction clauses) is long enough
// that it was dominating every page's footer; a dedicated tab keeps it
// fully readable while the footer itself stays a one-line copyright bar.
export default function DisclaimerView({ debugStatus }: { debugStatus: DebugStatus | null }) {
  const { t } = useLanguage()
  const isDemo = debugStatus?.demo_mode ?? false

  return (
    <div className="max-w-2xl mx-auto">
      <p className="text-sm leading-relaxed whitespace-pre-line text-black/70 dark:text-white/70">
        {t(isDemo ? 'footer.demoDisclaimer' : 'footer.disclaimer')}
      </p>
    </div>
  )
}
