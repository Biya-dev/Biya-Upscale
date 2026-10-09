import { useRef, useState } from "react";
import type { DragEvent } from "react";
import { ACCEPTED_EXTENSIONS } from "../format";
import { IconUpload } from "./Icons";

interface Props {
  disabled?: boolean;
  onFiles: (files: File[]) => void;
}

export default function DropZone({ disabled, onFiles }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    onFiles(Array.from(event.dataTransfer.files ?? []));
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!disabled) setDragging(true);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Drop images here or click to select files"
      className={`fade-up relative cursor-pointer rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-colors ${
        dragging
          ? "border-accent bg-accent-soft"
          : "border-line2 bg-panel hover:border-accent/60"
      } ${disabled ? "pointer-events-none opacity-50" : ""}`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={() => setDragging(false)}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.map((e) => `.${e}`).join(",")}
        className="hidden"
        onChange={(e) => {
          if (e.target.files) onFiles(Array.from(e.target.files));
          e.target.value = ""; // allow re-selecting the same file
        }}
      />

      <span className="mx-auto mb-4 grid size-14 place-items-center rounded-2xl border border-line bg-panel2 text-accent">
        <IconUpload width={24} height={24} />
      </span>

      <div className="text-lg font-semibold tracking-tight">
        {dragging ? "Release to add images" : "Drag & drop images here"}
      </div>
      <div className="mt-1.5 text-sm text-muted">
        or{" "}
        <span className="font-semibold text-accent underline underline-offset-4">
          select images
        </span>{" "}
        from your computer
      </div>
      <div className="mt-5 flex flex-wrap items-center justify-center gap-2 text-[11.5px] text-muted">
        {ACCEPTED_EXTENSIONS.map((ext) => (
          <span
            key={ext}
            className="rounded-md border border-line bg-panel2 px-2 py-0.5 font-medium uppercase"
          >
            {ext === "jpeg" ? "jpg" : ext}
          </span>
        ))}
        <span className="px-1">·</span>
        <span>multiple files supported</span>
      </div>
    </div>
  );
}
