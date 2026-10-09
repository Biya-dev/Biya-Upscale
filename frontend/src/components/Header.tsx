import type { AppStatus, ModelInfo } from "../types";
import {
  IconCpu,
  IconGpu,
  IconLayers,
  IconLock,
  IconMoon,
  IconSun,
} from "./Icons";

interface Props {
  status: AppStatus | null;
  models: ModelInfo[];
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onOpenModels: () => void;
}

function deviceIcon(status: AppStatus | null) {
  const kind = status?.device?.kind ?? "cpu";
  return kind === "gpu" ? <IconGpu /> : <IconCpu />;
}

export default function Header({
  status,
  models,
  theme,
  onToggleTheme,
  onOpenModels,
}: Props) {
  const installed = models.filter((m) => m.installed).length;
  const downloading = models.some((m) => m.state === "downloading");

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-5">
        {/* Brand */}
        <div className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-xl border border-line bg-panel">
            <svg width="20" height="20" viewBox="0 0 32 32" aria-hidden>
              <path
                d="M9 22V10h7.2a3.4 3.4 0 0 1 .6 6.74A3.6 3.6 0 0 1 16.9 22H9Zm3.4-2.6h3.3a1.2 1.2 0 0 0 0-2.4h-3.3v2.4Zm0-4.9h3.5a1.3 1.3 0 0 0 0-2.6h-3.5v2.6Z"
                fill="var(--accent)"
              />
              <path
                d="M20 19l5-5m0 0v4m0-4h-4"
                stroke="var(--accent)"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            </svg>
          </span>
          <div className="leading-tight">
            <div className="text-[15px] font-bold tracking-tight">Biya Upscale</div>
            <div className="text-[11px] text-muted">
              {status ? `v${status.version}` : "local image upscaling"}
            </div>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2.5">
          {/* Processing device — a core piece of information, always visible */}
          <span
            className="chip max-w-[46vw] truncate sm:max-w-none"
            title={
              status
                ? `Providers: ${status.compiled_providers.join(", ") || "n/a"}`
                : undefined
            }
          >
            {deviceIcon(status)}
            <span className="truncate">
              {status ? status.device.label : "detecting…"}
            </span>
          </span>

          {/* Model manager */}
          <button
            className={`chip ${installed > 0 && !downloading ? "chip-accent" : ""}`}
            onClick={onOpenModels}
            title="Manage AI models"
          >
            <IconLayers />
            <span className="hidden sm:inline">
              {downloading
                ? "Downloading model…"
                : installed > 0
                  ? `${installed} model${installed > 1 ? "s" : ""} ready`
                  : "Models"}
            </span>
            <span className="sm:hidden">
              {downloading ? "…" : installed > 0 ? `${installed}` : "Models"}
            </span>
          </button>

          <button
            className="btn btn-ghost size-9! p-0!"
            onClick={onToggleTheme}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            aria-label="Toggle color theme"
          >
            {theme === "dark" ? <IconSun /> : <IconMoon />}
          </button>
        </div>
      </div>

      {/* Privacy strip — the product promise, stated up front */}
      <div className="border-t border-line/70 bg-panel/40">
        <div className="mx-auto flex max-w-6xl items-center gap-2 px-5 py-1.5 text-[12px] text-muted">
          <IconLock width={13} height={13} />
          <span>
            All processing happens on this device. Images are never uploaded —
            no account, no API key, no telemetry.
          </span>
        </div>
      </div>
    </header>
  );
}
