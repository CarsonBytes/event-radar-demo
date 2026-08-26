// Layout-matched placeholder for the loading state of a card list -- same
// block structure as EventCard (art area, title lines, tag row, action
// row) so switching from skeletons to real cards doesn't shift layout.
export default function SkeletonCard() {
  return (
    <div className="rounded-lg border border-black/10 dark:border-white/10 overflow-hidden" aria-hidden="true">
      <div className="h-32 w-full bg-black/5 dark:bg-white/10 animate-pulse" />
      <div className="p-4 flex flex-col gap-2.5">
        <div className="h-4 w-3/4 rounded bg-black/10 dark:bg-white/15 animate-pulse" />
        <div className="h-3 w-1/2 rounded bg-black/5 dark:bg-white/10 animate-pulse" />
        <div className="flex gap-2">
          <div className="h-5 w-16 rounded-full bg-black/5 dark:bg-white/10 animate-pulse" />
          <div className="h-5 w-20 rounded-full bg-black/5 dark:bg-white/10 animate-pulse" />
          <div className="h-5 w-24 rounded-full bg-black/5 dark:bg-white/10 animate-pulse" />
        </div>
        <div className="mt-1 flex justify-between">
          <div className="h-3 w-28 rounded bg-black/5 dark:bg-white/10 animate-pulse" />
          <div className="h-8 w-16 rounded bg-black/5 dark:bg-white/10 animate-pulse" />
        </div>
      </div>
    </div>
  )
}
