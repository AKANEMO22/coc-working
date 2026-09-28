"use client";

import { useEffect, useRef, useState, useCallback } from "react";

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

interface UseInterviewSocketOptions {
  sessionId: string;
  onStateSync?: (state: WSSessionStatePayload) => void;
  onQuestionReceived?: (question: WSQuestionPayload) => void;
  onReverseAnswer?: (answer: { answer: string; references?: string[] }) => void;
  onSessionEnded?: (payload: { status: string; reason: string }) => void;
  onError?: (error: string) => void;
}

export function useInterviewSocket({
  sessionId,
  onStateSync,
  onQuestionReceived,
  onReverseAnswer,
  onSessionEnded,
  onError,
}: UseInterviewSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const shouldReconnectRef = useRef(true);

  const callbacksRef = useRef({
    onStateSync,
    onQuestionReceived,
    onReverseAnswer,
    onSessionEnded,
    onError,
  });

  useEffect(() => {
    callbacksRef.current = {
      onStateSync,
      onQuestionReceived,
      onReverseAnswer,
      onSessionEnded,
      onError,
    };
  });

  const getWsUrl = useCallback(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
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
              callbacksRef.current.onError?.(payload?.message || "Lỗi WebSocket từ server");
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
              connect();
            }, 3000);
          }
        }
      };

      ws.onerror = () => {
        // Handled via onclose and error messages
      };
    } catch (e: any) {
      console.error("WebSocket connection failure:", e);
      callbacksRef.current.onError?.(e.message || "Không thể kết nối đến máy chủ WebSocket");
    }
  }, [sessionId, getWsUrl]);

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
  const sendPartialTranscript = useCallback((text: string, features?: any) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "partial_transcript",
          payload: { text, features },
        })
      );
    }
  }, []);

  const sendFinalTranscript = useCallback((text: string, termCandidates?: any[]) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "final_transcript",
          payload: { text, term_candidates: termCandidates || [] },
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

  const sendReverseQuestion = useCallback((question: string, companyKnowledge?: any) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "reverse_question",
          payload: { question, company_knowledge: companyKnowledge },
        })
      );
    }
  }, []);

  const sendCommunicationFeatures = useCallback((features: any) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "communication_features",
          payload: features,
        })
      );
    }
  }, []);

  const sendSelfReport = useCallback((reportData: any) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "self_report",
          payload: reportData,
        })
      );
    }
  }, []);

  return {
    isConnected,
    isReconnecting,
    sendPartialTranscript,
    sendFinalTranscript,
    sendBargeIn,
    sendConfirmedTranscript,
    sendReverseQuestion,
    sendCommunicationFeatures,
    sendSelfReport,
  };
}
