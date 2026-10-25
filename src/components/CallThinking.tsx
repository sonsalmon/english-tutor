export function CallThinking({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="inline-flex gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} style={{ animationDelay: `${i * 180}ms` }} className="size-1.5 rounded-full bg-ink-soft motion-safe:animate-pulse" />
        ))}
      </span>
      {name} 생각하는 중이에요
    </span>
  );
}
