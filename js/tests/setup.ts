import "@testing-library/jest-dom/vitest";

function isStorageLike(value: unknown): value is Storage {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Storage).getItem === "function" &&
    typeof (value as Storage).setItem === "function" &&
    typeof (value as Storage).removeItem === "function"
  );
}

function createMemoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  };
}

const storage =
  typeof window !== "undefined" && isStorageLike(window.localStorage)
    ? window.localStorage
    : createMemoryStorage();

if (typeof window !== "undefined" && !isStorageLike(window.localStorage)) {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    writable: true,
    value: storage,
  });
}

if (!isStorageLike(globalThis.localStorage)) {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: storage,
  });
}
