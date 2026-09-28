"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { Clock, Shield, Sparkles, AlertCircle, X, Send, Terminal } from "lucide-react";

import { AudioVisualizer } from "@/components/interview/AudioVisualizer";
import { ControlBar } from "@/components/interview/ControlBar";
import { TranscriptBox, TranscriptMessage } from "@/components/interview/TranscriptBox";
import { OrchestratorConsole } from "@/components/interview/OrchestratorConsole";
import { useAudioRecorder } from "@/hooks/useAudioRecorder";
import { useInterviewSocket, WSQuestionPayload, WSSessionStatePayload } from "@/hooks/useInterviewSocket";
import { EdgeRuntimeOrchestrator } from "@/lib/edgeRuntime";
import { technicalTermRecovery } from "@/lib/technicalTermRecovery";

export default function InterviewRoomPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;

  // UI States
  const [status, setStatus] = useState<"connecting" | "ready" | "listening" | "thinking" | "speaking">("connecting");
  const [timeRemaining, setTimeRemaining] = useState<number>(1500);
  const [currentStageName, setCurrentStageName] = useState<string>("Khởi động & Động lực");
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [partialText, setPartialText] = useState<string>("");
  const [adaptationMode, setAdaptationMode] = useState<string>("NORMAL");

  // Modals
  const [showReverseModal, setShowReverseModal] = useState<boolean>(false);
  const [showSelfReportModal, setShowSelfReportModal] = useState<boolean>(false);
  const [showOrchestratorModal, setShowOrchestratorModal] = useState<boolean>(false);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [reverseQuestionInput, setReverseQuestionInput] = useState<string>("");
  const [selfReportConfidence, setSelfReportConfidence] = useState<number>(7);
  const [selfReportStress, setSelfReportStress] = useState<number>(4);

  // Edge AI Runtime ref
  const edgeRuntimeRef = useRef<EdgeRuntimeOrchestrator | null>(null);
  const isSubmittingRef = useRef<boolean>(false);

  // 1. Audio Recorder Hook
  const {
    isRecording,
    audioLevel,
    frequencyData,
    startRecording,
    stopRecording,
  } = useAudioRecorder({
    onAudioData: (pcm) => {
      // Forward PCM to VAD / Whisper if needed
    },
    onFeaturesExtracted: (features) => {
      sendCommunicationFeatures(features);
    },
  });

  const STAGE_LABELS: Record<string, string> = {
    hr_motivation: "Giai đoạn 1: Khởi động & Động lực",
    cv_project_defense: "Giai đoạn 2: Bảo vệ Dự án CV (STAR)",
    technical_core: "Giai đoạn 3: Chuyên môn Lõi & Tối ưu",
    applied_scenario: "Giai đoạn 4: Tình huống Thực chiến",
    wrap_up: "Giai đoạn 5: Tổng kết & Hỏi ngược",
  };

  // 2. WebSocket Interview Hook
  const {
    isConnected,
    sendPartialTranscript,
    sendFinalTranscript,
    sendBargeIn,
    sendConfirmedTranscript,
    sendReverseQuestion,
    sendCommunicationFeatures,
    sendSelfReport,
  } = useInterviewSocket({
    sessionId,
    onStateSync: (state: WSSessionStatePayload) => {
      if (state.time_remaining_sec !== undefined) {
        setTimeRemaining(state.time_remaining_sec);
      }
      if (state.current_topic) {
        setCurrentStageName(STAGE_LABELS[state.current_topic] || state.current_topic);
      }
      if (state.adaptation_mode) {
        setAdaptationMode(state.adaptation_mode);
      }
      setStatus("ready");
    },
    onQuestionReceived: (q: WSQuestionPayload) => {
      const nowStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const newMsg: TranscriptMessage = {
        id: q.question_id || `q_${Date.now()}`,
        role: "ai",
        text: q.question_text,
        time: nowStr,
      };
      let shouldSpeak = false;
      setMessages((prev) => {
        if (prev.some((m) => m.id === newMsg.id || (m.role === "ai" && m.text === newMsg.text))) {
          return prev;
        }
        shouldSpeak = true;
        return [...prev, newMsg];
      });

      if (shouldSpeak) {
        setStatus("speaking");
        // Speak using Edge Runtime / TTS
        edgeRuntimeRef.current?.speak(q.question_text, () => {
          setStatus("ready");
          isSubmittingRef.current = false;
        });
      } else {
        isSubmittingRef.current = false;
      }
    },
    onReverseAnswer: (ans) => {
      const nowStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const newMsg: TranscriptMessage = {
        id: `rev_${Date.now()}`,
        role: "ai",
        text: ans.answer,
        time: nowStr,
      };
      setMessages((prev) => [...prev, newMsg]);
      setStatus("speaking");
      edgeRuntimeRef.current?.speak(ans.answer, () => {
        setStatus("ready");
        isSubmittingRef.current = false;
      });
    },
    onSessionEnded: () => {
      router.push(`/report/${sessionId}`);
    },
    onError: (err) => {
      console.warn("Interview socket error:", err);
      if (err.includes("Session not found")) {
        setSessionError("Phiên phỏng vấn đã hết hạn hoặc máy chủ đã được khởi động lại.");
      }
    },
  });

  // 3. Initialize Edge Runtime Orchestrator
  useEffect(() => {
    const runtime = new EdgeRuntimeOrchestrator({
      onPartialTranscript: (text) => {
        setPartialText(text);
        sendPartialTranscript(text);
      },
      onFinalTranscript: (text, termCandidates) => {
        if (text && text.trim()) {
          stopRecording();
          handleSubmitText(text);
        }
      },
      onBargeIn: () => {
        sendBargeIn();
      },
      onStateChange: (state) => {
        if (state === "SPEAKING") setStatus("speaking");
        else if (state === "LISTENING") setStatus("listening");
        else if (state === "THINKING") setStatus("thinking");
      },
    });

    runtime.init();
    edgeRuntimeRef.current = runtime;

    return () => {
      runtime.destroy();
    };
  }, [sendPartialTranscript, sendFinalTranscript, sendBargeIn, stopRecording]);

  // Timer countdown
  useEffect(() => {
    if (!isConnected) return;
    const interval = setInterval(() => {
      setTimeRemaining((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(interval);
  }, [isConnected]);

  // Format MM:SS
  const formatTime = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // Submit candidate answer (via typed text or flushed voice)
  const handleSubmitText = useCallback((text: string) => {
    const cleanText = text.trim();
    if (!cleanText || isSubmittingRef.current) return;
    isSubmittingRef.current = true;
    setPartialText("");
    const nowStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const recovery = technicalTermRecovery.recover(cleanText);

    setMessages((prev) => {
      const lastMsg = prev[prev.length - 1];
      if (lastMsg && lastMsg.role === "candidate" && lastMsg.text === recovery.recoveredText) {
        return prev;
      }
      const newMsg: TranscriptMessage = {
        id: `cand_${Date.now()}`,
        role: "candidate",
        text: recovery.recoveredText,
        time: nowStr,
        termCandidates: recovery.candidates.map((c: any) => c.recovered),
      };
      return [...prev, newMsg];
    });

    sendFinalTranscript(recovery.recoveredText, recovery.candidates);
    setStatus("thinking");

    // Tự động mở khóa sau 2.5s nếu server chưa phản hồi kịp
    setTimeout(() => {
      isSubmittingRef.current = false;
    }, 2500);
  }, [sendFinalTranscript]);

  // Toggle Mic
  const handleToggleMic = useCallback(async () => {
    if (isRecording) {
      stopRecording();
      const flushed = edgeRuntimeRef.current?.stopListening();
      if (flushed && flushed.trim()) {
        handleSubmitText(flushed);
      } else {
        setStatus("ready");
      }
    } else {
      try {
        await startRecording();
        await edgeRuntimeRef.current?.startListening();
        setStatus("listening");
      } catch (e) {
        console.error("Failed to start mic:", e);
      }
    }
  }, [isRecording, startRecording, stopRecording, handleSubmitText]);

  // Barge-In
  const handleBargeIn = useCallback(() => {
    edgeRuntimeRef.current?.handleBargeIn();
    sendBargeIn();
    handleToggleMic();
  }, [handleToggleMic, sendBargeIn]);

  // End Session
  const handleEndSession = useCallback(async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      await fetch(`${apiUrl}/api/v1/sessions/${sessionId}/end`, { method: "POST" });
    } catch (e) {
      console.warn("Failed to end session gracefully:", e);
    }
    router.push(`/report/${sessionId}`);
  }, [sessionId, router]);

  // Confirm Transcript Fallback
  const handleConfirmTranscript = (messageId: string, confirmedText: string) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, text: confirmedText, needsConfirmation: false } : m))
    );
    sendConfirmedTranscript(confirmedText);
  };

  // Submit Reverse Question
  const handleSendReverseQuestion = () => {
    if (!reverseQuestionInput.trim()) return;
    const nowStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    setMessages((prev) => [
      ...prev,
      {
        id: `rev_q_${Date.now()}`,
        role: "candidate",
        text: `[Hỏi ngược DN]: ${reverseQuestionInput}`,
        time: nowStr,
      },
    ]);
    sendReverseQuestion(reverseQuestionInput);
    setReverseQuestionInput("");
    setShowReverseModal(false);
    setStatus("thinking");
  };

  // Submit Self-Report
  const handleSendSelfReport = () => {
    sendSelfReport({
      confidence_level: selfReportConfidence,
      stress_level: selfReportStress,
      timestamp: Date.now(),
    });
    setShowSelfReportModal(false);
  };

  return (
    <div className="h-[calc(100vh-4rem)] flex flex-col bg-[var(--bg-primary)] select-none">
      {/* Top Header Bar */}
      <div className="flex items-center justify-between px-4 sm:px-6 py-3 border-b border-[var(--border-color)] bg-[var(--glass-bg)] backdrop-blur-lg">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div
              className={`w-2.5 h-2.5 rounded-full ${
                isConnected ? "bg-emerald-500 animate-pulse" : "bg-amber-500 animate-ping"
              }`}
            />
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              {isConnected ? currentStageName : "Đang kết nối WebSocket..."}
            </span>
          </div>

          {adaptationMode !== "NORMAL" && (
            <span className="hidden sm:inline-flex items-center gap-1 text-[11px] font-semibold text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-md border border-amber-500/20">
              <Shield className="w-3 h-3" />
              <span>Chế độ: {adaptationMode}</span>
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowOrchestratorModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-[var(--coc-primary)]/30 bg-[var(--coc-primary)]/10 text-[var(--coc-primary)] text-xs font-semibold hover:bg-[var(--coc-primary)]/20 transition-all cursor-pointer shadow-sm"
          >
            <Terminal className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Orchestrator Tool Logs</span>
            <span className="sm:hidden">Logs</span>
          </button>

          <div
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border ${
              timeRemaining < 180
                ? "bg-red-500/10 border-red-500/30 text-red-400 animate-pulse"
                : "bg-[var(--bg-secondary)] border-[var(--border-color)] text-[var(--text-secondary)]"
            }`}
          >
            <Clock className="w-4 h-4" />
            <span className="font-mono text-sm font-bold">{formatTime(timeRemaining)}</span>
          </div>
        </div>
      </div>

      {/* Main Viewport */}
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden relative">
        {/* Visualizer & Orb */}
        <div className="flex-1 flex flex-col items-center justify-center p-4 sm:p-8 overflow-y-auto">
          <AudioVisualizer
            status={status}
            audioLevel={audioLevel}
            frequencyData={frequencyData}
          />
        </div>

        {/* Live Conversation Transcript Panel */}
        <TranscriptBox
          messages={messages}
          currentPartialText={partialText}
          onConfirmTranscript={handleConfirmTranscript}
        />
      </div>

      {/* Bottom Control Bar */}
      <ControlBar
        isRecording={isRecording}
        isSpeaking={status === "speaking"}
        status={status}
        onToggleMic={handleToggleMic}
        onBargeIn={handleBargeIn}
        onEndSession={handleEndSession}
        onOpenReverseModal={() => setShowReverseModal(true)}
        onOpenSelfReportModal={() => setShowSelfReportModal(true)}
        onSubmitText={handleSubmitText}
      />

      {/* Reverse Interview Modal (§11.4) */}
      {showReverseModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-3xl p-6 w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-[var(--border-color)] mb-4">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-[var(--coc-accent)]" />
                <h3 className="text-base font-bold text-[var(--text-primary)]">
                  Đặt câu hỏi ngược cho Doanh nghiệp (§11.4)
                </h3>
              </div>
              <button
                onClick={() => setShowReverseModal(false)}
                className="text-[var(--text-muted)] hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-3">
              Bạn có thể đặt câu hỏi về văn hóa, công nghệ hoặc lộ trình phát triển. Câu hỏi này sẽ được trả lời dựa trên tri thức doanh nghiệp thực tế.
            </p>
            <textarea
              value={reverseQuestionInput}
              onChange={(e) => setReverseQuestionInput(e.target.value)}
              placeholder="Ví dụ: Công ty hiện đang áp dụng quy trình CI/CD và kiến trúc microservices như thế nào trong dự án thực tế?"
              rows={4}
              className="w-full p-3 text-sm rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--coc-primary)] mb-4"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowReverseModal(false)}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-[var(--bg-secondary)] text-[var(--text-secondary)]"
              >
                Hủy
              </button>
              <button
                onClick={handleSendReverseQuestion}
                disabled={!reverseQuestionInput.trim()}
                className="px-5 py-2 text-xs font-semibold rounded-xl bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] text-white flex items-center gap-1.5 shadow-md disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" />
                <span>Gửi câu hỏi</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Self-Report Modal (§12.1.4) */}
      {showSelfReportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-3xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-[var(--border-color)] mb-4">
              <h3 className="text-base font-bold text-[var(--text-primary)]">
                Tự Đánh Giá Trạng Thái Tâm Lý (§12.1.4)
              </h3>
              <button
                onClick={() => setShowSelfReportModal(false)}
                className="text-[var(--text-muted)] hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-4">
              Dữ liệu tự báo cáo giúp hệ thống đánh giá hành vi giao tiếp & tư vấn cải thiện sau phỏng vấn (không trừ điểm chuyên môn).
            </p>

            <div className="space-y-4 mb-6">
              <div>
                <div className="flex justify-between text-xs font-semibold text-[var(--text-secondary)] mb-1">
                  <span>Mức độ tự tin lúc này:</span>
                  <span className="text-[var(--coc-primary)] font-mono">{selfReportConfidence}/10</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={selfReportConfidence}
                  onChange={(e) => setSelfReportConfidence(parseInt(e.target.value))}
                  className="w-full accent-[var(--coc-primary)]"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs font-semibold text-[var(--text-secondary)] mb-1">
                  <span>Mức độ căng thẳng / áp lực:</span>
                  <span className="text-amber-400 font-mono">{selfReportStress}/10</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={selfReportStress}
                  onChange={(e) => setSelfReportStress(parseInt(e.target.value))}
                  className="w-full accent-amber-500"
                />
              </div>
            </div>

            <button
              onClick={handleSendSelfReport}
              className="w-full py-2.5 rounded-xl bg-gradient-to-r from-[var(--coc-primary)] to-[var(--coc-accent)] text-white text-xs font-bold shadow-md"
            >
              Lưu trạng thái & Tiếp tục
            </button>
          </div>
        </div>
      )}

      {/* Orchestrator Tool Execution Modal */}
      {showOrchestratorModal && (
        <OrchestratorConsole
          company="FPT Software"
          role="Java Backend Intern"
          mode="modal"
          isOpen={showOrchestratorModal}
          onClose={() => setShowOrchestratorModal(false)}
        />
      )}

      {/* Session Expired / Server Reloaded Modal */}
      {sessionError && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in duration-200">
          <div className="glass-card max-w-md w-full p-6 text-center space-y-4 border-amber-500/30 rounded-3xl">
            <div className="w-12 h-12 rounded-full bg-amber-500/15 text-amber-400 flex items-center justify-center mx-auto">
              <AlertCircle className="w-6 h-6" />
            </div>
            <h3 className="text-base font-bold text-[var(--text-primary)]">
              Thông Báo Phiên Phỏng Vấn
            </h3>
            <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
              {sessionError} Bạn vui lòng quay lại trang thiết lập để bắt đầu một phiên luyện tập mới.
            </p>
            <button
              onClick={() => router.push("/interview")}
              className="btn-primary w-full py-2.5 text-xs font-bold rounded-xl"
            >
              Tạo phiên phỏng vấn mới
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
