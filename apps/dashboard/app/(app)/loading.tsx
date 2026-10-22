// Shown at once while a page fetches its data, so a click answers immediately instead of looking frozen.
export default function Loading() {
  return (
    <div className="flex flex-col gap-6 animate-pulse" role="status" aria-label="Loading">
      <div className="flex flex-col gap-2">
        <div className="h-7 w-40 rounded-md bg-muted" />
        <div className="h-4 w-64 max-w-full rounded-md bg-muted" />
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-4">
        {[0, 1, 2].map((i) => <div key={i} className="h-24 rounded-xl bg-muted" />)}
      </div>
      <div className="h-56 rounded-xl bg-muted" />
    </div>
  );
}
