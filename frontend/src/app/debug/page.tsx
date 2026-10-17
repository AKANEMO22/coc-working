"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertCircle, RefreshCw, Route, Trash2 } from "lucide-react";

type TrafficEvent = {
  id: string;
  timestamp: string;
  kind: "http" | "websocket" | string;
  direction: string;
  name: string;
  method?: string;
  path?: string;
  status_code?: number;
  duration_ms?: number;
  trace_id?: string;
  session_id?: string;
  message_type?: string;
  payload_keys?: string[];
  payload_bytes?: number;
  error?: string;
};

type ApiRoute = { path: string; methods: string[]; name: string };

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function DebugPage() {
  const [events, setEvents] = useState<TrafficEvent[]>([]);
  const [routes, setRoutes] = useState<ApiRoute[]>([]);
  const [filter, setFilter] = useState<"all" | "http" | "websocket">("all");
  const [isPaused, setIsPaused] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [trafficResponse, routesResponse] = await Promise.all([
        fetch(`${API_BASE}/api/v1/debug/traffic?limit=150`, { cache: "no-store" }),
        fetch(`${API_BASE}/api/v1/debug/routes`, { cache: "no-store" }),
      ]);

      if (trafficResponse.status === 404 || routesResponse.status === 404) {
        throw new Error("Debug chỉ bật khi chạy backend local ở môi trường development.");
      }
      if (!trafficResponse.ok || !routesResponse.ok) {
        throw new Error(`Backend trả lỗi HTTP ${trafficResponse.status}/${routesResponse.status}.`);
      }

      const [trafficData, routeData] = await Promise.all([
        trafficResponse.json(),
        routesResponse.json(),
      ]);
      setEvents(trafficData.events || []);
      setRoutes(routeData.routes || []);
      setLastUpdated(new Date().toLocaleTimeString("vi-VN"));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không thể tải dữ liệu debug.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isPaused) return;
    const initialLoad = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(timer);
    };
  }, [isPaused, refresh]);

  const visibleEvents = useMemo(
    () => (filter === "all" ? events : events.filter((event) => event.kind === filter)),
    [events, filter],
  );

  const clearEvents = async () => {
    if (!window.confirm("Xóa toàn bộ log debug đang lưu trong bộ nhớ backend?")) return;
    try {
      const response = await fetch(`${API_BASE}/api/v1/debug/traffic`, { method: "DELETE" });
      if (!response.ok) throw new Error(`Backend trả lỗi HTTP ${response.status}.`);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không thể xóa log debug.");
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-6">
      <section className="glass-card p-6 sm:p-8">
        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-5">
          <div>
            <div className="flex items-center gap-2 text-[var(--coc-primary)] mb-2">
              <Activity className="w-5 h-5" />
              <span className="text-xs font-bold uppercase tracking-widest">Development tools</span>
            </div>
            <h1 className="text-3xl sm:text-4xl font-bold text-[var(--text-primary)]">Debug luồng dữ liệu</h1>
            <p className="text-[var(--text-secondary)] mt-2 max-w-3xl">
              Theo dõi route HTTP và message WebSocket giữa trình duyệt và backend. Nội dung CV, transcript,
              query string và giá trị payload không được lưu — chỉ giữ metadata để trace luồng.
            </p>
            <div className="mt-4 text-sm text-[var(--text-secondary)]">
              Địa chỉ local: <code className="px-2 py-1 rounded bg-black/20 text-[var(--coc-primary)]">http://127.0.0.1:3000/debug</code>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => setIsPaused((value) => !value)}
              className="btn-secondary flex items-center gap-2 text-sm"
            >
              <RefreshCw className={`w-4 h-4 ${isPaused ? "" : "animate-spin"}`} />
              {isPaused ? "Tiếp tục" : "Tạm dừng"}
            </button>
            <button
              type="button"
              onClick={() => void refresh()}
              className="btn-secondary flex items-center gap-2 text-sm"
            >
              <RefreshCw className="w-4 h-4" /> Làm mới
            </button>
            <button
              type="button"
              onClick={() => void clearEvents()}
              className="btn-secondary flex items-center gap-2 text-sm text-rose-300"
            >
              <Trash2 className="w-4 h-4" /> Xóa log
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-6 flex items-start gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
            <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold">Chưa kết nối được debug API</div>
              <div className="mt-1">{error}</div>
              <div className="mt-2 text-rose-100/80">Backend đang trỏ tới: {API_BASE}</div>
            </div>
          </div>
        )}

        <div className="grid sm:grid-cols-3 gap-3 mt-6">
          <SummaryCard label="Sự kiện gần đây" value={String(events.length)} />
          <SummaryCard label="API / WebSocket routes" value={String(routes.length)} />
          <SummaryCard label="Cập nhật lúc" value={lastUpdated || (isLoading ? "Đang tải…" : "—")} />
        </div>
      </section>

      <section className="glass-card overflow-hidden">
        <div className="px-5 py-4 border-b border-[var(--border-color)] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h2 className="font-bold text-[var(--text-primary)]">Các luồng đã ghi nhận</h2>
            <p className="text-xs text-[var(--text-muted)] mt-1">Tối đa 500 sự kiện gần nhất; log chỉ nằm trong RAM và mất khi backend khởi động lại.</p>
          </div>
          <div className="flex gap-1 rounded-lg border border-[var(--border-color)] p-1 bg-[var(--bg-secondary)]">
            {(["all", "http", "websocket"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                  filter === value ? "bg-[var(--coc-primary)] text-white" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                }`}
              >
                {value === "all" ? "Tất cả" : value === "http" ? "HTTP" : "WebSocket"}
              </button>
            ))}
          </div>
        </div>

        <div className="divide-y divide-[var(--border-color)] max-h-[34rem] overflow-auto">
          {visibleEvents.length === 0 ? (
            <div className="p-10 text-center text-sm text-[var(--text-muted)]">
              {isLoading ? "Đang tải log…" : "Chưa có traffic. Mở một luồng trong ứng dụng rồi quay lại đây."}
            </div>
          ) : visibleEvents.map((event) => <TrafficRow key={event.id} event={event} />)}
        </div>
      </section>

      <section className="glass-card overflow-hidden">
        <div className="px-5 py-4 border-b border-[var(--border-color)] flex items-center gap-2">
          <Route className="w-4 h-4 text-[var(--coc-primary)]" />
          <div>
            <h2 className="font-bold text-[var(--text-primary)]">Bản đồ endpoint hiện có</h2>
            <p className="text-xs text-[var(--text-muted)] mt-1">Route template phía backend; {routes.length} route đang đăng ký.</p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-[var(--text-muted)] bg-black/10">
              <tr><th className="text-left px-5 py-3">Phương thức</th><th className="text-left px-5 py-3">Đường dẫn</th><th className="text-left px-5 py-3">Handler</th></tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-color)]">
              {routes.map((route) => (
                <tr key={`${route.path}:${route.methods.join(",")}`}>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--coc-primary)]">{route.methods.join(", ") || "—"}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-primary)]">{route.path}</td>
                  <td className="px-5 py-3 text-xs text-[var(--text-secondary)]">{route.name}</td>
                </tr>
              ))}
              {routes.length === 0 && <tr><td colSpan={3} className="px-5 py-8 text-center text-[var(--text-muted)]">Không tải được route list.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[var(--border-color)] bg-black/10 p-4">
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 font-semibold text-[var(--text-primary)] break-all">{value}</div>
    </div>
  );
}

function TrafficRow({ event }: { event: TrafficEvent }) {
  const isWebSocket = event.kind === "websocket";
  const isError = Boolean(event.error) || (event.status_code !== undefined && event.status_code >= 400);
  const time = new Date(event.timestamp).toLocaleTimeString("vi-VN", { hour12: false });

  return (
    <article className="px-5 py-4 hover:bg-black/5">
      <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${isWebSocket ? "bg-purple-500/15 text-purple-300" : "bg-sky-500/15 text-sky-300"}`}>
              {isWebSocket ? "WebSocket" : "HTTP"}
            </span>
            <span className="text-xs font-mono text-[var(--text-muted)]">{time}</span>
            <span className="text-xs text-[var(--text-secondary)]">{event.direction}</span>
          </div>
          <div className="mt-2 font-mono text-sm text-[var(--text-primary)] break-all">
            {event.method && <span className="text-[var(--coc-primary)] mr-2">{event.method}</span>}
            {event.path || event.name}
            {event.message_type && <span className="ml-2 text-purple-300">[{event.message_type}]</span>}
          </div>
          {event.payload_keys && event.payload_keys.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {event.payload_keys.map((key) => <span key={key} className="rounded border border-[var(--border-color)] px-1.5 py-0.5 text-[10px] font-mono text-[var(--text-secondary)]">{key}</span>)}
              <span className="text-[10px] text-[var(--text-muted)] self-center">{event.payload_bytes || 0} bytes (nội dung không lưu)</span>
            </div>
          )}
          {event.trace_id && <div className="mt-2 text-[10px] text-[var(--text-muted)]">trace: <code>{event.trace_id}</code></div>}
          {event.session_id && <div className="mt-1 text-[10px] text-[var(--text-muted)]">session: <code>{event.session_id}</code></div>}
          {event.error && <div className="mt-2 text-xs text-rose-300">Lỗi: {event.error}</div>}
        </div>
        <div className="flex items-center gap-2 shrink-0 text-xs">
          {event.status_code !== undefined && (
            <span className={`rounded px-2 py-1 font-mono font-bold ${isError ? "bg-rose-500/15 text-rose-300" : "bg-emerald-500/15 text-emerald-300"}`}>
              {event.status_code}
            </span>
          )}
          {event.duration_ms !== undefined && <span className="text-[var(--text-muted)]">{event.duration_ms} ms</span>}
        </div>
      </div>
    </article>
  );
}
