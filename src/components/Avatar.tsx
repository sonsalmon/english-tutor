import type { Partner } from '../lib/partners';

export function Avatar({ partner, size }: { partner: Partner; size: number }) {
  return (
    <span className="block shrink-0 overflow-hidden rounded-full bg-line" style={{ width: size, height: size }}>
      <img src={partner.portrait} alt="" width={size} height={size} className="size-full object-cover" />
    </span>
  );
}
