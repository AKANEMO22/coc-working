"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { TermCandidate } from "@/lib/technicalTermRecovery";
import type { ASREvidence } from "@/lib/edgeRuntime";

export interface WSQuestionPayload {
  question_id: string;
  question_text: string;
  target_rubric?: string;
  stage_name?: string;
  expected_concepts?: string[];
}

export interface WSSessionStatePayload {
  session_id: string;
  status: string;
  current_topic?: string;
  current_concept?: string;
  time_remaining_sec: number;
  remaining_scored_question_budget: number;
  interruption_count?: number;
  adaptation_mode?: string;
}

export interface WSASRGatePayload {
  transcript_safe: boolean;
  asr_gate_action: string;
  asr_confidence: number;
}

export interface WSStreamDecisionPayload {
  action: string;
  decision_id?: string;
  confidence: number;
}

export interface WSStreamInterruptionPayload {
  decision_id: string;
  action: string;
  utterance: string;
}

interface UseInterviewSocketOptions {
  sessionId: string;
  onStateSync?: (state: WSSessionStatePayload) => void;
  onAsrGateResult?: (result: WSASRGatePayload, turnId?: string) => void;
  onStreamDecision?: (decision: WSStreamDecisionPayload) => void;
  onStreamInterruption?: (interruption: WSStreamInterruptionPayload) => void;
  onStreamInterruptionCancelled?: (reason: string) => void;
  onQuestionReceived?: (question: WSQuestionPayload) => void;
  onReverseAnswer?: (answer: { answer: string; references?: string[] }) => void;
  onSessionEnded?: (payload: { status: string; reason: string }) => void;
  onError?: (error: string, details?: { code?: string; retryable?: boolean }) => void;
}

export function useInterviewSocket({
  sessionId,
  onStateSync,
  onAsrGateResult,
  onStreamDecision,
  onStreamInterruption,
  onStreamInterruptionCancelled,
  onQuestionReceived,
  onReverseAnswer,
  onSessionEnded,
  onError,
}: UseInterviewSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const connectRef = useRef<(() => void) | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const shouldReconnectRef = useRef(true);

  const callbacksRef = useRef({
    onStateSync,
    onAsrGateResult,
    onStreamDecision,
    onStreamInterruption,
    onStreamInterruptionCancelled,
    onQuestionReceived,
    onReverseAnswer,
    onSessionEnded,
    onError,
  });

  useEffect(() => {
    callbacksRef.current = {
      onStateSync,
      onAsrGateResult,
      onStreamDecision,
      onStreamInterruption,
      onStreamInterruptionCancelled,
      onQuestionReceived,
      onReverseAnswer,
      onSessionEnded,
      onError,
    };
  });

  const getWsUrl = useCallback(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    const wsUrl = apiUrl.replace(/^http/, "ws");
    return `${wsUrl}/ws/interview/${sessionId}`;
  }, [sessionId]);

  const connect = useCallback(() => {
    if (!sessionId) return;
    if (
      socketRef.current?.readyState === WebSocket.OPEN ||
      socketRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    try {
      const url = getWsUrl();
      const ws = new WebSocket(url);
      socketRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setIsReconnecting(false);
        console.log(`WebSocket connected: ${sessionId}`);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const type = data.type;
          const payload = data.payload;

          switch (type) {
            case "state_sync":
              callbacksRef.current.onStateSync?.(payload);
              break;

            case "asr_gate_result":
              callbacksRef.current.onAsrGateResult?.(payload, data.turn_id);
              break;

            case "stream_decision":
              callbacksRef.current.onStreamDecision?.(payload);
              break;

            case "stream_interruption":
              callbacksRef.current.onStreamInterruption?.(payload);
              break;

            case "stream_interruption_cancelled":
              callbacksRef.current.onStreamInterruptionCancelled?.(payload?.reason || "Không thể hỏi làm rõ lúc này.");
              break;

            case "question_text":
              callbacksRef.current.onQuestionReceived?.(payload);
              break;

            case "reverse_answer":
              callbacksRef.current.onReverseAnswer?.(payload);
              break;

            case "session_ended":
              callbacksRef.current.onSessionEnded?.(payload);
              break;

            case "error":
              if (payload?.message?.includes("Session not found")) {
                shouldReconnectRef.current = false;
                setIsReconnecting(false);
              }
              callbacksRef.current.onError?.(payload?.message || "Lỗi WebSocket từ server", payload);
              break;

            default:
              console.log("Unhandled WS message:", type, payload);
          }
        } catch (e) {
          console.warn("Failed to parse WebSocket message:", e);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        console.log("WebSocket closed:", event.code, event.reason);

        if (shouldReconnectRef.current && event.code !== 1000) {
          setIsReconnecting(true);
          if (!reconnectTimeoutRef.current) {
            reconnectTimeoutRef.current = setTimeout(() => {
              reconnectTimeoutRef.current = null;
              connectRef.current?.();
            }, 3000);
          }
        }
      };

      ws.onerror = () => {
        // Handled via onclose and error messages
      };
    } catch (e: unknown) {
      console.error("WebSocket connection failure:", e);
      callbacksRef.current.onError?.(e instanceof Error ? e.message : "Không thể kết nối đến máy chủ WebSocket");
    }
  }, [sessionId, getWsUrl]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    if (!sessionId) return;
    shouldReconnectRef.current = true;
    connect();

    return () => {
      shouldReconnectRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (socketRef.current) {
        socketRef.current.close(1000, "Component unmounted");
        socketRef.current = null;
      }
    };
  }, [sessionId, connect]);

  // Send helpers matching backend interview_turn_ws.py message types
  const sendPartialTranscript = useCallback((text: string, features?: unknown) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "partial_transcript",
          payload: { text, features },
        })
      );
    }
  }, []);

  const sendStreamSegment = useCallback((text: string, decisionId: string) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({
        type: "stream_segment",
        payload: { text, decision_id: decisionId },
      }));
    }
  }, []);

  const sendClientTiming = useCallback((phase: "first_audio_started" | "answer_to_first_audio" | "speech_to_partial_text" | "speech_end_to_final_text", latencyMs: number, turnId?: string) => {
    if (socketRef.current?.readyState === WebSocket.OPEN && Number.isFinite(latencyMs) && latencyMs >= 0) {
      socketRef.current.send(JSON.stringify({
        type: "client_timing",
        payload: { phase, latency_ms: Math.round(latencyMs), ...(turnId ? { turn_id: turnId } : {}) },
      }));
    }
  }, []);

  const sendFinalTranscript = useCallback((text: string, termCandidates?: TermCandidate[], turnId?: string, verified = false, asrEvidence?: ASREvidence) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "final_transcript",
          payload: { text, term_candidates: termCandidates || [], verified,
            ...(turnId ? { turn_id: turnId } : {}),
            ...(asrEvidence ? { asr_evidence: asrEvidence } : {}) },
        })
      );
    }
  }, []);

  const sendBargeIn = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "user_barge_in",
          payload: { timestamp: Date.now() },
        })
      );
    }
  }, []);

  const sendConfirmedTranscript = useCallback((text: string) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "user_confirmed_transcript",
          payload: { text },
        })
      );
    }
  }, []);

  const sendReverseQuestion = useCallback((question: string, companyKnowledge?: unknown) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "reverse_question",
          payload: { question, company_knowledge: companyKnowledge },
        })
      );
    }
  }, []);

  const sendCommunicationFeatures = useCallback((features: unknown) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "communication_features",
          payload: features,
        })
      );
    }
  }, []);

  const sendSelfReport = useCallback((reportData: unknown) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "self_report",
          payload: reportData,
        })
      );
    }
  }, []);

  const retryQuestionGeneration = useCallback(() => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return false;
    socketRef.current.send(JSON.stringify({ type: "reconnect", payload: { retry_question: true } }));
    return true;
  }, []);

  return {
    isConnected,
    isReconnecting,
    sendPartialTranscript,
    sendStreamSegment,
    sendClientTiming,
    sendFinalTranscript,
    sendBargeIn,
    sendConfirmedTranscript,
    sendReverseQuestion,
    sendCommunicationFeatures,
    sendSelfReport,
    retryQuestionGeneration,
  };
}
