"use client";

import { useEffect, useState } from "react";
import { Terminal, X } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type InterviewLog = {
  id: string;
  timestamp: string;
  stage: string;
  session_id: string;
  turn_id?: string;
  message: string;
  details?: Record<string, unknown>;
};

type StageTiming = { samples: number; p50_ms: number; p95_ms: number; max_ms: number };

const TIMING_LABELS: Record<string, string> = {
  LAYA_STREAM_DECISION: "Laya theo dõi partial",
  ASR_GATE: "Xác nhận transcript",
  LIVE_ORCHESTRATION: "Laya chọn hướng hỏi",
  QUESTION_ENGINE: "Orchestrator sinh câu tiếp",
  QUESTION_GENERATION_ERROR: "Sinh câu hỏi lỗi",
  QUESTION_GENERATION: "Orchestrator sinh câu",
  STREAM_CLARIFICATION_DELIVERED: "Tạo lời hỏi làm rõ",
  ANSWER_TO_NEXT_QUESTION: "Đáp án → câu hỏi kế",
  NEURAL_TTS_ALIGNED: "Tạo âm thanh TTS",
  VOICE_CLIENT_TIMING: "TTS chuẩn bị → âm thanh đầu",
  VOICE_TURN_LATENCY: "Nói xong → câu tiếp phát tiếng",
};

const SLOW_AFTER_P95_MS: Record<string, number> = {
  LAYA_STREAM_DECISION: 2000,
  ASR_GATE: 2000,
  LIVE_ORCHESTRATION: 2000,
  QUESTION_GENERATION: 6000,
  STREAM_CLARIFICATION_DELIVERED: 4000,
  ANSWER_TO_NEXT_QUESTION: 6000,
  VOICE_TURN_LATENCY: 8000,
};

type InterviewActivityPanelProps = { sessionId: string; onClose: () => void };

export function InterviewActivityPanel({ sessionId, onClose }: InterviewActivityPanelProps) {
  const [logs, setLogs] = useState<InterviewLog[]>([]);
  const [timingSummary, setTimingSummary] = useState<Record<string, StageTiming>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    let pending = false;

    async function readSessionLogs() {
      if (pending || controller.signal.aborted) return;
      pending = true;
      try {
        const query = new URLSearchParams({ session_id: sessionId, limit: "50" });
        const response = await fetch(`${API_BASE}/api/v1/sessions/live-logs?${query}`, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Không đọc được log phiên phỏng vấn.");
        const data = await response.json() as { logs?: InterviewLog[]; timing_summary?: Record<string, StageTiming> };
        if (!controller.signal.aborted) {
          setLogs((data.logs || []).filter((entry) => entry.session_id === sessionId));
          setTimingSummary(data.timing_summary || {});
          setError(null);
        }
      } catch (failure: unknown) {
        if (!controller.signal.aborted) {
          setError(failure instanceof Error ? failure.message : "Không đọc được log phỏng vấn.");
        }
      } finally {
        pending = false;
      }
    }

    void readSessionLogs();
    const interval = setInterval(() => void readSessionLogs(), 3000);
    return () => { controller.abort(); clearInterval(interval); };
  }, [sessionId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <section role="dialog" aria-modal="true" aria-labelledby="interview-log-title" className="w-full max-w-3xl rounded-2xl border border-[var(--border-color)] bg-[#0d1117] shadow-2xl overflow-hidden">
        <header className="px-4 py-3 border-b border-[var(--border-color)] flex items-start justify-between gap-3">
          <div>
            <h2 id="interview-log-title" className="text-sm font-bold text-[var(--text-primary)] flex items-center gap-2">
              <Terminal className="w-4 h-4 text-[var(--coc-primary)]" /> Log phiên phỏng vấn
            </h2>
            <p className="text-xs text-[var(--text-muted)] mt-1">CV/JD → STT + Laya theo dõi trực tiếp → hỏi làm rõ nếu cần → câu hỏi/TTS. Rubric chỉ chạy sau khi kết thúc phiên. Chỉ đọc log; không crawl Internet.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Đóng log phỏng vấn" className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </header>
        <div className="p-4 max-h-[70vh] overflow-y-auto space-y-3">
          {error && <p className="text-xs text-amber-300">{error}</p>}
          {Object.keys(timingSummary).length > 0 && (
            <section aria-label="Thời gian xử lý các giai đoạn" className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3">
              <h3 className="mb-2 text-xs font-semibold text-cyan-200">Latency theo các lượt đã ghi nhận</h3>
              <p className="mb-2 text-[10px] text-[var(--text-muted)]">P50/P95 tính từ các lượt trong phiên. Gắn nhãn CHẬM nếu P95 vượt ngân sách mục tiêu nội bộ.</p>
              <div className="space-y-1.5">
                {Object.entries(timingSummary).map(([stage, timing]) => (
                  <div key={stage} className="grid grid-cols-[1fr_auto] gap-2 text-[10px] font-mono">
                    <span className="text-[var(--text-secondary)]">{TIMING_LABELS[stage] || stage}</span>
                    <span className="text-[var(--text-primary)]">
                      P50 {timing.p50_ms} · P95 {timing.p95_ms} · max {timing.max_ms} ms ({timing.samples})
                      {SLOW_AFTER_P95_MS[stage] !== undefined && timing.p95_ms > SLOW_AFTER_P95_MS[stage] && (
                        <strong className="ml-1 text-rose-300">CHẬM</strong>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}
          {!logs.length && !error && <p className="text-xs text-[var(--text-muted)]">Chưa có log cho phiên này.</p>}
          {logs.map((entry) => (
            <article key={entry.id} className="p-3 rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)]/40">
              <div className="flex flex-wrap gap-2 items-center text-[10px] font-mono text-[var(--text-muted)]">
                <time>{entry.timestamp}</time>
                <span className="text-[var(--coc-primary)]">{entry.stage}</span>
                {entry.turn_id && <span>{entry.turn_id}</span>}
              </div>
              <p className="text-xs text-[var(--text-primary)] mt-1">{entry.message}</p>
              {entry.details && Object.keys(entry.details).length > 0 && (
                <details className="mt-2 text-xs text-[var(--text-secondary)]">
                  <summary className="cursor-pointer">Chi tiết luồng</summary>
                  <pre className="text-[11px] mt-2 whitespace-pre-wrap break-words font-mono">{JSON.stringify(entry.details, null, 2)}</pre>
                </details>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
