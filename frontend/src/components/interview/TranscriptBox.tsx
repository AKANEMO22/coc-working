"use client";

import React, { useRef, useEffect } from "react";
import { MessageSquare, Bot, User, AlertCircle, Volume2 } from "lucide-react";

export interface TranscriptMessage {
  id: string;
  role: "ai" | "candidate" | "system";
  text: string;
  time: string;
  isPartial?: boolean;
  needsRepeat?: boolean;
  termCandidates?: string[];
  speechText?: string;
  speechPending?: boolean;
}

interface TranscriptBoxProps {
  messages: TranscriptMessage[];
  currentPartialText?: string;
  onSpeak?: (text: string) => void;
}

export function TranscriptBox({
  messages,
  currentPartialText,
  onSpeak,
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
            data-message-id={msg.id}
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
              {msg.role === "ai" && onSpeak && msg.speechText && (
                <button
                  type="button"
                  disabled={msg.speechPending}
                  onClick={() => onSpeak(msg.speechText || msg.text)}
                  title="Nghe lại câu hỏi"
                  aria-label="Nghe lại câu hỏi"
                  className="ml-1 rounded-md p-1 text-[var(--coc-primary)] hover:bg-[var(--coc-primary)]/10 disabled:opacity-40"
                >
                  <Volume2 className="w-3.5 h-3.5" />
                </button>
              )}
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
              <p>{msg.text || (msg.speechPending ? "Đang chuẩn bị lời thoại…" : "")}</p>

              {/* Unclear speech is handled by an automatic spoken follow-up. */}
              {msg.needsRepeat && (
                <div className="mt-2.5 pt-2 border-t border-white/20">
                  <div className="flex items-center gap-1.5 text-xs text-amber-200 font-medium">
                    <AlertCircle className="w-3.5 h-3.5" />
                    <span>Chưa nghe rõ ý này; AI sẽ hỏi lại bằng giọng nói.</span>
                  </div>
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
