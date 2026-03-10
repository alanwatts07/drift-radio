"use client";

export default function ListenerCount({ count }: { count: number }) {
  return (
    <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
      <span className="w-2 h-2 rounded-full bg-[var(--accent)] inline-block" />
      {count} listener{count !== 1 ? "s" : ""}
    </div>
  );
}
