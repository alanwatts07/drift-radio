"use client";

export interface QueueTrack {
  title: string;
  artist: string;
  album_art?: string;
}

interface Props {
  tracks: QueueTrack[];
  queuedBy: Map<string, string>; // track title -> person's name
  onRefresh?: () => void;
}

export default function Queue({ tracks, queuedBy, onRefresh }: Props) {
  if (!tracks.length) return null;

  return (
    <div className="w-full space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider">
          Up Next
        </h2>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="text-xs text-[var(--muted)] hover:text-[var(--foreground)] transition-colors px-2 py-1"
            title="Refresh queue"
          >
            ↻
          </button>
        )}
      </div>
      <div className="space-y-1">
        {tracks.map((t, i) => {
          const requestedBy = queuedBy.get(t.title);
          return (
            <div
              key={i}
              className="flex items-center gap-3 p-2 rounded-lg"
            >
              <span className="text-xs text-[var(--muted)] w-5 text-right">{i + 1}</span>
              {t.album_art ? (
                <img src={t.album_art} alt="" className="w-8 h-8 rounded" />
              ) : (
                <div className="w-8 h-8 rounded bg-[var(--border)]" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm">{t.title}</p>
                  {requestedBy && (
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ background: "var(--accent)" }} />
                  )}
                </div>
                <p className="truncate text-xs text-[var(--muted)]">
                  {t.artist}
                  {requestedBy && (
                    <span style={{ color: "var(--accent)" }}> · requested by {requestedBy}</span>
                  )}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
