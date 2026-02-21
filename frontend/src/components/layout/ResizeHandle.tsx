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
      className="w-[3px] flex-shrink-0 cursor-col-resize bg-gray-200 hover:bg-[#002FA7]/30 active:bg-[#002FA7]/50 transition-colors"
      onMouseDown={onMouseDown}
    />
  );
}
