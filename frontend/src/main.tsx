import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { reportClientError } from './api.ts'
import { LanguageProvider } from './i18n.tsx'

// Previously invisible unless someone happened to be watching the browser
// console live -- these now land in the same backend system-event log as
// rerank/ingest activity (GET /api/debug/events?category=frontend), so a
// frontend crash a user hits is actually debuggable after the fact.
window.addEventListener('error', (e) => {
  reportClientError(`Uncaught error: ${e.message}`, {
    stack: e.error?.stack,
    context: { filename: e.filename, lineno: e.lineno, colno: e.colno },
  })
})
window.addEventListener('unhandledrejection', (e) => {
  const reason = e.reason
  reportClientError(`Unhandled promise rejection: ${reason instanceof Error ? reason.message : String(reason)}`, {
    stack: reason instanceof Error ? reason.stack : undefined,
  })
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </StrictMode>,
)
