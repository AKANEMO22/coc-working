"use client";

import React, { useEffect, useRef } from "react";
import { Mic, Volume2 } from "lucide-react";

interface AudioVisualizerProps {
  status: "connecting" | "ready" | "listening" | "thinking" | "speaking";
  audioLevel?: number; // 0.0 to 1.0
  frequencyData?: Uint8Array | null;
}

export function AudioVisualizer({ status, audioLevel = 0, frequencyData }: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;

    const render = () => {
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      if (status === "listening" || status === "speaking") {
        const barCount = 32;
        const barWidth = width / barCount - 2;
        const centerY = height / 2;

        for (let i = 0; i < barCount; i++) {
          let magnitude = 0.2;
          if (frequencyData && frequencyData.length > 0) {
            const freqIndex = Math.floor((i / barCount) * frequencyData.length);
            magnitude = frequencyData[freqIndex] / 255;
          } else {
            // Organic wave based on audioLevel
            magnitude = Math.max(0.15, Math.sin((Date.now() / 200) + i * 0.4) * 0.4 * (audioLevel + 0.3) + 0.3);
          }

          const barHeight = Math.max(6, magnitude * (height * 0.85));
          const x = i * (barWidth + 2);
          const y = centerY - barHeight / 2;

          // Gradient color: Coc green to cyan for candidate, violet to blue for AI
          const gradient = ctx.createLinearGradient(0, y, 0, y + barHeight);
          if (status === "listening") {
            gradient.addColorStop(0, "#4ade80");
            gradient.addColorStop(1, "#06b6d4");
          } else {
            gradient.addColorStop(0, "#a855f7");
            gradient.addColorStop(1, "#3b82f6");
          }

          ctx.fillStyle = gradient;
          ctx.beginPath();
          ctx.roundRect(x, y, barWidth, barHeight, 3);
          ctx.fill();
        }
      }

      animId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animId);
    };
  }, [status, audioLevel, frequencyData]);

  return (
    <div className="flex flex-col items-center justify-center p-6 w-full max-w-xl">
      {/* Orb Center */}
      <div className="relative mb-6">
        <div
          className={`w-36 h-36 rounded-full flex items-center justify-center transition-all duration-500 relative z-10 ${
            status === "listening"
              ? "bg-gradient-to-br from-[var(--coc-primary)] to-[var(--coc-accent)] shadow-[0_0_50px_rgba(34,197,94,0.45)] scale-105"
              : status === "speaking"
              ? "bg-gradient-to-br from-violet-500 to-blue-500 shadow-[0_0_50px_rgba(168,85,247,0.45)] scale-105"
              : status === "thinking"
              ? "bg-gradient-to-br from-amber-500 to-orange-500 shadow-[0_0_40px_rgba(245,158,11,0.35)]"
              : "bg-[var(--bg-secondary)] border-2 border-[var(--border-color)]"
          }`}
        >
          {status === "listening" && (
            <div className="flex items-center gap-1.5">
              {[0, 1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="w-1.5 bg-white rounded-full animate-pulse"
                  style={{
                    height: `${20 + Math.random() * 24}px`,
                    animationDelay: `${i * 0.12}s`,
                  }}
                />
              ))}
            </div>
          )}

          {status === "speaking" && (
            <Volume2 className="w-14 h-14 text-white animate-bounce" />
          )}

          {status === "thinking" && (
            <div className="flex gap-2">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="w-3 h-3 rounded-full bg-white animate-bounce"
                  style={{ animationDelay: `${i * 0.18}s` }}
                />
              ))}
            </div>
          )}

          {(status === "ready" || status === "connecting") && (
            <Mic className="w-12 h-12 text-[var(--text-muted)]" />
          )}
        </div>

        {/* Ambient Ring */}
        {(status === "listening" || status === "speaking") && (
          <div className="absolute inset-0 -m-4 rounded-full border border-white/20 animate-ping opacity-75" />
        )}
      </div>

      {/* Canvas Waveform */}
      <canvas
        ref={canvasRef}
        width={420}
        height={70}
        className="w-full max-w-md h-16 rounded-xl bg-[var(--bg-secondary)]/50 border border-[var(--border-color)] p-1 backdrop-blur-sm"
      />

      {/* Status Label */}
      <div className="text-center mt-5">
        <p className="text-lg font-semibold text-[var(--text-primary)]">
          {status === "connecting" && "Đang kết nối tới phòng phỏng vấn..."}
          {status === "ready" && "Sẵn sàng — Nhấn micro để bắt đầu trả lời"}
          {status === "listening" && "🎙️ Đang lắng nghe bạn nói (VAD kích hoạt)..."}
          {status === "thinking" && "💭 Đang đánh giá câu trả lời theo rubric..."}
          {status === "speaking" && "🔊 Phỏng vấn viên đang phản hồi (Barge-in sẵn sàng)..."}
        </p>
        <p className="text-xs text-[var(--text-muted)] mt-1">
          {status === "listening"
            ? "Nói xong hãy dừng nói (VAD tự chốt) hoặc nhấn tắt mic."
            : "Hệ thống hỗ trợ chen ngang (barge-in) khi phỏng vấn viên đang nói."}
        </p>
      </div>
    </div>
  );
}
