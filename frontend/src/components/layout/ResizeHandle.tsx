"use client";

import { useCallback } from "react";

interface ResizeHandleProps {
  onResize: (delta: number) => void;
}

export default function ResizeHandle({ onResize }: ResizeHandleProps) {
  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      let lastX = e.clientX;

      const onMove = (ev: MouseEvent) => {
        const dx = ev.clientX - lastX;
        lastX = ev.clientX;
        onResize(dx);
      };

      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [onResize]
  );

  return (
    <div
      className="group relative w-3 flex-shrink-0 cursor-col-resize"
      onMouseDown={onMouseDown}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize panel"
    >
      <div className="apex-divider absolute inset-y-5 left-1/2 w-px -translate-x-1/2 rounded-full transition-colors group-hover:bg-[var(--apex-accent-glow)] group-active:bg-[var(--apex-accent)]" />
      <div className="absolute inset-y-9 left-1/2 w-1.5 -translate-x-1/2 rounded-full bg-transparent transition-colors group-hover:bg-[rgba(47,122,95,0.12)] group-active:bg-[rgba(47,122,95,0.18)]" />
    </div>
  );
}
