// Shared API types — mirror of the Python backend's response shapes.

export interface DeviceInfo {
  id: string;
  label: string;
  kind: string;
  provider: string;
  gpu_name?: string | null;
  vram_mb?: number | null;
}

export type ModelState = "not_downloaded" | "downloading" | "ready" | "error";

export interface ModelInfo {
  id: string;
  name: string;
  scale: number;
  size_bytes: number;
  sha256: string;
  license: string;
  homepage: string;
  architecture: string;
  summary: string;
  default: boolean;
  filename: string;
  state: ModelState;
  progress: number;
  error: string | null;
  installed: boolean;
}

export interface Settings {
  theme: "dark" | "light" | null;
  scale: number;
  output_format: "auto" | "png" | "jpg" | "webp";
  quality: number;
  model_preference: string;
  force_cpu: boolean;
}

export interface AppStatus {
  app_name: string;
  version: string;
  device: DeviceInfo;
  detected_device: DeviceInfo;
  devices: DeviceInfo[];
  active: DeviceInfo | null;
  compiled_providers: string[];
  models: ModelInfo[];
  pending_jobs: number;
  active_jobs: number;
  settings: Settings;
  privacy: string;
}

export interface ImageRecord {
  id: string;
  filename: string;
  width: number;
  height: number;
  size_bytes: number;
  format: string;
  has_alpha: boolean;
  added_at: number;
}

export interface JobError {
  code: string;
  message: string;
  hint?: string | null;
}

export interface JobResult {
  result_id: string;
  width: number;
  height: number;
  duration_s: number;
  inference_s: number;
  device: string;
  device_id: string;
  model: string;
  tile: number;
  download_stem: string;
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface Job {
  id: string;
  image_id: string;
  filename: string;
  src_width: number;
  src_height: number;
  scale: number;
  model_id: string;
  status: JobStatus;
  progress: number;
  error: JobError | null;
  result: JobResult | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
}

export type OutputFormat = "png" | "jpg" | "webp";

/** Client-side lifecycle for one queued image. */
export type ItemStatus =
  | "uploading"
  | "ready"
  | "queued"
  | "processing"
  | "done"
  | "failed"
  | "cancelled";
