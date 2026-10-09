import { dims, formatBytes } from "../format";
import type { ItemStatus, UiImage } from "../App";
import {
  IconAlert,
  IconCheck,
  IconRetry,
  IconTrash,
  IconX,
} from "./Icons";

interface Props {
  images: UiImage[];
  selectedKey: string | null;
  busyKeys: Set<string>;
  onSelect: (key: string) => void;
  onRemove: (key: string) => void;
  onRetry: (key: string) => void;
}

const STATUS_META: Record<ItemStatus, { text: string; cls: string }> = {
  uploading: { text: "Adding…", cls: "bg-panel2 text-muted" },
  ready: { text: "Ready", cls: "bg-panel2 text-muted" },
  queued: { text: "Queued", cls: "bg-panel2 text-muted" },
  processing: { text: "Processing", cls: "chip-accent" },
  done: { text: "Done", cls: "chip-accent" },
  failed: { text: "Failed", cls: "bg-danger-soft text-danger" },
  cancelled: { text: "Cancelled", cls: "bg-panel2 text-muted" },
};

export default function ImageQueue({
  images,
  selectedKey,
  busyKeys,
  onSelect,
  onRemove,
  onRetry,
}: Props) {
  if (images.length === 0) return null;

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="label-cap">Images · {images.length}</span>
        <span className="text-[12px] text-muted">
          processed one at a time — low memory use
        </span>
      </div>

      <ul className="divide-y divide-line">
        {images.map((item) => {
          const meta = STATUS_META[item.status];
          const selected = item.key === selectedKey;
          const record = item.record;
          return (
            <li
              key={item.key}
              className={`flex cursor-pointer items-center gap-3.5 px-4 py-3 transition-colors ${
                selected ? "bg-accent-soft/60" : "hover:bg-panel2/70"
              }`}
              onClick={() => item.result && onSelect(item.key)}
            >
              {/* thumbnail */}
              <div className="relative size-12 shrink-0 overflow-hidden rounded-lg border border-line bg-panel2">
                <img
                  src={item.previewUrl}
                  alt=""
                  className="size-full object-cover"
                  loading="lazy"
                />
              </div>

              {/* name + meta */}
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13.5px] font-medium">
                  {item.record?.filename ?? item.fileName}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[11.5px] text-muted">
                  {record && <span>{dims(record.width, record.height)}</span>}
                  {record && <span>{formatBytes(record.size_bytes)}</span>}
                  {item.result && (
                    <>
                      <span className="text-accent">
                        → {dims(item.result.width, item.result.height)}
                      </span>
                      <span>{item.result.duration_s.toFixed(1)}s</span>
                    </>
                  )}
                </div>

                {/* per-item progress */}
                {(item.status === "processing" || item.status === "queued") && (
                  <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-panel2">
                    <div
                      className="h-full rounded-full bg-accent transition-[width] duration-300"
                      style={{
                        width:
                          item.status === "queued"
                            ? "4%"
                            : `${Math.max(4, Math.round(item.progress * 100))}%`,
                      }}
                    />
                  </div>
                )}
                {item.error && (
                  <div className="mt-1.5 flex items-start gap-1.5 text-[12px] leading-snug text-danger">
                    <IconAlert
                      width={13}
                      height={13}
                      className="mt-0.5 shrink-0"
                    />
                    <span>
                      {item.error.message}
                      {item.error.hint && (
                        <span className="text-muted"> {item.error.hint}</span>
                      )}
                    </span>
                  </div>
                )}
              </div>

              {/* status + actions */}
              <div className="flex shrink-0 items-center gap-1.5">
                <span
                  className={`chip ${meta.cls} min-w-[86px] justify-center ${
                    item.status === "processing" ? "animate-pulse" : ""
                  }`}
                >
                  {item.status === "done" && <IconCheck width={13} height={13} />}
                  {item.status === "failed" && <IconX width={13} height={13} />}
                  {meta.text}
                </span>

                {(item.status === "failed" || item.status === "cancelled") &&
                  item.record && (
                    <button
                      className="btn btn-ghost size-8! p-0!"
                      title="Try again"
                      disabled={busyKeys.has(item.key)}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRetry(item.key);
                      }}
                    >
                      <IconRetry />
                    </button>
                  )}

                <button
                  className="btn btn-ghost btn-danger size-8! p-0!"
                  title="Remove from list"
                  disabled={busyKeys.has(item.key)}
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemove(item.key);
                  }}
                >
                  <IconTrash />
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

