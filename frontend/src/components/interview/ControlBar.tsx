import React, { useState } from "react";
import { Mic, PhoneOff, HelpCircle, MessageSquarePlus, StopCircle, Send, Sparkles } from "lucide-react";

interface ControlBarProps {
  isRecording: boolean;
  vadAvailable: boolean;
  isConnected: boolean;
  status: "connecting" | "ready" | "listening" | "thinking" | "speaking";
  onBargeIn: () => void;
  onEndSession: () => void;
  onOpenReverseModal?: () => void;
  onOpenSelfReportModal?: () => void;
  onSubmitText?: (text: string) => void;
  onSubmitDemoAnswer?: (text: string) => void;
}

export function ControlBar({
  isRecording,
  vadAvailable,
  isConnected,
  status,
  onBargeIn,
  onEndSession,
  onOpenReverseModal,
  onOpenSelfReportModal,
  onSubmitText,
  onSubmitDemoAnswer,
}: ControlBarProps) {
  const [inputText, setInputText] = useState("");

  const handleSend = () => {
    if (!inputText.trim()) return;
    onSubmitText?.(inputText.trim());
    setInputText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col gap-2 px-6 py-3 border-t border-[var(--border-color)] bg-[var(--glass-bg)] backdrop-blur-lg">
      {/* Quick Text Answer Bar */}
      <div className="flex items-center gap-2 max-w-3xl w-full mx-auto">
        <input
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Nhập câu trả lời của bạn hoặc nói tự nhiên — micro tự bật..."
          disabled={!isConnected || status === "connecting" || status === "thinking"}
          className="flex-1 px-4 py-2 text-xs rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--coc-primary)] transition-all"
        />
        <button
          onClick={handleSend}
          disabled={!inputText.trim() || !isConnected || status === "connecting" || status === "thinking"}
          title="Gửi câu trả lời"
          className="px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] text-white text-xs font-semibold flex items-center gap-1.5 shadow-md hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          <Send className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Gửi</span>
        </button>
      </div>

      {process.env.NODE_ENV === "development" && onSubmitDemoAnswer && (
        <div className="flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => onSubmitDemoAnswer(
              "Em chọn FPT Software vì muốn tham gia các dự án backend thực tế và học quy trình làm việc với khách hàng Nhật. Trong dự án gần đây, em phát triển API bằng Java và Spring Boot, tối ưu truy vấn SQL kết hợp Redis giúp giảm 25% thời gian phản hồi. Em muốn tiếp tục rèn thiết kế API, kiểm thử và phối hợp với QA theo quy trình Agile."
            )}
            disabled={!isConnected || status === "connecting" || status === "thinking"}
            title="Gửi transcript mẫu qua đúng WebSocket phỏng vấn; không mô phỏng âm thanh hoặc STT"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-cyan-500/30 bg-cyan-500/5 text-cyan-300 text-[11px] font-semibold hover:bg-cyan-500/10 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Gửi câu trả lời mẫu (dev)</span>
          </button>
          <span className="text-[10px] text-[var(--text-muted)]">Kiểm tra luồng hội thoại; micro tự bật khi đến lượt trả lời.</span>
        </div>
      )}

      {/* Button Controls Bar */}
      <div className="flex items-center justify-center gap-4">
        {/* Self-Report button (§12.1.4) */}
        {onOpenSelfReportModal && (
          <button
            onClick={onOpenSelfReportModal}
            title="Tự báo cáo trạng thái tâm lý / giao tiếp"
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-xl bg-[var(--bg-secondary)] hover:bg-[var(--border-color)] text-[var(--text-secondary)] transition-all"
          >
            <HelpCircle className="w-4 h-4 text-amber-400" />
            <span className="hidden sm:inline">Tâm lý</span>
          </button>
        )}

        {/* Reverse question button (§11.4) */}
        {onOpenReverseModal && (
          <button
            onClick={onOpenReverseModal}
            title="Đặt câu hỏi ngược cho doanh nghiệp"
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-xl bg-[var(--bg-secondary)] hover:bg-[var(--border-color)] text-[var(--text-secondary)] transition-all"
          >
            <MessageSquarePlus className="w-4 h-4 text-[var(--coc-accent)]" />
            <span className="hidden sm:inline">Hỏi ngược</span>
          </button>
        )}

        {/* Barge-in Quick Stop (Active when AI is speaking) */}
        {status === "speaking" && (
          <button
            onClick={onBargeIn}
            title="Chen ngang (Barge-in)"
            className="flex items-center gap-2 px-4 py-2.5 rounded-full bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 text-xs font-bold animate-pulse transition-all"
          >
            <StopCircle className="w-4 h-4" />
            <span>Ngắt lời (Barge-in)</span>
          </button>
        )}

        <div
          role="status"
          aria-live="polite"
          className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-semibold ${
            isRecording
              ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
              : "bg-[var(--bg-secondary)] text-[var(--text-muted)] border border-[var(--border-color)]"
          }`}
        >
          <Mic className={`w-4 h-4 ${isRecording ? "animate-pulse" : ""}`} />
          <span>
            {isRecording
              ? vadAvailable
                ? "Micro vẫn nghe qua nhịp dừng — sẽ tự chốt"
                : "Đang dùng VAD dự phòng — sẽ tự chốt"
              : status === "speaking"
                ? "Micro sẽ tự bật sau khi câu hỏi được đọc xong"
                : "Micro tự bật khi đến lượt bạn trả lời"}
          </span>
        </div>

        {/* End Session */}
        <button
          onClick={onEndSession}
          title="Kết thúc phiên phỏng vấn"
          className="w-10 h-10 rounded-full bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 flex items-center justify-center transition-all"
        >
          <PhoneOff className="w-4 h-4 text-red-400" />
        </button>
      </div>
      <p className="text-center text-[10px] text-[var(--text-muted)]">
        Silero phát hiện lời nói; Laya có thể hỏi làm rõ ngay khi bạn đang nói. Rubric chỉ được chấm khi kết thúc phiên.
      </p>
    </div>
  );
}
