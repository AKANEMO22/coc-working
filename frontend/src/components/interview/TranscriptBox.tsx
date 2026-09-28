"use client";

import React, { useRef, useEffect } from "react";
import { MessageSquare, Bot, User, CheckCircle2, AlertCircle } from "lucide-react";

export interface TranscriptMessage {
  id: string;
  role: "ai" | "candidate" | "system";
  text: string;
  time: string;
  isPartial?: boolean;
  needsConfirmation?: boolean;
  termCandidates?: string[];
}

interface TranscriptBoxProps {
  messages: TranscriptMessage[];
  currentPartialText?: string;
  onConfirmTranscript?: (messageId: string, confirmedText: string) => void;
}

export function TranscriptBox({
  messages,
  currentPartialText,
  onConfirmTranscript,
}: TranscriptBoxProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, currentPartialText]);

  return (
    <div className="w-full lg:w-96 border-t lg:border-t-0 lg:border-l border-[var(--border-color)] flex flex-col h-full bg-[var(--bg-secondary)]/30 backdrop-blur-md">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-color)] bg-[var(--glass-bg)]">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-[var(--coc-primary)]" />
          <span className="text-sm font-semibold text-[var(--text-primary)]">
            Hội thoại trực tiếp
          </span>
        </div>
        <span className="text-xs text-[var(--text-muted)]">
          {messages.length} lượt trao đổi
        </span>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex flex-col ${
              msg.role === "candidate" ? "items-end" : "items-start"
            }`}
          >
            <div className="flex items-center gap-1.5 mb-1 px-1">
              {msg.role === "ai" ? (
                <>
                  <Bot className="w-3.5 h-3.5 text-[var(--coc-accent)]" />
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">
                    Phỏng vấn viên AI
                  </span>
                </>
              ) : msg.role === "candidate" ? (
                <>
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">
                    Bạn
                  </span>
                  <User className="w-3.5 h-3.5 text-[var(--coc-primary)]" />
                </>
              ) : (
                <span className="text-[11px] font-medium text-amber-400">
                  Hệ thống
                </span>
              )}
              <span className="text-[10px] text-[var(--text-muted)] ml-1">
                {msg.time}
              </span>
            </div>

            <div
              className={`max-w-[88%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                msg.role === "candidate"
                  ? "bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] text-white shadow-sm"
                  : msg.role === "ai"
                  ? "bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-primary)] shadow-sm"
                  : "bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs"
              }`}
            >
              <p>{msg.text}</p>

              {/* ASR Gate Confirmation Fallback (§8.2) */}
              {msg.needsConfirmation && onConfirmTranscript && (
                <div className="mt-2.5 pt-2 border-t border-white/20">
                  <div className="flex items-center gap-1.5 text-xs text-amber-200 mb-1.5 font-medium">
                    <AlertCircle className="w-3.5 h-3.5" />
                    <span>Cần xác nhận thuật ngữ kỹ thuật:</span>
                  </div>
                  {msg.termCandidates && msg.termCandidates.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-2">
                      {msg.termCandidates.map((cand, idx) => (
                        <button
                          key={idx}
                          onClick={() => onConfirmTranscript(msg.id, cand)}
                          className="px-2 py-0.5 rounded text-xs bg-white/20 hover:bg-white/30 text-white font-mono"
                        >
                          {cand}
                        </button>
                      ))}
                    </div>
                  )}
                  <button
                    onClick={() => onConfirmTranscript(msg.id, msg.text)}
                    className="flex items-center gap-1 text-xs bg-emerald-500/30 hover:bg-emerald-500/40 text-emerald-100 px-2.5 py-1 rounded-md transition-all font-medium"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Xác nhận nội dung đúng</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Live Partial Streaming Bubble */}
        {currentPartialText && (
          <div className="flex flex-col items-end">
            <div className="flex items-center gap-1.5 mb-1 px-1">
              <span className="text-[11px] font-medium text-[var(--text-secondary)]">
                Đang nói...
              </span>
              <div className="w-2 h-2 rounded-full bg-[var(--coc-primary)] animate-ping" />
            </div>
            <div className="max-w-[88%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed bg-[var(--coc-primary)]/20 border border-[var(--coc-primary)]/40 text-[var(--text-primary)] animate-pulse">
              <p>{currentPartialText}</p>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
