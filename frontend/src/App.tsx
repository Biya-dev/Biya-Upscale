import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { isAcceptedFile } from "./format";
import type {
  AppStatus,
  ImageRecord,
  Job,
  JobError,
  JobResult,
  OutputFormat,
} from "./types";
import Header from "./components/Header";
import DropZone from "./components/DropZone";
import ImageQueue from "./components/ImageQueue";
import ResultPanel from "./components/ResultPanel";
import ModelDialog from "./components/ModelDialog";
import {
  IconAlert,
  IconCheck,
  IconCpu,
  IconDownload,
  IconGpu,
  IconLock,
  IconPlay,
  IconStop,
} from "./components/Icons";

export type { OutputFormat };

export type ItemStatus =
  | "uploading"
  | "ready"
  | "queued"
  | "processing"
  | "done"
  | "failed"
  | "cancelled";

export interface UiImage {
  key: string;
  fileName: string;
  previewUrl: string;
  status: ItemStatus;
  file?: File; // kept until the upload finishes
  record?: ImageRecord;
  jobId?: string;
  progress: number;
  result?: JobResult;
  error?: JobError | null;
}

const JOB_TO_ITEM: Record<Job["status"], ItemStatus> = {
  queued: "queued",
  running: "processing",
  done: "done",
  failed: "failed",
  cancelled: "cancelled",
};

function applyJob(item: UiImage, job: Job): UiImage {
  return {
    ...item,
    status: JOB_TO_ITEM[job.status],
    progress: job.progress,
    error: job.error,
    result: job.result ?? undefined,
  };
}

function toJobError(error: unknown): JobError {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message, hint: error.hint };
  }
  return {
    code: "unknown",
    message: "Something unexpected happened.",
    hint: "Please try again.",
  };
}

type Toast = { kind: "error" | "info"; text: string };

export default function App() {
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [images, setImages] = useState<UiImage[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [scale, setScale] = useState<2 | 4>(2);
  const [modelChoice, setModelChoice] = useState("auto");
  const [format, setFormat] = useState<OutputFormat>("png");
  const [quality, setQuality] = useState(95);
  const [showModels, setShowModels] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">(() =>
    document.documentElement.dataset.theme === "light" ? "light" : "dark",
  );
  const [toast, setToast] = useState<Toast | null>(null);
  const [busyKeys, setBusyKeys] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const promptedForModel = useRef(false);
  const toastTimer = useRef<number | undefined>(undefined);

  const notify = useCallback((kind: Toast["kind"], text: string) => {
    window.clearTimeout(toastTimer.current);
    setToast({ kind, text });
    toastTimer.current = window.setTimeout(() => setToast(null), 6000);
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await api.status();
      setStatus(next);
      return next;
    } catch {
      return null;
    }
  }, []);

  // Initial load: device/models + first-launch model prompt.
  useEffect(() => {
    void (async () => {
      const next = await refreshStatus();
      if (!next) return;
      const initialScale = next.settings.scale === 4 ? 4 : 2;
      setScale(initialScale as 2 | 4);
      setModelChoice(next.settings.model_preference || "auto");
      const installed = new Set(
        next.models.filter((m) => m.installed).map((m) => m.id),
      );
      const wanted = next.models.find(
        (m) => m.default && m.scale === initialScale && !installed.has(m.id),
      );
      if (wanted && !promptedForModel.current) {
        promptedForModel.current = true;
        setShowModels(true);
      }
    })();
  }, [refreshStatus]);

  // Poll active jobs (one request covers the whole batch).
  const hasActive = images.some(
    (i) => i.status === "queued" || i.status === "processing",
  );
  useEffect(() => {
    if (!hasActive) return;
    let stopped = false;
    const tick = async () => {
      try {
        const { jobs } = await api.listJobs();
        if (stopped) return;
        const byId = new Map(jobs.map((j) => [j.id, j]));
        setImages((prev) =>
          prev.map((item) => {
            if (!item.jobId) return item;
            const job = byId.get(item.jobId);
            return job ? applyJob(item, job) : item;
          }),
        );
      } catch {
        /* transient polling error — the next tick retries */
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 400);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [hasActive]);

  // Keep model download progress fresh while the dialog is open.
  useEffect(() => {
    if (!showModels) return;
    const timer = window.setInterval(() => void refreshStatus(), 700);
    return () => window.clearInterval(timer);
  }, [showModels, refreshStatus]);

  // Auto-select the first available result for the comparison view.
  useEffect(() => {
    if (selectedKey && images.some((i) => i.key === selectedKey && i.result)) {
      return;
    }
    const firstDone = images.find((i) => i.result);
    if (firstDone) setSelectedKey(firstDone.key);
  }, [images, selectedKey]);

  // --- helpers -------------------------------------------------------------
  const updateItem = useCallback((key: string, patch: Partial<UiImage>) => {
    setImages((prev) =>
      prev.map((item) => (item.key === key ? { ...item, ...patch } : item)),
    );
  }, []);

  const models = status?.models ?? [];
  const selected = images.find((i) => i.key === selectedKey) ?? null;

  const processable = images.filter(
    (i) =>
      i.record &&
      (i.status === "ready" ||
        i.status === "failed" ||
        i.status === "cancelled"),
  );
  const finishedCount = images.filter(
    (i) =>
      i.status === "done" || i.status === "failed" || i.status === "cancelled",
  ).length;
  const doneCount = images.filter((i) => i.status === "done").length;
  const failedCount = images.filter((i) => i.status === "failed").length;
  const activeCount = images.filter(
    (i) => i.status === "queued" || i.status === "processing",
  ).length;
  const uploadingCount = images.filter((i) => i.status === "uploading").length;
  const busy = activeCount > 0 || submitting || uploadingCount > 0;

  // --- actions --------------------------------------------------------------
  const addFiles = useCallback(
    async (files: File[]) => {
      const accepted: { key: string; file: File }[] = [];
      const rejected: string[] = [];
      for (const file of files) {
        if (!isAcceptedFile(file)) {
          rejected.push(file.name);
          continue;
        }
        const key =
          typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        accepted.push({ key, file });
      }
      if (rejected.length > 0) {
        notify(
          "error",
          `Unsupported file${rejected.length > 1 ? "s" : ""}: ${rejected
            .slice(0, 3)
            .join(", ")}${rejected.length > 3 ? "…" : ""} — PNG, JPG and WEBP only.`,
        );
      }
      if (accepted.length === 0) return;

      const fresh: UiImage[] = accepted.map(({ key, file }) => ({
        key,
        fileName: file.name,
        previewUrl: URL.createObjectURL(file),
        status: "uploading",
        file,
        progress: 0,
        error: null,
      }));
      setImages((prev) => [...prev, ...fresh]);

      for (const item of fresh) {
        try {
          const record = await api.uploadImage(item.file!);
          updateItem(item.key, { record, status: "ready", file: undefined });
        } catch (error) {
          updateItem(item.key, { status: "failed", error: toJobError(error) });
        }
      }
    },
    [notify, updateItem],
  );

  const submitTargets = useCallback(
    async (targets: UiImage[]) => {
      if (targets.length === 0 || !status) return;
      setSubmitting(true);
      // Optimistic queueing keeps the UI honest even before the API replies.
      setImages((prev) =>
        prev.map((item) =>
          targets.some((t) => t.key === item.key)
            ? {
                ...item,
                status: "queued" as ItemStatus,
                progress: 0,
                error: null,
                result: undefined,
                jobId: undefined,
              }
            : item,
        ),
      );
      for (const target of targets) {
        try {
          const { job_id } = await api.startUpscale(
            target.record!.id,
            scale,
            modelChoice === "auto" ? undefined : modelChoice,
          );
          updateItem(target.key, { jobId: job_id, status: "queued" });
        } catch (error) {
          const jobError = toJobError(error);
          updateItem(target.key, { status: "failed", error: jobError });
          if (jobError.code === "model_missing") setShowModels(true);
        }
      }
      setSubmitting(false);
    },
    [modelChoice, scale, status, updateItem],
  );

  const startProcessing = useCallback(
    () => void submitTargets(processable),
    [processable, submitTargets],
  );

  const retryItem = useCallback(
    (key: string) => {
      const target = images.find((i) => i.key === key);
      if (target?.record) void submitTargets([target]);
    },
    [images, submitTargets],
  );


  const cancelAll = useCallback(async () => {
    const active = images.filter(
      (i) => (i.status === "queued" || i.status === "processing") && i.jobId,
    );
    // Queued items without a job id yet are cancelled locally.
    setImages((prev) =>
      prev.map((i) =>
        i.status === "queued" && !i.jobId
          ? {
              ...i,
              status: "cancelled",
              error: { code: "cancelled", message: "Cancelled." },
            }
          : i,
      ),
    );
    await Promise.all(
      active.map(async (item) => {
        try {
          const job = await api.cancelJob(item.jobId!);
          updateItem(item.key, applyJob(item, job));
        } catch {
          /* job may already be finished */
        }
      }),
    );
  }, [images, updateItem]);

  const removeImage = useCallback(
    async (key: string) => {
      const target = images.find((i) => i.key === key);
      if (!target) return;
      setBusyKeys((prev) => new Set(prev).add(key));
      if (
        target.jobId &&
        !["done", "failed", "cancelled"].includes(target.status)
      ) {
        try {
          await api.cancelJob(target.jobId);
        } catch {
          /* ignore */
        }
      }
      if (target.record) {
        try {
          await api.deleteImage(target.record.id);
        } catch {
          /* ignore */
        }
      }
      URL.revokeObjectURL(target.previewUrl);
      setImages((prev) => prev.filter((i) => i.key !== key));
      if (selectedKey === key) setSelectedKey(null);
      setBusyKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    },
    [images, selectedKey],
  );

  const clearFinished = useCallback(() => {
    const keep: UiImage[] = [];
    for (const item of images) {
      if (
        item.status === "done" ||
        item.status === "failed" ||
        item.status === "cancelled"
      ) {
        URL.revokeObjectURL(item.previewUrl);
      } else {
        keep.push(item);
      }
    }
    setImages(keep);
    setSelectedKey(null);
  }, [images]);

  // --- downloads -------------------------------------------------------------
  const outputExt = useMemo<OutputFormat>(() => {
    if (format === "png" || format === "jpg" || format === "webp") return format;
    return "png";
  }, [format]);

  const downloadOne = useCallback(
    (item: UiImage) => {
      if (!item.jobId || !item.result) return;
      const anchor = document.createElement("a");
      anchor.href = api.downloadUrl(item.jobId, outputExt, quality);
      anchor.download = `${item.result.download_stem}.${outputExt}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    },
    [outputExt, quality],
  );

  const downloadAll = useCallback(() => {
    const done = images.filter((i) => i.result && i.jobId);
    done.forEach((item, index) => {
      window.setTimeout(() => downloadOne(item), index * 400);
    });
  }, [downloadOne, images]);

  // --- settings / theme --------------------------------------------------------
  const toggleTheme = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("biya-theme", next);
    setTheme(next);
    void api.setSettings({ theme: next }).catch(() => undefined);
  }, [theme]);

  const changeScale = useCallback(
    (next: 2 | 4) => {
      setScale(next);
      // Reset a model that cannot serve the new scale.
      setModelChoice((current) => {
        if (current === "auto") return current;
        const chosen = models.find((m) => m.id === current);
        return chosen && chosen.scale === next ? current : "auto";
      });
      void api.setSettings({ scale: next }).catch(() => undefined);
    },
    [models],
  );

  const changeModel = useCallback((next: string) => {
    setModelChoice(next);
    void api.setSettings({ model_preference: next }).catch(() => undefined);
  }, []);

  // Models offered for the current scale factor.
  const modelsForScale = models.filter((m) => m.scale === scale);


  // --- derived display values ------------------------------------------------
  const totalConsidered = images.filter((i) => i.status !== "uploading").length;
  const progressPercent =
    totalConsidered > 0 ? Math.round((finishedCount / totalConsidered) * 100) : 0;
  const focusOriginal =
    (selected && selected.record) ||
    images.find((i) => i.record)?.record ||
    null;
  const deviceLabel = status?.device.label ?? "detecting…";
  const isGpu = status?.device.kind === "gpu";

  return (
    <div className="flex min-h-full flex-col">
      <Header
        status={status}
        models={models}
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenModels={() => setShowModels(true)}
      />

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 pt-8 pb-44">
        {/* ---------- First screen (spec): title, tagline, drop zone ---------- */}
        {images.length === 0 && (
          <section className="mx-auto max-w-2xl pt-6 text-center">
            <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
              Biya Upscale
            </h1>
            <p className="mt-3 text-lg text-muted">Upscale your images locally.</p>

            <div className="mt-8">
              <DropZone onFiles={addFiles} disabled={busy} />
            </div>

            <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
              <span className="chip chip-accent">
                <IconLock width={13} height={13} /> 100% offline
              </span>
              <span className="chip">no account · no API key</span>
              <span className="chip">2× &amp; 4× AI models</span>
              <span className="chip">PNG · JPG · WEBP</span>
            </div>

            {status && (
              <div className="card mx-auto mt-8 max-w-md p-4 text-left">
                <div className="label-cap">Processing device</div>
                <div className="mt-1.5 flex items-center gap-2 text-sm font-semibold">
                  {isGpu ? <IconGpu /> : <IconCpu />}
                  {deviceLabel}
                </div>
                <div className="mt-1 text-[11.5px] text-muted">
                  Falls back to CPU automatically when no GPU is available.
                </div>
              </div>
            )}
          </section>
        )}


        {/* ---------------------- Working screen ---------------------- */}
        {images.length > 0 && (
          <div className="space-y-5">
            {/* Controls: original · scale · model · device · run */}
            <div className="card flex flex-wrap items-end gap-x-6 gap-y-4 p-4">
              <div className="min-w-[9rem]">
                <div className="label-cap">Original</div>
                <div className="mt-1 text-sm font-semibold tabular-nums">
                  {focusOriginal
                    ? `${focusOriginal.width.toLocaleString()} × ${focusOriginal.height.toLocaleString()}`
                    : "—"}
                </div>
              </div>

              <div>
                <div className="label-cap mb-1.5">Scale</div>
                <div className="seg">
                  <button
                    data-active={scale === 2}
                    onClick={() => changeScale(2)}
                    disabled={busy}
                  >
                    2×
                  </button>
                  <button
                    data-active={scale === 4}
                    onClick={() => changeScale(4)}
                    disabled={busy}
                  >
                    4×
                  </button>
                </div>
              </div>

              <div>
                <div className="label-cap mb-1.5">Model</div>
                <select
                  value={modelChoice}
                  onChange={(e) => changeModel(e.target.value)}
                  disabled={busy}
                >
                  <option value="auto">Auto (recommended)</option>
                  {modelsForScale.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                      {m.installed ? "" : " — not installed"}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <div className="label-cap mb-1.5">Processing</div>
                <span
                  className="chip"
                  title={
                    status
                      ? `Runtime providers: ${status.compiled_providers.join(", ")}`
                      : undefined
                  }
                >
                  {isGpu ? <IconGpu /> : <IconCpu />}
                  {deviceLabel}
                </span>
              </div>

              <div className="ml-auto flex items-center gap-2">
                <label className="btn" title="Add more images">
                  Add images
                  <input
                    type="file"
                    multiple
                    accept=".png,.jpg,.jpeg,.webp"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files) void addFiles(Array.from(e.target.files));
                      e.target.value = "";
                    }}
                  />
                </label>

                {busy ? (
                  <button className="btn" onClick={() => void cancelAll()}>
                    <IconStop />
                    Cancel
                  </button>
                ) : (
                  <button
                    className="btn btn-primary"
                    disabled={processable.length === 0}
                    onClick={startProcessing}
                  >
                    <IconPlay />
                    {processable.length > 1
                      ? `Upscale ${processable.length} images`
                      : "Upscale"}
                  </button>
                )}
              </div>
            </div>


            {/* Queue + comparison result */}
            <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,460px)]">
              <ImageQueue
                images={images}
                selectedKey={selectedKey}
                busyKeys={busyKeys}
                onSelect={setSelectedKey}
                onRemove={(key) => void removeImage(key)}
                onRetry={retryItem}
              />
              {selected && selected.result && (
                <div className="h-fit lg:sticky lg:top-28">
                  <ResultPanel
                    item={selected}
                    format={outputExt}
                    quality={quality}
                    onFormatChange={(f) => {
                      setFormat(f);
                      void api
                        .setSettings({ output_format: f })
                        .catch(() => undefined);
                    }}
                    onQualityChange={(q) => {
                      setQuality(q);
                      void api
                        .setSettings({ quality: q })
                        .catch(() => undefined);
                    }}
                    onDownload={() => downloadOne(selected)}
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* ------------------- Batch progress bar ------------------- */}
      {images.length > 0 && (busy || finishedCount > 0) && (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-bg/90 backdrop-blur-md">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
            <div className="text-sm">
              <span className="font-semibold tabular-nums">
                {finishedCount} / {totalConsidered}
              </span>{" "}
              images processed
              {activeCount > 0 && (
                <span className="text-muted">
                  {" "}
                  · {activeCount} in progress
                </span>
              )}
              {failedCount > 0 && (
                <span className="text-danger"> · {failedCount} failed</span>
              )}
              {doneCount > 0 && (
                <span className="text-accent"> · {doneCount} done</span>
              )}
            </div>

            <div className="relative h-1.5 min-w-32 flex-1 overflow-hidden rounded-full bg-panel2">
              <div
                className="h-full rounded-full bg-accent transition-[width] duration-500"
                style={{ width: `${progressPercent}%` }}
              />
            </div>

            {doneCount > 0 && (
              <button className="btn" onClick={downloadAll}>
                <IconDownload />
                Download all ({doneCount})
              </button>
            )}
            {!busy && finishedCount > 0 && (
              <button className="btn btn-ghost" onClick={clearFinished}>
                Clear list
              </button>
            )}
          </div>
        </div>
      )}

      {/* ------------------- Model manager dialog ------------------- */}
      {showModels && (
        <ModelDialog
          models={models}
          onClose={() => {
            setShowModels(false);
            void refreshStatus();
          }}
          onChanged={() => void refreshStatus()}
        />
      )}

      {/* ------------------- Toast ------------------- */}
      {toast && (
        <div
          className={`fade-up fixed right-5 bottom-24 z-50 flex max-w-sm items-start gap-2 rounded-xl border px-4 py-3 text-sm shadow-lg ${
            toast.kind === "error"
              ? "border-danger/40 bg-panel text-danger"
              : "border-accent/40 bg-panel text-accent"
          }`}
          style={{ boxShadow: "var(--shadow)" }}
          role="status"
        >
          {toast.kind === "error" ? (
            <IconAlert className="mt-0.5 shrink-0" />
          ) : (
            <IconCheck className="mt-0.5 shrink-0" />
          )}
          <span>{toast.text}</span>
        </div>
      )}
    </div>
  );
}

