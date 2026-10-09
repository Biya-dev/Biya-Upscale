import { dims, formatSeconds } from "../format";
import { api } from "../api";
import type { OutputFormat, UiImage } from "../App";
import CompareSlider from "./CompareSlider";
import { IconDownload, IconGpu, IconCpu } from "./Icons";

interface Props {
  item: UiImage;
  format: OutputFormat;
  quality: number;
  onFormatChange: (format: OutputFormat) => void;
  onQualityChange: (quality: number) => void;
  onDownload: () => void;
}

export default function ResultPanel({
  item,
  format,
  quality,
  onFormatChange,
  onQualityChange,
  onDownload,
}: Props) {
  const record = item.record;
  const result = item.result;
  if (!record || !result) return null;

  const lossy = format !== "png";
  const modelShort =
    result.model.length > 14
      ? result.model.replace("Real-ESRGAN ", "R-ESR ")
      : result.model;

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="label-cap">Before | After</span>
        <span className="max-w-[55%] truncate text-[12px] text-muted">
          {record.filename}
        </span>
      </div>

      <div className="p-4">
        <CompareSlider
          beforeUrl={item.previewUrl}
          afterUrl={api.previewUrl(item.jobId!)}
        />

        {/* Resolution math + processing time — the headline numbers */}
        <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
          <Stat
            label="Original"
            value={dims(record.width, record.height)}
            sub="pixels"
          />
          <Stat
            label="Upscaled"
            value={dims(result.width, result.height)}
            sub={modelShort}
            accent
          />
          <Stat
            label="Processing time"
            value={formatSeconds(result.duration_s)}
            sub={`inference ${formatSeconds(result.inference_s)}`}
          />
          <div className="rounded-lg border border-line bg-panel2/60 p-3">
            <div className="label-cap !text-[10px]">Device</div>
            <div className="mt-1.5 flex items-center gap-1.5 text-[12.5px] font-semibold">
              {result.device_id === "cpu" ? <IconCpu /> : <IconGpu />}
              <span className="break-words" title={result.device}>
                {result.device}
              </span>
            </div>
            <div className="mt-0.5 text-[11px] text-muted">
              {record.width.toLocaleString()} × {record.height.toLocaleString()} →{" "}
              {result.width.toLocaleString()} × {result.height.toLocaleString()}
            </div>
          </div>
        </div>

        {/* Download controls */}
        <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-4">
          <label className="flex flex-col gap-1">
            <span className="label-cap !text-[10px]">Output format</span>
            <select
              value={format}
              onChange={(e) => onFormatChange(e.target.value as OutputFormat)}
            >
              <option value="png">PNG (lossless)</option>
              <option value="jpg">JPG</option>
              <option value="webp">WEBP</option>
            </select>
          </label>

          {lossy && (
            <label className="flex flex-col gap-1">
              <span className="label-cap !text-[10px]">
                Quality · {quality}
              </span>
              <input
                type="range"
                min={60}
                max={100}
                value={quality}
                onChange={(e) => onQualityChange(Number(e.target.value))}
                className="w-32"
              />
            </label>
          )}

          <button className="btn btn-primary ml-auto" onClick={onDownload}>
            <IconDownload />
            Download
          </button>
        </div>

        <p className="mt-2.5 text-[11.5px] text-muted">
          Files are saved as{" "}
          <span className="font-medium text-ink">{result.download_stem}</span>
          .<span className="text-accent"> Originals are never overwritten.</span>
        </p>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-lg border border-line bg-panel2/60 p-3">
      <div className="label-cap !text-[10px]">{label}</div>
      <div
        className={`mt-1 text-[14.5px] font-semibold tracking-tight ${
          accent ? "text-accent" : ""
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-muted">{sub}</div>}
    </div>
  );
}
