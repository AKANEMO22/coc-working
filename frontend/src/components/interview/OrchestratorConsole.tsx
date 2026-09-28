"use client";

import React, { useState, useEffect, useRef } from "react";
import { Terminal, Globe, Database, Cpu, CheckCircle2, RefreshCw, ChevronDown, ChevronUp, Sparkles, ExternalLink, ShieldCheck } from "lucide-react";

export interface OrchestratorLog {
  id: string;
  timestamp: string;
  level: "INFO" | "TOOL_CALL" | "TOOL_RESULT" | "INGEST" | "SUCCESS" | "WARN" | "RAW_MCP_LOG";
  tool_name?: string;
  message: string;
  details?: Record<string, any>;
}

export interface IngestedQuestion {
  id: string;
  question: string;
  stage: string;
  rubric_type: string;
  difficulty: number;
  expected_concepts: string[];
  source: string;
  url?: string;
}

interface OrchestratorConsoleProps {
  company: string;
  role: string;
  studentId?: string | null;
  mode?: "embedded" | "modal";
  isOpen?: boolean;
  onClose?: () => void;
  onQuestionsLoaded?: (questions: IngestedQuestion[]) => void;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function OrchestratorConsole({
  company,
  role,
  studentId,
  mode = "embedded",
  isOpen = true,
  onClose,
  onQuestionsLoaded,
}: OrchestratorConsoleProps) {
  const [logs, setLogs] = useState<OrchestratorLog[]>([]);
  const [questions, setQuestions] = useState<IngestedQuestion[]>([]);
  const [activeTab, setActiveTab] = useState<"logs" | "bank">("logs");
  const [isExecuting, setIsExecuting] = useState(false);
  // Default to collapsed (an di) so it doesn't clutter the page, expandable on demand as CMD tab
  const [isExpanded, setIsExpanded] = useState(false);

  const lastScannedKeyRef = useRef<string>("");
  const debounceTimerRef = useRef<any>(null);

  // Trigger orchestrator discovery
  const triggerDiscovery = async (targetComp = company, targetR = role) => {
    if (!targetComp || !targetR || !targetR.trim()) return;
    setIsExecuting(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/questions/orchestrate-discovery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company: targetComp,
          role: targetR,
          student_id: studentId || "GUEST",
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.logs) setLogs(data.logs);
        if (data.questions) {
          setQuestions(data.questions);
          onQuestionsLoaded?.(data.questions);
        }
      }
    } catch (err) {
      console.warn("Orchestrator discovery trigger failed:", err);
    } finally {
      setIsExecuting(false);
    }
  };

  // Poll latest logs
  const fetchLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/questions/orchestrator-logs?limit=40`);
      if (res.ok) {
        const data = await res.json();
        if (data.logs && data.logs.length > 0) {
          setLogs(data.logs);
        }
      }
    } catch (err) {
      // Ignore polling errors
    }
  };

  // Load existing questions
  const fetchBank = async (comp = company, r = role) => {
    if (!comp || !r || !r.trim()) return;
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/questions/bank?company=${encodeURIComponent(comp)}&role=${encodeURIComponent(r)}&limit=15`
      );
      if (res.ok) {
        const data = await res.json();
        if (data.questions && data.questions.length > 0) {
          setQuestions(data.questions);
          onQuestionsLoaded?.(data.questions);
        }
      }
    } catch (err) {
      console.warn("Fetch bank error:", err);
    }
  };

  // Initial fetch and AUTOMATIC research whenever company or role changes
  useEffect(() => {
    fetchLogs();
    if (company && role && role.trim()) {
      fetchBank(company, role);

      const currentKey = `${company.trim()}::${role.trim()}`;
      if (lastScannedKeyRef.current !== currentKey) {
        lastScannedKeyRef.current = currentKey;
        if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
        // Tự động kích hoạt nghiên cứu / cào đề Internet ngay khi chọn vị trí
        debounceTimerRef.current = setTimeout(() => {
          triggerDiscovery(company, role);
        }, 300);
      }
    }

    const interval = setInterval(fetchLogs, 3000);
    return () => {
      clearInterval(interval);
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [company, role]);

  if (!isOpen) return null;

  // Custom styling matching the screenshot tags
  const getToolStyle = (toolName?: string, level?: string) => {
    const key = (toolName || level || "").toUpperCase();
    if (key.includes("NLP") || key.includes("STRUCTURER")) {
      return {
        card: "border-sky-500/40 bg-sky-950/20 text-sky-200",
        badge: "border-sky-400/60 bg-sky-500/20 text-sky-300 font-bold",
        json: "text-amber-200/90 border-amber-500/30",
      };
    }
    if (key.includes("INGEST") || key.includes("BANK")) {
      return {
        card: "border-purple-500/40 bg-purple-950/20 text-purple-200",
        badge: "border-purple-400/60 bg-purple-500/20 text-purple-300 font-bold",
        json: "text-amber-200/90 border-amber-500/30",
      };
    }
    if (key.includes("ORCHESTRATOR") || key.includes("SUCCESS")) {
      return {
        card: "border-emerald-500/40 bg-emerald-950/20 text-emerald-200",
        badge: "border-emerald-400/60 bg-emerald-500/20 text-emerald-300 font-bold",
        json: "text-emerald-200/90 border-emerald-500/30",
      };
    }
    if (key.includes("VAULT") || key.includes("MATCHER")) {
      return {
        card: "border-amber-500/40 bg-amber-950/20 text-amber-200",
        badge: "border-amber-400/60 bg-amber-500/20 text-amber-300 font-bold",
        json: "text-amber-200/90 border-amber-500/30",
      };
    }
    if (key.includes("MCP") || key.includes("SEARCH")) {
      return {
        card: "border-blue-500/40 bg-blue-950/20 text-blue-200",
        badge: "border-blue-400/60 bg-blue-500/20 text-blue-300 font-bold",
        json: "text-blue-200/90 border-blue-500/30",
      };
    }
    return {
      card: "border-slate-800 bg-slate-900/60 text-slate-300",
      badge: "border-slate-600 bg-slate-800 text-slate-200",
      json: "text-slate-300 border-slate-700",
    };
  };

  const renderLogDetails = (details: Record<string, any>) => {
    if (!details || Object.keys(details).length === 0) return null;

    // 0. Web Content Extractor (Dữ liệu THÔ NGUYÊN BẢN 100% RAW từ trang web)
    if (details.extracted_pages) {
      const pages = details.extracted_pages || [];
      return (
        <div className="mt-2 space-y-2 text-xs bg-black/60 p-3 rounded-xl border border-cyan-500/20 font-mono">
          <div className="text-cyan-300 font-semibold text-[11px] flex items-center gap-1.5 font-sans">
            <span>📄 [RAW WEB SCRAPER] Dữ liệu thô thu thập trực tiếp từ mạng Internet ({pages.length} trang web):</span>
          </div>
          <div className="space-y-2.5">
            {pages.map((p: any, idx: number) => {
              const status = p.status_code || 0;
              const rawText = p.raw_content || p.harvested_content || "";
              const searchSnip = p.search_snippet || "";

              return (
                <div key={idx} className="p-2.5 rounded-lg bg-white/5 border border-white/5 space-y-1.5">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-white font-medium text-xs font-sans">
                      {idx + 1}. {p.title || p.url}
                    </span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                        status === 200 
                          ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30" 
                          : "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                      }`}>
                        {status ? `HTTP ${status}` : "NET_TIMEOUT"}
                      </span>
                      {p.byte_size !== undefined && (
                        <span className="text-[10px] text-slate-400">
                          {p.byte_size.toLocaleString()} bytes
                        </span>
                      )}
                      {p.latency_ms !== undefined && (
                        <span className="text-[10px] text-slate-500">
                          {p.latency_ms}ms
                        </span>
                      )}
                    </div>
                  </div>
                  {p.url && (
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] text-sky-400 hover:text-sky-300 hover:underline flex items-center gap-1 break-all"
                    >
                      <span className="truncate">{p.url}</span>
                      <ExternalLink className="w-3 h-3 shrink-0" />
                    </a>
                  )}
                  {rawText && (
                    <div className="text-[11px] text-slate-200 bg-black/60 p-2 rounded border border-white/10 font-mono leading-relaxed whitespace-pre-wrap break-all">
                      <span className="text-amber-400 font-semibold">[RAW HTTP BODY]: </span>
                      "{rawText}"
                    </div>
                  )}
                  {searchSnip && searchSnip !== rawText && (
                    <div className="text-[10px] text-slate-400 bg-black/40 p-1.5 rounded border border-white/5 font-mono">
                      <span className="text-purple-400 font-semibold">[RAW SEARCH SNIPPET]: </span>
                      "{searchSnip}"
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      );
    }

    // 1. Web Search Sources & Queries
    if (details.sources || details.dynamic_search_queries) {
      const sources = details.sources || [];
      const queries = details.dynamic_search_queries || [];
      const domains = details.discovered_domains || [];

      return (
        <div className="mt-2 space-y-2 text-xs font-mono bg-black/60 p-3 rounded-xl border border-white/10">
          {queries.length > 0 && (
            <div>
              <div className="text-sky-300 font-semibold mb-1 flex items-center gap-1.5">
                <span>🔍 Truy vấn AI sinh:</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {queries.map((q: string, idx: number) => (
                  <span key={idx} className="bg-sky-950/60 border border-sky-500/30 text-sky-200 px-2 py-0.5 rounded-md text-[11px]">
                    "{q}"
                  </span>
                ))}
              </div>
            </div>
          )}

          {domains.length > 0 && (
            <div className="text-[11px] text-slate-300">
              <span className="text-sky-400 font-medium">🌐 Tên miền phát hiện: </span>
              {domains.join(", ")}
            </div>
          )}

          {sources.length > 0 && (
            <div className="space-y-1.5 pt-1 border-t border-white/5">
              <div className="text-emerald-400 font-semibold text-[11px]">
                📑 Link bài viết thảo luận thực tế ({sources.length}):
              </div>
              <div className="space-y-1">
                {sources.map((s: any, idx: number) => (
                  <div key={idx} className="flex items-start justify-between gap-2 p-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors">
                    <div className="min-w-0 flex-1">
                      <div className="text-white font-sans text-xs truncate font-medium">
                        {idx + 1}. {s.title || s.domain || "Bài thảo luận"}
                      </div>
                      {s.url && (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[11px] text-sky-400 hover:text-sky-300 hover:underline flex items-center gap-1 break-all"
                        >
                          <span className="truncate">{s.url}</span>
                          <ExternalLink className="w-3 h-3 shrink-0" />
                        </a>
                      )}
                    </div>
                    {s.domain && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shrink-0">
                        {s.domain}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      );
    }

    // 2. Curated Vault Questions
    if (details.vault_questions) {
      const vqs = details.vault_questions || [];
      return (
        <div className="mt-2 space-y-1.5 text-xs bg-black/60 p-3 rounded-xl border border-amber-500/20">
          <div className="text-amber-300 font-semibold text-[11px] flex items-center gap-1.5">
            <span>🏛️ Kho tri thức kiểm định {details.company_vault || ""} ({vqs.length} câu hỏi):</span>
          </div>
          <div className="space-y-1">
            {vqs.map((q: any, idx: number) => (
              <div key={idx} className="text-amber-100/90 text-[11px] font-sans flex items-start gap-1.5">
                <span className="text-amber-400 font-mono font-bold shrink-0">[Q{idx + 1}]</span>
                <span>{q.question}</span>
              </div>
            ))}
          </div>
        </div>
      );
    }

    // 3. Question Structurer Final List
    if (details.questions_list) {
      const qList = details.questions_list || [];
      return (
        <div className="mt-2 space-y-1.5 text-xs bg-black/60 p-3 rounded-xl border border-purple-500/20">
          <div className="text-purple-300 font-semibold text-[11px]">
            🎯 Ngân hàng đề hoàn chỉnh ({qList.length} câu hỏi) {details.summary ? `— ${details.summary}` : ""}:
          </div>
          <div className="space-y-1 max-h-48 overflow-y-auto pr-1">
            {qList.map((q: any, idx: number) => (
              <div key={idx} className="text-purple-100/90 text-[11px] font-sans flex items-start gap-1.5">
                <span className="text-purple-400 font-mono font-bold shrink-0">{idx + 1}.</span>
                <span className="text-[10px] text-purple-300/70 font-mono shrink-0">[{q.source || "Vault"}]</span>
                <span>{q.question}</span>
              </div>
            ))}
          </div>
        </div>
      );
    }

    // Default formatted JSON
    return (
      <div className="mt-2 text-[11px] font-mono bg-black/60 p-2 rounded-lg border border-white/5 overflow-x-auto text-amber-200/90">
        <pre className="whitespace-pre-wrap">{JSON.stringify(details, null, 2)}</pre>
      </div>
    );
  };

  const content = (
    <div className="rounded-2xl border border-[var(--border-color)] bg-[#0d1117]/95 backdrop-blur-xl overflow-hidden shadow-2xl transition-all duration-300">
      {/* Header Bar */}
      <div className="px-4 py-3 bg-[var(--bg-primary)]/90 border-b border-[var(--border-color)] flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-[var(--coc-primary)]/10 text-[var(--coc-primary)]">
            <Cpu className="w-4 h-4 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-bold text-[var(--text-primary)]">
                Model Orchestrator & Tool Calling Engine
              </h3>
              {isExecuting ? (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/40 flex items-center gap-1 animate-pulse">
                  <RefreshCw className="w-3 h-3 animate-spin" />
                  <span>Đang tự động research...</span>
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                  <ShieldCheck className="w-3 h-3" />
                  <span>System-1 Active</span>
                </span>
              )}
            </div>
            <p className="text-[11px] text-[var(--text-muted)]">
              {isExecuting
                ? `⚡ Đang tự động rà quét Internet & cào đề phỏng vấn cho ${role} tại ${company}...`
                : role
                ? `Tự động khai phá Internet (MCP Web Search) & nạp câu hỏi thực chiến cho ${role} — ${company}`
                : `Vui lòng nhấp chọn một vị trí ứng tuyển bên trên để AI tự động nghiên cứu đề`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Action Tabs: Tool Activity & Question Bank */}
          <div className="flex bg-[var(--bg-secondary)] p-0.5 rounded-xl border border-[var(--border-color)]">
            <button
              onClick={() => {
                setActiveTab("logs");
                setIsExpanded(true);
              }}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                activeTab === "logs" && isExpanded
                  ? "bg-[var(--coc-primary)] text-white shadow-sm"
                  : "text-[var(--text-muted)] hover:text-white"
              }`}
            >
              Tool Activity ({logs.length})
            </button>
            <button
              onClick={() => {
                setActiveTab("bank");
                setIsExpanded(true);
              }}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                activeTab === "bank" && isExpanded
                  ? "bg-[var(--coc-primary)] text-white shadow-sm"
                  : "text-[var(--text-muted)] hover:text-white"
              }`}
            >
              Question Bank ({questions.length})
            </button>
          </div>

          {/* Re-sync Button */}
          <button
            onClick={() => triggerDiscovery()}
            disabled={isExecuting || !role}
            title={role ? "Quét lại dữ liệu mới từ Internet" : "Vui lòng chọn vị trí"}
            className="px-3 py-1 rounded-xl bg-[var(--coc-primary)]/15 border border-[var(--coc-primary)]/40 text-[var(--coc-primary)] hover:bg-[var(--coc-primary)] hover:text-white disabled:opacity-50 transition-all flex items-center gap-1.5 text-xs font-semibold"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isExecuting ? "animate-spin" : ""}`} />
            <span>{isExecuting ? "Đang quét..." : "Quét lại"}</span>
          </button>

          {/* Toggle Expand / Collapse */}
          {mode === "embedded" && (
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              title={isExpanded ? "Ẩn bớt (Thu gọn)" : "Hiện dạng CMD theo dõi"}
              className="px-2.5 py-1 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-secondary)] hover:text-white hover:border-[var(--coc-primary)] transition-all flex items-center gap-1.5 text-xs font-mono"
            >
              <Terminal className="w-3.5 h-3.5 text-[var(--coc-primary)]" />
              <span>{isExpanded ? "Ẩn CMD" : "Hiện CMD"}</span>
              {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
          )}

          {mode === "modal" && onClose && (
            <button
              onClick={onClose}
              className="text-xs px-2.5 py-1 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-white"
            >
              Đóng
            </button>
          )}
        </div>
      </div>

      {/* Body: CMD Style Terminal Console */}
      {isExpanded && (
        <div className="p-4 max-h-80 overflow-y-auto font-mono text-xs bg-[#0b0f14]/90 space-y-2.5 border-t border-[var(--border-color)]">
          {activeTab === "logs" ? (
            <div className="space-y-2">
              {logs.length === 0 ? (
                <div className="text-center py-6 text-[var(--text-muted)]">
                  Chưa có lịch sử gọi Tool. Hãy chọn một công ty để Orchestrator tự động quét...
                </div>
              ) : (
                logs.map((log) => {
                  const style = getToolStyle(log.tool_name, log.level);
                  return (
                    <div
                      key={log.id}
                      className={`p-2.5 rounded-xl border flex flex-col gap-1.5 transition-all ${style.card}`}
                    >
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[10px] text-slate-400 font-mono shrink-0">
                          {log.timestamp}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border shrink-0 ${style.badge}`}
                        >
                          {log.tool_name ? log.tool_name.toUpperCase() : log.level}
                        </span>
                        <span className="font-sans text-xs flex-1 break-words font-medium">
                          {log.message}
                        </span>
                      </div>

                      {log.details && Object.keys(log.details).length > 0 && renderLogDetails(log.details)}
                    </div>
                  );
                })
              )}
            </div>
          ) : (
            <div className="space-y-2.5 font-sans">
              {questions.length === 0 ? (
                <div className="text-center py-6 text-[var(--text-muted)]">
                  Đang nạp câu hỏi từ Web Search & Knowledge Vault...
                </div>
              ) : (
                questions.map((q, idx) => (
                  <div
                    key={q.id || idx}
                    className="p-3 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-color)] hover:border-[var(--coc-primary)]/50 transition-all"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-[var(--coc-primary)]/15 text-[var(--coc-primary)] border border-[var(--coc-primary)]/30 uppercase">
                          {q.stage || "technical_core"}
                        </span>
                        <span className="text-[10px] px-2 py-0.5 rounded-md bg-[var(--bg-secondary)] text-[var(--text-muted)] border border-[var(--border-color)]">
                          Độ khó: {q.difficulty}/5
                        </span>
                        {q.expected_concepts?.map((c) => (
                          <span
                            key={c}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono"
                          >
                            #{c}
                          </span>
                        ))}
                      </div>
                      {q.url ? (
                        <a
                          href={q.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[10px] text-[var(--coc-primary)] hover:underline shrink-0 italic max-w-[220px] truncate flex items-center gap-1"
                          title={q.url}
                        >
                          <span>🔗</span>
                          <span>{q.source || "Nguồn bài viết"}</span>
                        </a>
                      ) : (
                        <span className="text-[10px] text-[var(--text-muted)] shrink-0 italic">
                          {q.source}
                        </span>
                      )}
                    </div>
                    <p className="text-xs font-semibold text-[var(--text-primary)] leading-relaxed">
                      {q.question}
                    </p>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );

  if (mode === "modal") {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in">
        <div className="w-full max-w-3xl">{content}</div>
      </div>
    );
  }

  return <div className="w-full my-6">{content}</div>;
}
