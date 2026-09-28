import React, { useState } from "react";
import { Mic, MicOff, PhoneOff, HelpCircle, MessageSquarePlus, StopCircle, Send } from "lucide-react";

interface ControlBarProps {
  isRecording: boolean;
  isSpeaking: boolean;
  status: "connecting" | "ready" | "listening" | "thinking" | "speaking";
  onToggleMic: () => void;
  onBargeIn: () => void;
  onEndSession: () => void;
  onOpenReverseModal?: () => void;
  onOpenSelfReportModal?: () => void;
  onSubmitText?: (text: string) => void;
}

export function ControlBar({
  isRecording,
  isSpeaking,
  status,
  onToggleMic,
  onBargeIn,
  onEndSession,
  onOpenReverseModal,
  onOpenSelfReportModal,
  onSubmitText,
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
          placeholder="Nhập câu trả lời của bạn (hoặc bấm Micro bên dưới để nói)..."
          disabled={status === "connecting" || status === "thinking"}
          className="flex-1 px-4 py-2 text-xs rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--coc-primary)] transition-all"
        />
        <button
          onClick={handleSend}
          disabled={!inputText.trim() || status === "connecting" || status === "thinking"}
          title="Gửi câu trả lời"
          className="px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] text-white text-xs font-semibold flex items-center gap-1.5 shadow-md hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          <Send className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Gửi</span>
        </button>
      </div>

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

        {/* Main Mic Button */}
        <button
          onClick={onToggleMic}
          disabled={status === "connecting"}
          title={isRecording ? "Dừng ghi âm & Chấm điểm" : "Bật Micro để trả lời"}
          className={`w-14 h-14 rounded-full flex items-center justify-center transition-all duration-300 ${
            isRecording
              ? "bg-red-500 hover:bg-red-600 shadow-[0_0_30px_rgba(239,68,68,0.45)] scale-105"
              : "bg-gradient-to-br from-[var(--coc-primary)] to-[var(--coc-accent)] hover:shadow-[var(--shadow-glow)] hover:scale-105"
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          {isRecording ? (
            <MicOff className="w-6 h-6 text-white" />
          ) : (
            <Mic className="w-6 h-6 text-white" />
          )}
        </button>

        {/* End Session */}
        <button
          onClick={onEndSession}
          title="Kết thúc phiên phỏng vấn"
          className="w-10 h-10 rounded-full bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 flex items-center justify-center transition-all"
        >
          <PhoneOff className="w-4 h-4 text-red-400" />
        </button>
      </div>
    </div>
  );
}
