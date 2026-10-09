"""Typed application errors carrying user-friendly messages.

The UI never shows raw stack traces; every failure path raises a
:class:`BiyaError` subclass which the API layer serializes into
``{code, message, hint}``.
"""

from __future__ import annotations

from typing import Any, Optional


class BiyaError(Exception):
    """Base class for all errors that are safe to show to the user."""

    code = "error"
    status = 400

    def __init__(self, message: str, *, hint: Optional[str] = None,
                  detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail = detail  # log-only, never sent to the UI

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        return payload


class InvalidRequestError(BiyaError):
    code = "invalid_request"
    status = 400


class NotFoundError(BiyaError):
    code = "not_found"
    status = 404


class UnsupportedFormatError(BiyaError):
    code = "unsupported_format"
    status = 415

    def __init__(self, message: str = "This file type is not supported.",
                 *, hint: Optional[str] = None, detail: Optional[str] = None) -> None:
        super().__init__(
            message,
            hint=hint or "Supported formats: PNG, JPG/JPEG and WEBP.",
            detail=detail,
        )


class CorruptImageError(BiyaError):
    code = "corrupt_image"
    status = 422

    def __init__(self, message: str = "This image could not be read.",
                 *, hint: Optional[str] = None, detail: Optional[str] = None) -> None:
        super().__init__(
            message,
            hint=hint or "The file may be damaged or incomplete. Try re-exporting it.",
            detail=detail,
        )


class ImageTooLargeError(BiyaError):
    code = "image_too_large"
    status = 413


class ModelNotFoundError(BiyaError):
    code = "model_missing"
    status = 409

    def __init__(self, message: str = "The AI model is not installed yet.",
                 *, hint: Optional[str] = None, detail: Optional[str] = None) -> None:
        super().__init__(
            message,
            hint=hint or "Open the model manager and download the model first.",
            detail=detail,
        )


class ModelDownloadError(BiyaError):
    code = "model_download_failed"
    status = 502


class ModelLoadError(BiyaError):
    code = "model_load_failed"
    status = 500


class OutOfMemoryError(BiyaError):  # noqa: A001 - intentionally shadows builtin within app
    code = "out_of_memory"
    status = 507

    def __init__(self, message: str = "Not enough memory to process this image.",
                 *, hint: Optional[str] = None, detail: Optional[str] = None) -> None:
        super().__init__(
            message,
            hint=hint or "Close other applications, or try a smaller image or the 2x scale.",
            detail=detail,
        )


class ProcessingCancelled(BiyaError):
    code = "cancelled"
    status = 409


class DeviceError(BiyaError):
    code = "device_error"
    status = 500
