import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

const store = new Map<string, string>();

const localStorageMock = {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => {
    store.set(key, value);
  },
  removeItem: (key: string) => {
    store.delete(key);
  },
  clear: () => {
    store.clear();
  },
  key: (index: number) => Array.from(store.keys())[index] ?? null,
  get length() {
    return store.size;
  },
};

// jsdom cung cấp window thật (cần cho render React) — chỉ override localStorage
// để test có store sạch, KHÔNG stub cả window (sẽ phá document/render).
vi.stubGlobal("localStorage", localStorageMock);

// Unmount component & dọn DOM sau mỗi test để tránh rò rỉ giữa các test.
afterEach(() => {
  cleanup();
  store.clear();
});
