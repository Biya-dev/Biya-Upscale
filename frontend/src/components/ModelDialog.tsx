import { useState } from "react";
import { formatBytes, percent } from "../format";
import { api, ApiError } from "../api";
import type { ModelInfo } from "../types";
import { IconAlert, IconCheck, IconDownload, IconX } from "./Icons";

interface Props {
  models: ModelInfo[];
  onClose: () => void;
  onChanged: () => void;
}

/**
 * First-launch model manager. Nothing is downloaded until the user clicks
 * Download — and the card states exactly what will be fetched, how big it is,
 * what license it carries and what it does.
 */
export default function ModelDialog({ models, onClose, onChanged }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const download = async (model: ModelInfo) => {
    setBusy(model.id);
    setLocalError(null);
    try {
      await api.downloadModel(model.id);
      onChanged();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Download failed.";
      setLocalError(message);
    } finally {
      setBusy(null);
    }
  };

  const cancel = async (model: ModelInfo) => {
    try {
      await api.cancelModelDownload(model.id);
      onChanged();
    } catch {
      /* already finished */
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/55 p-4 backdrop-blur-[2px]"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="fade-up card w-full max-w-xl"
        style={{ boxShadow: "var(--shadow)" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Manage AI models"
      >
        <div className="flex items-start justify-between border-b border-line px-5 py-4">
          <div>
            <div className="label-cap">AI models</div>
            <h2 className="mt-0.5 text-lg font-semibold tracking-tight">
              Install the upscaling model
            </h2>
          </div>
          <button
            className="btn btn-ghost size-8! p-0!"
            onClick={onClose}
            aria-label="Close"
          >
            <IconX />
          </button>
        </div>

        <div className="border-b border-line px-5 py-3 text-[12.5px] leading-relaxed text-muted">
          Models are downloaded <strong className="text-ink">once</strong>,
          verified with a checksum, and stored on this computer. After that
          everything works fully offline. Images are never uploaded anywhere.
        </div>

        <div className="max-h-[55vh] space-y-3 overflow-y-auto px-5 py-4">
          {models.map((model) => (
            <div
              key={model.id}
              className="rounded-xl border border-line bg-panel2/60 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{model.name}</span>
                    <span className="chip !py-0.5 !text-[11px]">
                      {model.scale}× · {formatBytes(model.size_bytes)}
                    </span>
                    <span className="chip !py-0.5 !text-[11px]">
                      {model.license}
                    </span>
                    {model.default && (
                      <span className="chip chip-accent !py-0.5 !text-[11px]">
                        recommended
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">
                    {model.summary}
                  </p>
                  <div className="mt-1 text-[11px] text-muted">
                    {model.architecture} ·{" "}
                    <a
                      className="underline underline-offset-2 hover:text-accent"
                      href={model.homepage}
                      target="_blank"
                      rel="noreferrer"
                    >
                      source &amp; license
                    </a>
                  </div>
                </div>

                <div className="shrink-0 text-right">
                  {model.state === "ready" && (
                    <span className="chip chip-accent">
                      <IconCheck width={13} height={13} /> Installed
                    </span>
                  )}
                  {(model.state === "not_downloaded" ||
                    model.state === "error") && (
                    <button
                      className="btn btn-primary !py-1.5 !text-[13px]"
                      disabled={busy === model.id}
                      onClick={() => download(model)}
                    >
                      <IconDownload width={14} height={14} />
                      {model.state === "error" ? "Retry" : "Download"}
                    </button>
                  )}
                  {model.state === "downloading" && (
                    <button
                      className="btn !py-1.5 !text-[13px]"
                      onClick={() => cancel(model)}
                    >
                      <span className="tabular-nums">
                        {percent(model.progress)}
                      </span>
                      Cancel
                    </button>
                  )}
                </div>
              </div>

              {model.state === "downloading" && (
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-panel">
                  <div
                    className="h-full rounded-full bg-accent transition-[width] duration-200"
                    style={{ width: `${Math.max(2, model.progress * 100)}%` }}
                  />
                </div>
              )}

              {model.state === "error" && model.error && (
                <div className="mt-2 flex items-start gap-1.5 text-[12px] text-danger">
                  <IconAlert width={13} height={13} className="mt-0.5 shrink-0" />
                  <span>{model.error}</span>
                </div>
              )}
            </div>
          ))}
        </div>

        {localError && (
          <div className="mx-5 mb-2 flex items-start gap-1.5 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
            <IconAlert width={14} height={14} className="mt-0.5 shrink-0" />
            {localError}
          </div>
        )}

        <div className="flex items-center justify-between border-t border-line px-5 py-3.5">
          <span className="text-[12px] text-muted">
            Models stay in your app data folder.
          </span>
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

