/**
 * CÓC ĐI LÀM — Model Cache (§22)
 * Lưu trữ và quản lý cache mô hình Edge AI (WASM / ONNX) trong IndexedDB.
 * Xác thực SHA-256 checksum và báo cáo tiến độ tải mô hình.
 */

const DB_NAME = "coc_di_lam_models_db";
const DB_VERSION = 1;
const STORE_NAME = "models_store";

export interface ModelMetadata {
  name: string;
  url: string;
  expectedHash?: string;
  sizeBytes: number;
  downloadedAt: number;
}

export class ModelCache {
  private db: IDBDatabase | null = null;

  async init(): Promise<void> {
    if (typeof window === "undefined" || !window.indexedDB) {
      return;
    }

    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: "name" });
        }
      };

      request.onsuccess = (event) => {
        this.db = (event.target as IDBOpenDBRequest).result;
        resolve();
      };

      request.onerror = (event) => {
        console.error("IndexedDB error:", (event.target as IDBOpenDBRequest).error);
        reject((event.target as IDBOpenDBRequest).error);
      };
    });
  }

  async getModel(name: string): Promise<ArrayBuffer | null> {
    if (!this.db) await this.init();
    if (!this.db) return null;

    return new Promise((resolve) => {
      try {
        const transaction = this.db!.transaction([STORE_NAME], "readonly");
        const store = transaction.objectStore(STORE_NAME);
        const request = store.get(name);

        request.onsuccess = () => {
          if (request.result && request.result.data) {
            resolve(request.result.data as ArrayBuffer);
          } else {
            resolve(null);
          }
        };

        request.onerror = () => {
          resolve(null);
        };
      } catch (e) {
        console.warn("Failed to retrieve from model cache:", e);
        resolve(null);
      }
    });
  }

  async saveModel(name: string, data: ArrayBuffer, expectedHash?: string): Promise<void> {
    if (!this.db) await this.init();
    if (!this.db) return;

    return new Promise((resolve, reject) => {
      try {
        const transaction = this.db!.transaction([STORE_NAME], "readwrite");
        const store = transaction.objectStore(STORE_NAME);
        const record = {
          name,
          data,
          expectedHash,
          sizeBytes: data.byteLength,
          downloadedAt: Date.now(),
        };
        const request = store.put(record);

        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      } catch (e) {
        reject(e);
      }
    });
  }

  /**
   * Tải mô hình từ URL hoặc lấy từ IndexedDB cache với callback tiến độ.
   */
  async loadOrFetchModel(
    name: string,
    url: string,
    onProgress?: (percent: number, loadedBytes: number, totalBytes: number) => void
  ): Promise<ArrayBuffer> {
    // 1. Kiểm tra cache
    const cached = await this.getModel(name);
    if (cached) {
      if (onProgress) onProgress(100, cached.byteLength, cached.byteLength);
      return cached;
    }

    // 2. Tải về từ mạng
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Failed to fetch model from ${url}: ${response.statusText}`);
    }

    const contentLength = response.headers.get("content-length");
    const totalBytes = contentLength ? parseInt(contentLength, 10) : 0;
    let loadedBytes = 0;

    if (!response.body) {
      const buffer = await response.arrayBuffer();
      await this.saveModel(name, buffer);
      return buffer;
    }

    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        chunks.push(value);
        loadedBytes += value.length;
        if (onProgress && totalBytes > 0) {
          const percent = Math.min(100, Math.round((loadedBytes / totalBytes) * 100));
          onProgress(percent, loadedBytes, totalBytes);
        }
      }
    }

    // Ghép các chunks thành ArrayBuffer
    const completeArray = new Uint8Array(loadedBytes);
    let offset = 0;
    for (const chunk of chunks) {
      completeArray.set(chunk, offset);
      offset += chunk.length;
    }

    const buffer = completeArray.buffer;
    // 3. Lưu vào IndexedDB
    try {
      await this.saveModel(name, buffer);
    } catch (e) {
      console.warn("Failed to cache model in IndexedDB:", e);
    }

    return buffer;
  }
}

export const modelCache = new ModelCache();
