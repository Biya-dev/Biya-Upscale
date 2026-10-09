// Typed client for the local API. Everything here talks to 127.0.0.1 only.

import type {
  AppStatus,
  ImageRecord,
  Job,
  ModelInfo,
  OutputFormat,
} from "./types";

export class ApiError extends Error {
  code: string;
  hint?: string | null;

  constructor(code: string, message: string, hint?: string | null) {
    super(message);
    this.code = code;
    this.hint = hint;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const options: RequestInit = { ...init };
  if (init?.json !== undefined) {
    options.method = init.method ?? "POST";
    options.headers = {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    };
    options.body = JSON.stringify(init.json);
  }
  let response: Response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(
      "network",
      "Cannot reach the local Biya Upscale service.",
      "Restart the application and try again.",
    );
  }
  if (!response.ok) {
    let code = "error";
    let message = `Request failed (${response.status}).`;
    let hint: string | null = null;
    try {
      const body = await response.json();
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
        hint = body.error.hint ?? null;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(code, message, hint);
  }
  return (await response.json()) as T;
}

export const api = {
  status: () => request<AppStatus>("/api/status"),

  setSettings: (updates: Record<string, unknown>) =>
    request<{ settings: AppStatus["settings"] }>("/api/settings", {
      json: updates,
    }),

  uploadImage: async (file: File): Promise<ImageRecord> => {
    const response = await fetch(
      `/api/images?filename=${encodeURIComponent(file.name)}`,
      { method: "POST", body: file },
    );
    if (!response.ok) {
      let code = "error";
      let message = `Could not add "${file.name}".`;
      let hint: string | null = null;
      try {
        const body = await response.json();
        code = body?.error?.code ?? code;
        message = body?.error?.message ?? message;
        hint = body?.error?.hint ?? null;
      } catch {
        /* ignore */
      }
      throw new ApiError(code, message, hint);
    }
    return (await response.json()) as ImageRecord;
  },

  deleteImage: (imageId: string) =>
    request<{ ok: boolean }>(`/api/images/${imageId}`, { method: "DELETE" }),

  models: () => request<{ models: ModelInfo[] }>("/api/models"),

  downloadModel: (modelId: string) =>
    request<{ ok: boolean }>(`/api/models/${modelId}/download`, {
      method: "POST",
    }),

  cancelModelDownload: (modelId: string) =>
    request<{ ok: boolean }>(`/api/models/${modelId}/cancel-download`, {
      method: "POST",
    }),

  startUpscale: (
    imageId: string,
    scale: number,
    modelId?: string,
  ) =>
    request<{ job_id: string; job: Job }>("/api/upscale", {
      json: { image_id: imageId, scale, model_id: modelId },
    }),

  listJobs: () => request<{ jobs: Job[] }>("/api/jobs"),

  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),

  cancelJob: (jobId: string) =>
    request<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),

  previewUrl: (jobId: string) => `/api/jobs/${jobId}/preview`,

  downloadUrl: (
    jobId: string,
    format: OutputFormat,
    quality: number,
  ) => `/api/jobs/${jobId}/download?format=${format}&quality=${quality}`,
};
