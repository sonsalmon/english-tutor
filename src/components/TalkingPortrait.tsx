import { useEffect, useId, useRef } from 'react';
import { Portrait } from './ui';

/*
 * Mouth geometry, measured on public/ms-park.webp (512x512).
 * The overlay box covers x 220..298, y 232..280 of the image, so it scales with the portrait size:
 * left 42.97%, top 45.31%, width 15.23%, height 9.38%. Path coordinates stay in image pixels.
 * Mouth corners (228,242) and (290,242); closed smile line y=244 at x=259; teeth bottom y=253; lower lip bottom y=262.
 */
const BOX = { x: 220, y: 232, w: 78, h: 48 };
const PCT = {
  left: `${(BOX.x / 512) * 100}%`,
  top: `${(BOX.y / 512) * 100}%`,
  width: `${(BOX.w / 512) * 100}%`,
  height: `${(BOX.h / 512) * 100}%`,
};
const LEFT = 228;
const RIGHT = 290;
const CORNER_Y = 242;
const MID_X = (LEFT + RIGHT) / 2;
const UPPER_MID_Y = 244;
const TEETH_BOTTOM_Y = 253;
const LIP_BOTTOM_Y = 262;
const MAX_DROP = 17;

// Colors sampled from the illustration.
const LIP = '#DD8870';
const LIP_LIGHT = '#EE947E';
const LIP_EDGE = '#B5604C';
const CORNER = '#562211';
const INSIDE = '#3A1612';
const TEETH = '#F6EBE3';
const TONGUE = '#C0605A';

// Pipecat's audio level is small in normal speech, so stretch it before easing.
const openingFor = (level: number) => Math.min(1, (Math.max(0, level) * 1.25) ** 0.8);

// Quadratic curve from corner to corner whose midpoint is at y = midY.
const arc = (midY: number, toX = RIGHT) => `Q ${MID_X} ${2 * midY - CORNER_Y} ${toX} ${CORNER_Y}`;

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// 입 모양 애니메이션은 ms-park.webp 좌표에 맞춰져 있어 mouth가 켜진 Ms. Park만 쓴다. 다른 상대는 말하는 링만 보여 준다.
export function TalkingPortrait({
  size,
  level = 0,
  active = false,
  src = '/ms-park.webp',
  alt = 'Ms. Park',
  mouth = true,
}: {
  size: number;
  level?: number;
  active?: boolean;
  src?: string;
  alt?: string;
  mouth?: boolean;
}) {
  const uid = useId();
  const clipId = `${uid}-mouth-clip`;
  const lipId = `${uid}-lip`;
  const levelRef = useRef(level);
  levelRef.current = level;
  const reduced = prefersReducedMotion() || !mouth;

  const group = useRef<SVGGElement | null>(null);
  const lowerLip = useRef<SVGPathElement | null>(null);
  const lowerLipEdge = useRef<SVGPathElement | null>(null);
  const inside = useRef<SVGPathElement | null>(null);
  const clip = useRef<SVGPathElement | null>(null);
  const teeth = useRef<SVGRectElement | null>(null);
  const tongue = useRef<SVGEllipseElement | null>(null);
  const upperEdge = useRef<SVGPathElement | null>(null);

  useEffect(() => {
    if (reduced) return;
    let open = 0;
    let last = performance.now();
    let frame = 0;

    const draw = (o: number) => {
      const drop = o * MAX_DROP;
      const insideBottom = TEETH_BOTTOM_Y + drop;
      const lipBottom = LIP_BOTTOM_Y + drop;
      const upper = `M ${LEFT} ${CORNER_Y} ${arc(UPPER_MID_Y)}`;
      const opening = `${upper} L ${RIGHT} ${CORNER_Y} ${arc(insideBottom, LEFT)} Z`;
      const lip = `M ${LEFT} ${CORNER_Y} ${arc(lipBottom)} Z`;
      const lipEdge = `M ${LEFT} ${CORNER_Y} ${arc(lipBottom)}`;
      group.current?.setAttribute('opacity', String(Math.min(1, o * 12)));
      lowerLip.current?.setAttribute('d', lip);
      lowerLipEdge.current?.setAttribute('d', lipEdge);
      inside.current?.setAttribute('d', opening);
      clip.current?.setAttribute('d', opening);
      upperEdge.current?.setAttribute('d', upper);
      teeth.current?.setAttribute('height', String(Math.min(8, 3 + drop * 0.5)));
      tongue.current?.setAttribute('cy', String(insideBottom + 2));
      tongue.current?.setAttribute('ry', String(Math.max(0, drop * 0.55)));
    };

    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const target = active ? openingFor(levelRef.current) : 0;
      // Open quickly, close a little slower, independent of frame rate.
      const tau = target > open ? 0.04 : 0.09;
      open += (target - open) * (1 - Math.exp(-dt / tau));
      if (!active && open < 0.003) {
        open = 0;
        draw(0);
        return;
      }
      draw(open);
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active, reduced]);

  if (!mouth) {
    const ring = active ? 1.06 + Math.min(level, 1) * 0.14 : 1;
    return (
      <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }}>
        <span
          aria-hidden
          className="absolute inset-0 rounded-full bg-call/20 transition-[transform,opacity] duration-150 ease-out"
          style={{ transform: `scale(${ring})`, opacity: active ? 1 : 0 }}
        />
        <div className="relative overflow-hidden rounded-full bg-line" style={{ width: size - 8, height: size - 8 }}>
          <img src={src} alt={alt} width={size} height={size} className="size-full object-cover" />
        </div>
      </div>
    );
  }

  return (
    <Portrait size={size} level={level} active={active}>
      {!reduced && (
          <svg
            aria-hidden
            viewBox={`${BOX.x} ${BOX.y} ${BOX.w} ${BOX.h}`}
            className="pointer-events-none absolute overflow-visible"
            style={PCT}
          >
            <defs>
              <linearGradient id={lipId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor={LIP} />
                <stop offset="0.7" stopColor={LIP_LIGHT} />
                <stop offset="1" stopColor={LIP} />
              </linearGradient>
              <clipPath id={clipId}>
                <path ref={clip} d="" />
              </clipPath>
            </defs>
            <g ref={group} opacity="0">
              <path ref={lowerLip} d="" fill={`url(#${lipId})`} />
              <path ref={lowerLipEdge} d="" fill="none" stroke={LIP_EDGE} strokeWidth="1.2" strokeLinecap="round" />
              <path ref={inside} d="" fill={INSIDE} />
              <g clipPath={`url(#${clipId})`}>
                <ellipse ref={tongue} cx={MID_X} cy={TEETH_BOTTOM_Y} rx="14" ry="0" fill={TONGUE} />
                <rect ref={teeth} x={LEFT + 6} y={CORNER_Y} width={RIGHT - LEFT - 12} height="3" rx="2" fill={TEETH} />
              </g>
              <path ref={upperEdge} d="" fill="none" stroke={CORNER} strokeWidth="1.6" strokeLinecap="round" />
            </g>
          </svg>
      )}
    </Portrait>
  );
}
