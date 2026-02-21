"use client";

export default function Navbar() {
  return (
    <header className="h-11 flex items-center justify-between px-4 border-b border-gray-200 bg-white/80 backdrop-blur-md flex-shrink-0 z-10">
      <span className="font-semibold text-sm tracking-tight text-gray-900">
        mini OpenClaw
      </span>
      <a
        href="https://fufan.ai"
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs text-gray-400 hover:text-[#002FA7] transition-colors"
      >
        赋范空间
      </a>
    </header>
  );
}
