import { useCallback, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

interface Props {
  beforeUrl: string;
  afterUrl: string;
  beforeLabel?: string;
  afterLabel?: string;
}

/**
 * Draggable before/after comparison.
 *
 * Both images are rendered full-size in the frame and the "before" layer is
 * clipped with `clip-path`, so the two images stay pixel-registered for any
 * aspect ratio and size.
 */
export default function CompareSlider({
  beforeUrl,
  afterUrl,
  beforeLabel = "Before",
  afterLabel = "After",
}: Props) {
  const frameRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState(50);
  const draggingRef = useRef(false);

  const updateFromEvent = useCallback((clientX: number) => {
    const frame = frameRef.current;
    if (!frame) return;
    const rect = frame.getBoundingClientRect();
    const fraction = ((clientX - rect.left) / rect.width) * 100;
    setPosition(Math.min(98, Math.max(2, fraction)));
  }, []);

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    updateFromEvent(event.clientX);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (draggingRef.current) updateFromEvent(event.clientX);
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    draggingRef.current = false;
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      /* pointer already released */
    }
  };

  return (
    <div
      ref={frameRef}
      className="relative aspect-[4/3] w-full cursor-ew-resize touch-none overflow-hidden rounded-xl border border-line bg-panel2 select-none"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      role="slider"
      aria-label="Before and after comparison"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(position)}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") setPosition((p) => Math.max(2, p - 4));
        if (e.key === "ArrowRight") setPosition((p) => Math.min(98, p + 4));
      }}
    >
      {/* After (base layer) */}
      <img
        src={afterUrl}
        alt="Upscaled result"
        className="absolute inset-0 size-full object-contain"
        draggable={false}
      />

      {/* Before (same geometry, clipped from the right) */}
      <img
        src={beforeUrl}
        alt="Original image"
        className="absolute inset-0 size-full object-contain"
        style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }}
        draggable={false}
      />

      {/* Divider handle */}
      <div
        className="pointer-events-none absolute inset-y-0 z-10 w-px bg-white/85 shadow-[0_0_0_1px_rgba(0,0,0,0.35)]"
        style={{ left: `${position}%` }}
      >
        <span className="absolute top-1/2 left-1/2 grid size-9 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-black/20 bg-white/95 text-gray-900 shadow-lg">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="m9 6-5 6 5 6M15 6l5 6-5 6" />
          </svg>
        </span>
      </div>

      {/* Labels */}
      <span className="pointer-events-none absolute top-3 left-3 z-10 rounded-md bg-black/60 px-2 py-1 text-[11px] font-semibold tracking-wide text-white uppercase backdrop-blur-sm">
        {beforeLabel}
      </span>
      <span className="pointer-events-none absolute top-3 right-3 z-10 rounded-md bg-black/60 px-2 py-1 text-[11px] font-semibold tracking-wide text-white uppercase backdrop-blur-sm">
        {afterLabel}
      </span>
    </div>
  );
}
