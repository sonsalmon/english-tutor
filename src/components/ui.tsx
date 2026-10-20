import { ChevronLeft, ChevronRight, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

export function Screen({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <main
      className={`mx-auto flex min-h-dvh w-full max-w-[480px] flex-col px-5 pt-[calc(12px+env(safe-area-inset-top))] pb-[calc(24px+env(safe-area-inset-bottom))] ${className}`}
    >
      {children}
    </main>
  );
}

export function TopBar({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <header className="-ml-2 mb-4 flex items-center gap-1">
      <button
        type="button"
        onClick={onBack}
        aria-label="뒤로"
        className="grid size-11 place-items-center rounded-full text-ink hover:bg-line/60"
      >
        <ChevronLeft size={24} aria-hidden />
      </button>
      <h1 className="text-lg font-bold">{title}</h1>
    </header>
  );
}

export function Portrait({
  size,
  level = 0,
  active = false,
  children,
}: {
  size: number;
  level?: number;
  active?: boolean;
  children?: ReactNode;
}) {
  const ring = active ? 1.06 + Math.min(level, 1) * 0.14 : 1;
  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <span
        aria-hidden
        className="absolute inset-0 rounded-full bg-call/20 transition-[transform,opacity] duration-150 ease-out"
        style={{ transform: `scale(${ring})`, opacity: active ? 1 : 0 }}
      />
      <div className="relative" style={{ width: size - 8, height: size - 8 }}>
        <img
          src="/ms-park.webp"
          alt="Ms. Park"
          width={size}
          height={size}
          className="size-full rounded-full bg-line object-cover"
        />
        {children}
      </div>
    </div>
  );
}

export function CallButton({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex min-h-14 w-full items-center justify-center gap-2 rounded-full bg-call px-6 text-lg font-bold text-white shadow-[0_6px_16px_-6px_rgb(18_161_80/0.6)] active:bg-call-press disabled:cursor-not-allowed disabled:bg-ink-soft/40 disabled:shadow-none"
    >
      {children}
    </button>
  );
}

export function QuietButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-12 w-full items-center justify-center gap-2 rounded-full border border-line bg-surface px-6 font-semibold text-ink hover:bg-paper"
    >
      {children}
    </button>
  );
}

export function RowLink({ icon: Icon, title, desc, onClick, trailing }: {
  icon?: LucideIcon;
  title: string;
  desc?: string;
  onClick: () => void;
  trailing?: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-4 px-4 py-4 text-left hover:bg-paper"
    >
      {Icon && (
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-paper text-ink" aria-hidden>
          <Icon size={20} />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{title}</span>
        {desc && <span className="mt-0.5 block text-sm text-ink-soft">{desc}</span>}
      </span>
      {trailing}
      <ChevronRight size={20} className="shrink-0 text-ink-soft" aria-hidden />
    </button>
  );
}

export function List({ children }: { children: ReactNode }) {
  return <div className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">{children}</div>;
}
