"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { Clock, Shield, Sparkles, AlertCircle, X, Send, Terminal } from "lucide-react";

import { AudioVisualizer } from "@/components/interview/AudioVisualizer";
import { ControlBar } from "@/components/interview/ControlBar";
import { TranscriptBox, TranscriptMessage } from "@/components/interview/TranscriptBox";
import { InterviewActivityPanel } from "@/components/interview/InterviewActivityPanel";
import { useAudioRecorder } from "@/hooks/useAudioRecorder";
import { useInterviewSocket, WSASRGatePayload, WSQuestionPayload, WSSessionStatePayload } from "@/hooks/useInterviewSocket";
import { EdgeRuntimeOrchestrator, type ASREvidence } from "@/lib/edgeRuntime";
import { technicalTermRecovery } from "@/lib/technicalTermRecovery";
import { appendAnswerSegment } from "@/lib/answerDraft";

function microphoneErrorMessage(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Chưa được cấp quyền dùng micro. Hãy cho phép micro trong quyền của trình duyệt rồi thử lại.";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "Không tìm thấy micro. Hãy kết nối micro rồi thử lại.";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "Micro đang bị ứng dụng khác sử dụng hoặc không thể khởi động.";
  }
  if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") {
    return "Micro không hỗ trợ cấu hình âm thanh hiện tại.";
  }
  return error instanceof Error ? error.message : "Không thể khởi động phần luyện nói.";
}

export default function InterviewRoomPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;

  // UI States
  const [status, setStatus] = useState<"connecting" | "ready" | "listening" | "thinking" | "speaking">("connecting");
  const [thinkingMessage, setThinkingMessage] = useState("Đang xử lý lượt phỏng vấn...");
  const [listeningMessage, setListeningMessage] = useState<string | undefined>(undefined);
  const [isRecording, setIsRecording] = useState(false);
  const [speechDetected, setSpeechDetected] = useState(false);
  const [vadAvailable, setVadAvailable] = useState(true);
  const [vadMode, setVadMode] = useState<"silero" | "energy">("energy");
  const [timeRemaining, setTimeRemaining] = useState<number>(1500);
  const [currentStageName, setCurrentStageName] = useState<string>("Khởi động & Động lực");
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [partialText, setPartialText] = useState<string>("");
  const [adaptationMode, setAdaptationMode] = useState<string>("NORMAL");

  // Modals
  const [showReverseModal, setShowReverseModal] = useState<boolean>(false);
  const [showSelfReportModal, setShowSelfReportModal] = useState<boolean>(false);
  const [showActivityModal, setShowActivityModal] = useState<boolean>(false);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [interactionError, setInteractionError] = useState<string | null>(null);
  const [questionGenerationFailed, setQuestionGenerationFailed] = useState(false);
  const [reverseQuestionInput, setReverseQuestionInput] = useState<string>("");
  const [selfReportConfidence, setSelfReportConfidence] = useState<number>(7);
  const [selfReportStress, setSelfReportStress] = useState<number>(4);

  // Edge AI Runtime ref
  const edgeRuntimeRef = useRef<EdgeRuntimeOrchestrator | null>(null);
  const pendingSpeechTextRef = useRef<{ text: string; onProgress?: (visibleText: string) => void } | null>(null);
  const autoListenAfterSpeechRef = useRef<() => void>(() => undefined);
  const autoListenPendingRef = useRef(false);
  const cancelVoiceCaptureRef = useRef<() => void>(() => undefined);
  const isRecordingRef = useRef(false);
  const microphoneStartInProgressRef = useRef(false);
  const microphoneGenerationRef = useRef(0);
  const spokenAiMessagesRef = useRef<Set<string>>(new Set());
  const submitTextRef = useRef<(text: string, verified?: boolean, evidence?: ASREvidence) => void>(() => undefined);
  const pendingTranscriptRef = useRef<Map<string, string>>(new Map());
  const pendingStreamInterruptionRef = useRef<string | null>(null);
  const answerDraftRef = useRef("");
  const speechStartedAtRef = useRef<number | null>(null);
  const speechEndTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const speechRequestStartedAtRef = useRef<number | null>(null);
  const answerProcessingStartedAtRef = useRef<number | null>(null);
  const activeSpeechTurnIdRef = useRef<string | undefined>(undefined);
  const isSubmittingRef = useRef<boolean>(false);

  // 1. Audio Recorder Hook
  const {
    audioLevel,
    frequencyData,
    startRecording,
    stopRecording,
    prepareVadWorker,
  } = useAudioRecorder({
    onFeaturesExtracted: (features) => {
      sendCommunicationFeatures(features);
    },
    onAudioChunk: (samples, sampleRate) => {
      edgeRuntimeRef.current?.sendAudioChunk(samples, sampleRate);
    },
    onSpeechStart: () => {
      if (speechEndTimerRef.current) {
        clearTimeout(speechEndTimerRef.current);
        speechEndTimerRef.current = null;
      }
      speechStartedAtRef.current = Date.now();
      edgeRuntimeRef.current?.markSpeechStarted();
      setListeningMessage(undefined);
      setSpeechDetected(true);
    },
    onSpeechEnd: () => {
      edgeRuntimeRef.current?.markSpeechEnded();
      setSpeechDetected(false);
      if (!isRecordingRef.current) return;
      setListeningMessage("Bạn có thể nói tiếp; tôi chờ thêm trước khi chốt câu trả lời...");
      setThinkingMessage("Bạn có thể nói tiếp; tôi đang chờ xem câu trả lời đã hết chưa...");
      setStatus("listening");
      if (speechEndTimerRef.current) clearTimeout(speechEndTimerRef.current);
      speechEndTimerRef.current = setTimeout(() => {
        speechEndTimerRef.current = null;
        if (!isRecordingRef.current) return;
        isRecordingRef.current = false;
        stopRecording();
        setIsRecording(false);
        setListeningMessage(undefined);
        answerProcessingStartedAtRef.current = performance.now();
        setThinkingMessage("Đang hoàn thiện bản chép lời...");
        setStatus("thinking");
        edgeRuntimeRef.current?.stopListening();
      }, 1600);
    },
    onVadReady: () => {
      setVadAvailable(true);
    },
    onVadError: (message) => {
      console.warn("[VAD] Silero chưa sẵn sàng; dùng energy VAD local:", message);
      setVadMode("energy");
      setVadAvailable(true);
    },
    onVadModeChange: (mode) => {
      setVadMode(mode);
      setVadAvailable(true);
    },
  });

  useEffect(() => {
    void prepareVadWorker();
  }, [prepareVadWorker]);

  useEffect(() => () => {
    if (speechEndTimerRef.current) clearTimeout(speechEndTimerRef.current);
  }, []);

  const STAGE_LABELS: Record<string, string> = {
    hr_motivation: "Giai đoạn 1: Khởi động & Động lực",
    cv_project_defense: "Giai đoạn 2: Bảo vệ Dự án CV (STAR)",
    technical_core: "Giai đoạn 3: Chuyên môn Lõi & Tối ưu",
    applied_scenario: "Giai đoạn 4: Tình huống Thực chiến",
    wrap_up: "Giai đoạn 5: Tổng kết & Hỏi ngược",
  };

  const playSpeech = useCallback((text: string, onProgress?: (visibleText: string) => void) => {
    const runtime = edgeRuntimeRef.current;
    if (!runtime) {
      pendingSpeechTextRef.current = { text, onProgress };
      return;
    }

    pendingSpeechTextRef.current = null;
    if (isRecordingRef.current || microphoneStartInProgressRef.current) {
      cancelVoiceCaptureRef.current();
    }
    setInteractionError(null);
    runtime.speak(
      text,
      () => {
        setStatus("ready");
        isSubmittingRef.current = false;
        autoListenAfterSpeechRef.current();
        activeSpeechTurnIdRef.current = undefined;
      },
      (reason) => {
        speechRequestStartedAtRef.current = null;
        answerProcessingStartedAtRef.current = null;
        onProgress?.(text);
        setInteractionError(reason);
        setStatus("ready");
        autoListenAfterSpeechRef.current();
      },
      onProgress,
    );
  }, []);

  // 2. WebSocket Interview Hook
  const {
    isConnected,
    sendPartialTranscript,
    sendStreamSegment,
    sendClientTiming,
    sendFinalTranscript,
    sendBargeIn,
    sendReverseQuestion,
    sendCommunicationFeatures,
    sendSelfReport,
    retryQuestionGeneration,
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
      setStatus((current) => current === "connecting" ? "ready" : current);
    },
    onAsrGateResult: (result: WSASRGatePayload, turnId?: string) => {
      if (!turnId) return;
      const messageId = pendingTranscriptRef.current.get(turnId);
      if (!messageId) return;
      pendingTranscriptRef.current.delete(turnId);
      if (result.transcript_safe) {
        setThinkingMessage("Laya đang chọn hướng hỏi tiếp từ câu trả lời của bạn...");
        return;
      }
      setMessages((prev) => prev.map((message) =>
        message.id === messageId ? { ...message, needsRepeat: true } : message
      ));
      setThinkingMessage("Nghe chưa rõ; phỏng vấn viên đang chuẩn bị hỏi lại...");
      setStatus("thinking");
    },
    onStreamDecision: (decision) => {
      const action = decision.action?.toUpperCase();
      if (action === "WAIT_FOR_CANDIDATE") {
        if (!isRecordingRef.current) return;
        // A delayed streaming decision must never cancel an endpoint already
        // detected by VAD. Otherwise the mic can wait forever for another
        // speech_end event and force the candidate to press a button.
        if (speechEndTimerRef.current) return;
        setListeningMessage("Tôi vẫn đang nghe; cứ nói tiếp khi bạn sẵn sàng.");
        setStatus("listening");
        return;
      }
      if (!decision.decision_id || !["ASK_REPEAT", "CLARIFY_NOW", "AI_SOFT_INTERRUPT"].includes(action)) return;
      if (!isRecordingRef.current || pendingStreamInterruptionRef.current) return;

      if (speechEndTimerRef.current) {
        clearTimeout(speechEndTimerRef.current);
        speechEndTimerRef.current = null;
      }

      pendingStreamInterruptionRef.current = decision.decision_id;
      microphoneGenerationRef.current += 1;
      microphoneStartInProgressRef.current = false;
      isRecordingRef.current = false;
      setSpeechDetected(false);
      setListeningMessage(undefined);
      setIsRecording(false);
      setThinkingMessage("Laya muốn hỏi rõ một ý; đang giữ câu trả lời của bạn...");
      setStatus("thinking");
      stopRecording();
      edgeRuntimeRef.current?.stopListening();
    },
    onStreamInterruption: (interruption) => {
      pendingStreamInterruptionRef.current = null;
      setPartialText("");
      setInteractionError(null);
      const messageId = `clarify_${interruption.decision_id}`;
      activeSpeechTurnIdRef.current = interruption.decision_id;
      setMessages((prev) => prev.some((message) => message.id === messageId) ? prev : [...prev, {
        id: messageId,
        role: "ai",
        text: "",
        time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        speechText: interruption.utterance,
        speechPending: true,
      }]);
      playSpeech(interruption.utterance, (visibleText) => setMessages((prev) => prev.map((message) =>
        message.id === messageId
          ? { ...message, text: visibleText, speechPending: visibleText.length === 0 }
          : message
      )));
    },
    onStreamInterruptionCancelled: (reason) => {
      pendingStreamInterruptionRef.current = null;
      setInteractionError(reason);
      setThinkingMessage("Đang mở lại micro để bạn tiếp tục câu trả lời...");
      setStatus("ready");
      autoListenAfterSpeechRef.current();
    },
    onQuestionReceived: (q: WSQuestionPayload) => {
      setQuestionGenerationFailed(false);
      setInteractionError(null);
      isSubmittingRef.current = false;
      const questionKey = q.question_id || q.question_text;
      if (spokenAiMessagesRef.current.has(questionKey) || spokenAiMessagesRef.current.has(q.question_text)) {
        isSubmittingRef.current = false;
        return;
      }
      spokenAiMessagesRef.current.add(questionKey);
      spokenAiMessagesRef.current.add(q.question_text);

      const nowStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const messageId = q.question_id || `q_${Date.now()}`;
      activeSpeechTurnIdRef.current = messageId;
      const newMsg: TranscriptMessage = {
        id: messageId,
        role: "ai",
        text: "",
        time: nowStr,
        speechText: q.question_text,
        speechPending: true,
      };
      setMessages((prev) => {
        if (prev.some((m) => m.id === newMsg.id || (m.role === "ai" && (m.speechText || m.text) === q.question_text))) {
          return prev;
        }
        return [...prev, newMsg];
      });
      // Do not depend on a side-effect inside the React state updater: React
      // may defer or replay updater functions, which previously skipped TTS.
      playSpeech(q.question_text, (visibleText) => setMessages((prev) => prev.map((message) =>
        message.id === messageId
          ? { ...message, text: visibleText, speechPending: visibleText.length === 0 }
          : message
      )));
    },
    onReverseAnswer: (ans) => {
      const nowStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const messageId = `rev_${Date.now()}`;
      activeSpeechTurnIdRef.current = messageId;
      const newMsg: TranscriptMessage = {
        id: messageId,
        role: "ai",
        text: "",
        time: nowStr,
        speechText: ans.answer,
        speechPending: true,
      };
      setMessages((prev) => [...prev, newMsg]);
      playSpeech(ans.answer, (visibleText) => setMessages((prev) => prev.map((message) =>
        message.id === messageId
          ? { ...message, text: visibleText, speechPending: visibleText.length === 0 }
          : message
      )));
    },
    onSessionEnded: () => {
      router.push(`/report/${sessionId}`);
    },
    onError: (err, details) => {
      console.warn("Interview socket error:", err);
      if (err.includes("Session not found")) {
        setSessionError("Phiên phỏng vấn đã hết hạn hoặc máy chủ đã được khởi động lại.");
      } else {
        setInteractionError(err);
        if (details?.code === "QUESTION_GENERATION_UNAVAILABLE") {
          setQuestionGenerationFailed(true);
          isSubmittingRef.current = false;
          setStatus("ready");
        }
      }
    },
  });

  const startAutoListening = useCallback(async () => {
    if (!sessionId || questionGenerationFailed) return;
    if (!isConnected) {
      autoListenPendingRef.current = true;
      return;
    }
    autoListenPendingRef.current = false;
    if (isRecordingRef.current || microphoneStartInProgressRef.current) return;

    const runtime = edgeRuntimeRef.current;
    if (!runtime) {
      setInteractionError("Bộ nhận dạng giọng nói chưa sẵn sàng. Hãy tải lại trang rồi thử lại.");
      return;
    }

    const generation = ++microphoneGenerationRef.current;
    microphoneStartInProgressRef.current = true;
    setSpeechDetected(false);
    setStatus("connecting");

    try {
      // Arm local Qwen capture before the microphone starts delivering PCM.
      await runtime.startListening();
      if (generation !== microphoneGenerationRef.current) {
        runtime.cancelListening();
        return;
      }

      await startRecording();
      if (generation !== microphoneGenerationRef.current) {
        stopRecording();
        runtime.cancelListening();
        return;
      }

      isRecordingRef.current = true;
      setIsRecording(true);
      setStatus("listening");
    } catch (error) {
      if (generation !== microphoneGenerationRef.current) return;
      runtime.cancelListening();
      stopRecording();
      isRecordingRef.current = false;
      setIsRecording(false);
      setStatus("ready");
      setInteractionError(microphoneErrorMessage(error));
    } finally {
      if (generation === microphoneGenerationRef.current) {
        microphoneStartInProgressRef.current = false;
      }
    }
  }, [sessionId, isConnected, questionGenerationFailed, startRecording, stopRecording]);

  useEffect(() => {
    autoListenAfterSpeechRef.current = () => {
      void startAutoListening();
    };
  }, [startAutoListening]);

  useEffect(() => {
    if (isConnected && autoListenPendingRef.current) {
      autoListenAfterSpeechRef.current();
    }
  }, [isConnected]);

  const cancelVoiceCapture = useCallback(() => {
    if (!isRecordingRef.current && !microphoneStartInProgressRef.current) return;
    microphoneGenerationRef.current += 1;
    microphoneStartInProgressRef.current = false;
    const wasRecording = isRecordingRef.current;
    isRecordingRef.current = false;
    setSpeechDetected(false);
    setIsRecording(false);
    if (wasRecording) stopRecording();
    edgeRuntimeRef.current?.cancelListening();
  }, [stopRecording]);

  useEffect(() => {
    cancelVoiceCaptureRef.current = cancelVoiceCapture;
  }, [cancelVoiceCapture]);

  // 3. Initialize Edge Runtime Orchestrator
  useEffect(() => {
    const runtime = new EdgeRuntimeOrchestrator({
      sessionId,
      onPartialTranscript: (text, audioQualityOk, latencyMs) => {
        setPartialText(text);
        const startedAt = speechStartedAtRef.current;
        if (startedAt !== null) sendClientTiming("speech_to_partial_text", Date.now() - startedAt);
        sendPartialTranscript(text, {
          duration_sec: startedAt ? Math.max(0, (Date.now() - startedAt) / 1000) : 0,
          audio_quality_ok: audioQualityOk,
          asr_latency_ms: Math.round(latencyMs),
          source: "qwen_partial",
        });
      },
      onFinalTranscript: (text, _terms, evidence) => {
        const speechEndedAt = answerProcessingStartedAtRef.current;
        if (speechEndedAt !== null) sendClientTiming("speech_end_to_final_text", performance.now() - speechEndedAt);
        speechStartedAtRef.current = null;
        if (text && text.trim()) {
          setSpeechDetected(false);
          setListeningMessage(undefined);
          isRecordingRef.current = false;
          edgeRuntimeRef.current?.cancelListening();
          stopRecording();
          setIsRecording(false);
          const decisionId = pendingStreamInterruptionRef.current;
          if (decisionId) {
            pendingStreamInterruptionRef.current = null;
            answerDraftRef.current = appendAnswerSegment(answerDraftRef.current, text);
            sendStreamSegment(text, decisionId);
            setPartialText("");
          } else {
            submitTextRef.current(text, false, evidence);
          }
        }
      },
      onUnclearAudio: (evidence) => {
        setPartialText("");
        setThinkingMessage("Chưa nghe rõ; phỏng vấn viên sẽ tự hỏi lại...");
        setStatus("thinking");
        sendFinalTranscript("", [], `unclear_${Date.now()}`, false, evidence);
      },
      onBargeIn: () => {
        sendBargeIn();
      },
      onStateChange: (state) => {
        if (state === "PREPARING_TTS") {
          speechRequestStartedAtRef.current = performance.now();
          setThinkingMessage("Đang chuẩn bị giọng nói...");
          setStatus("thinking");
        }
        else if (state === "SPEAKING") {
          const requestStartedAt = speechRequestStartedAtRef.current;
          if (requestStartedAt !== null) {
            sendClientTiming("first_audio_started", performance.now() - requestStartedAt, activeSpeechTurnIdRef.current);
            speechRequestStartedAtRef.current = null;
          }
          const answerStartedAt = answerProcessingStartedAtRef.current;
          if (answerStartedAt !== null) {
            sendClientTiming("answer_to_first_audio", performance.now() - answerStartedAt, activeSpeechTurnIdRef.current);
            answerProcessingStartedAtRef.current = null;
          }
          setStatus("speaking");
        }
        else if (state === "LISTENING") setStatus(isRecordingRef.current ? "listening" : "connecting");
        else if (state === "THINKING") setStatus("thinking");
      },
      onError: (error) => {
        if (speechEndTimerRef.current) {
          clearTimeout(speechEndTimerRef.current);
          speechEndTimerRef.current = null;
        }
        setInteractionError(error);
        setListeningMessage(undefined);
        const decisionId = pendingStreamInterruptionRef.current;
        if (decisionId) {
          pendingStreamInterruptionRef.current = null;
          sendStreamSegment("", decisionId);
          return;
        }
        edgeRuntimeRef.current?.stopListening();
        isRecordingRef.current = false;
        setSpeechDetected(false);
        stopRecording();
        setIsRecording(false);
        setStatus("ready");
      },
    });

    const initialization = runtime.init();
    edgeRuntimeRef.current = runtime;
    void initialization.then(() => {
      if (edgeRuntimeRef.current !== runtime) return;
      const pendingSpeech = pendingSpeechTextRef.current;
      if (pendingSpeech) playSpeech(pendingSpeech.text, pendingSpeech.onProgress);
    });

    return () => {
      runtime.destroy();
      if (edgeRuntimeRef.current === runtime) edgeRuntimeRef.current = null;
      pendingSpeechTextRef.current = null;
    };
  }, [playSpeech, sendPartialTranscript, sendStreamSegment, sendFinalTranscript, sendClientTiming, sendBargeIn, stopRecording, sessionId]);

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
  const handleSubmitText = useCallback((text: string, verified = true, evidence?: ASREvidence) => {
    const cleanText = text.trim();
    if (!cleanText || isSubmittingRef.current) return;
    if (questionGenerationFailed) {
      setInteractionError("Hãy sinh lại câu hỏi trước khi gửi câu trả lời. Lượt trước đã được lưu; không cần gửi lại.");
      return;
    }
    if (!isConnected) {
      setInteractionError("Mất kết nối với máy chủ phỏng vấn. Hãy đợi WebSocket kết nối lại trước khi gửi câu trả lời.");
      return;
    }
    const completeAnswer = appendAnswerSegment(answerDraftRef.current, cleanText);
    answerDraftRef.current = "";
    cancelVoiceCapture();
    isSubmittingRef.current = true;
    setPartialText("");
    const nowStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const recovery = technicalTermRecovery.recover(completeAnswer);
    const turnId = `turn_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const messageId = `cand_${turnId}`;
    // Every submitted turn owns a distinct candidate bubble, including a
    // repeated answer, so the ASR gate can attach confirmation to this ID.
    pendingTranscriptRef.current.set(turnId, messageId);

    setMessages((prev) => {
      const newMsg: TranscriptMessage = {
        id: messageId,
        role: "candidate",
        text: recovery.recoveredText,
        time: nowStr,
        termCandidates: recovery.candidates.map((candidate) => candidate.recovered),
      };
      return [...prev, newMsg];
    });

    if (answerProcessingStartedAtRef.current === null) answerProcessingStartedAtRef.current = performance.now();
    sendFinalTranscript(recovery.recoveredText, recovery.candidates, turnId, verified, evidence);
    setThinkingMessage("Đang chuyển câu trả lời cho Laya xử lý...");
    setStatus("thinking");

    // Tự động mở khóa sau 2.5s nếu server chưa phản hồi kịp
    setTimeout(() => {
      isSubmittingRef.current = false;
    }, 2500);
  }, [isConnected, sendFinalTranscript, questionGenerationFailed, cancelVoiceCapture]);

  useEffect(() => {
    submitTextRef.current = handleSubmitText;
  }, [handleSubmitText]);

  // Barge-In
  const handleBargeIn = useCallback(() => {
    edgeRuntimeRef.current?.handleBargeIn();
    autoListenAfterSpeechRef.current();
  }, []);

  // End Session
  const handleEndSession = useCallback(async () => {
    setThinkingMessage("Phiên đã kết thúc; đang chấm rubric toàn bộ câu trả lời...");
    setStatus("thinking");
    edgeRuntimeRef.current?.stopTTS();
    try {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      await fetch(`${apiUrl}/api/v1/sessions/${sessionId}/end`, { method: "POST" });
    } catch (e) {
      console.warn("Failed to end session gracefully:", e);
    }
    router.push(`/report/${sessionId}`);
  }, [sessionId, router]);

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
            onClick={() => setShowActivityModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-[var(--coc-primary)]/30 bg-[var(--coc-primary)]/10 text-[var(--coc-primary)] text-xs font-semibold hover:bg-[var(--coc-primary)]/20 transition-all cursor-pointer shadow-sm"
          >
            <Terminal className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Log phỏng vấn</span>
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
            vadMode={vadMode}
            thinkingMessage={questionGenerationFailed ? "Đang thử sinh lại câu hỏi theo CV/JD/framework..." : thinkingMessage}
            listeningMessage={listeningMessage}
            speechDetected={speechDetected}
            audioLevel={audioLevel}
            frequencyData={frequencyData}
          />
        </div>

        {/* Live Conversation Transcript Panel */}
        <TranscriptBox
          messages={messages}
          currentPartialText={partialText}
        onSpeak={playSpeech}
        />
      </div>

      {/* Bottom Control Bar */}
      <ControlBar
        isRecording={isRecording}
        vadAvailable={vadAvailable}
        isConnected={isConnected}
        status={status}
        onBargeIn={handleBargeIn}
        onEndSession={handleEndSession}
        onOpenReverseModal={() => setShowReverseModal(true)}
        onOpenSelfReportModal={() => setShowSelfReportModal(true)}
        onSubmitText={(text) => handleSubmitText(text, true)}
        onSubmitDemoAnswer={(text) => handleSubmitText(text, true)}
      />

      {(interactionError || questionGenerationFailed) && (
        <div role="alert" className="fixed bottom-28 left-1/2 z-40 -translate-x-1/2 w-[min(92vw,42rem)] rounded-xl border border-rose-500/40 bg-rose-950/95 px-4 py-3 text-sm text-rose-100 shadow-2xl">
          <div className="flex items-start justify-between gap-3">
            <span>{interactionError || "Model chưa sinh được câu hỏi theo framework."}</span>
            {questionGenerationFailed ? (
              <button type="button" disabled={!isConnected || status === "thinking"} onClick={() => {
                if (retryQuestionGeneration()) setStatus("thinking");
              }} className="shrink-0 rounded-lg px-2 py-1 border border-rose-300/40 disabled:opacity-50">
                {status === "thinking" ? "Đang sinh lại câu hỏi…" : "Thử sinh lại"}
              </button>
            ) : <button type="button" aria-label="Đóng thông báo" onClick={() => setInteractionError(null)} className="shrink-0 text-rose-200 hover:text-white">×</button>}
          </div>
        </div>
      )}

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

      {/* Read-only logs for this interview; opening the panel never crawls the web. */}
      {showActivityModal && (
        <InterviewActivityPanel
          sessionId={sessionId}
          onClose={() => setShowActivityModal(false)}
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
