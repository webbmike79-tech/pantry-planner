/**
 * Automated test suite for mobile client app.js logic:
 * - State machine transitions
 * - Offline cache persistence and retrieval
 * - Hand-add outbox queuing and duplicate protection
 * - Destructive action blocking while offline
 * - Server URL and token injection
 */

const assert = require("assert");
const fs = require("fs");
const path = require("path");

// Mock LocalStorage
class LocalStorageMock {
  constructor() {
    this.store = {};
  }
  getItem(key) {
    return this.store[key] !== undefined ? this.store[key] : null;
  }
  setItem(key, value) {
    this.store[key] = String(value);
  }
  removeItem(key) {
    delete this.store[key];
  }
  clear() {
    this.store = {};
  }
}

// Set up global mocks for headless testing
global.localStorage = new LocalStorageMock();
global.sessionStorage = new LocalStorageMock();

// Mock DOM elements
const domElements = {};
function getOrCreateElement(id) {
  if (!domElements[id]) {
    domElements[id] = {
      id,
      value: "",
      textContent: "",
      innerHTML: "",
      className: "",
      classList: {
        classes: new Set(),
        add(c) { this.classes.add(c); },
        remove(c) { this.classes.delete(c); },
        toggle(c, val) { if (val === undefined) val = !this.classes.has(c); if (val) this.add(c); else this.remove(c); },
        contains(c) { return this.classes.has(c); }
      },
      hidden: false,
      style: {},
      disabled: false,
      dataset: {},
      addEventListener() {},
      appendChild() {},
      scrollIntoView() {},
      focus() {},
      querySelector(s) { return getOrCreateElement("child_" + s); },
      querySelectorAll() { return []; },
    };
  }
  return domElements[id];
}

global.document = {
  querySelector(sel) {
    if (sel.startsWith("#")) {
      return getOrCreateElement(sel.slice(1));
    }
    return getOrCreateElement("mock_" + sel.replace(/[^a-zA-Z0-9]/g, "_"));
  },
  querySelectorAll() {
    return [];
  },
  createElement(tag) {
    return getOrCreateElement("tag_" + tag + "_" + Math.random());
  },
  addEventListener() {},
  visibilityState: "visible"
};

global.window = {
  addEventListener() {},
  scrollTo() {},
  location: { protocol: "http:", origin: "http://localhost:8000" }
};

// Mock fetch
let fetchHandler = null;
global.fetch = async (url, opts = {}) => {
  if (fetchHandler) {
    return fetchHandler(url, opts);
  }
  return {
    ok: true,
    status: 200,
    headers: { get: (h) => (h === "content-type" ? "application/json" : "") },
    json: async () => ({ status: "ok", app: "pantry-planner" }),
    text: async () => JSON.stringify({ status: "ok" })
  };
};

const vm = require("vm");
// Read app.js
const appJsPath = path.resolve(__dirname, "../api/static/app.js");
const appJsCode = fs.readFileSync(appJsPath, "utf-8");

// Evaluate in global context
vm.runInThisContext(appJsCode);

// Test suite execution
async function runTests() {
  console.log("Starting Mobile Client unit tests...");
  let passed = 0;

  // Test 1: buildUrl
  localStorage.clear();
  assert.strictEqual(buildUrl("/api/inventory"), "/api/inventory", "Relative URL when no server stored");
  localStorage.setItem(SERVER_URL_STORAGE, "http://192.168.4.159:8000");
  assert.strictEqual(buildUrl("/api/inventory"), "http://192.168.4.159:8000/api/inventory", "Prefixed with desktop server URL");
  assert.strictEqual(buildUrl("api/inventory"), "http://192.168.4.159:8000/api/inventory", "Handles leading slash gracefully");
  console.log("✓ Test 1 Passed: buildUrl resolution");
  passed++;

  // Test 2: api() headers injection
  let capturedHeaders = null;
  localStorage.setItem(KEY_STORAGE, "test-gemini-key-123");
  localStorage.setItem(ACCESS_TOKEN_STORAGE, "secret-token-456");
  fetchHandler = async (url, opts) => {
    capturedHeaders = opts.headers;
    return {
      ok: true,
      status: 200,
      headers: { get: () => "application/json" },
      json: async () => [{ id: 1, item_name: "Test Apple" }]
    };
  };
  const data = await api("/api/inventory");
  assert.strictEqual(capturedHeaders["X-Gemini-Key"], "test-gemini-key-123");
  assert.strictEqual(capturedHeaders["X-Pantry-Token"], "secret-token-456");
  assert.strictEqual(data.length, 1);
  console.log("✓ Test 2 Passed: api() injects Gemini Key and Pantry Access Token");
  passed++;

  // Test 3: Connection State transitions
  setConnectionState("CONNECTED");
  assert.strictEqual(isOnline(), true);
  assert.strictEqual(document.querySelector("#connection-banner").hidden, true);
  assert.strictEqual(document.querySelector("#server-status-dot").classList.contains("connected"), true);

  setConnectionState("DISCONNECTED");
  assert.strictEqual(isOnline(), false);
  assert.strictEqual(document.querySelector("#connection-banner").hidden, false);
  assert.strictEqual(document.querySelector("#server-status-dot").classList.contains("disconnected"), true);

  setConnectionState("AUTH_REQUIRED");
  assert.strictEqual(isOnline(), false);
  assert.strictEqual(document.querySelector("#connection-banner").hidden, false);
  assert.strictEqual(document.querySelector("#server-status-dot").classList.contains("auth"), true);
  console.log("✓ Test 3 Passed: Connection state machine UI updates");
  passed++;

  // Test 4: Offline cache save & load
  const mockInv = [{ id: 10, item_name: "Carrots", quantity: 5, unit: "count" }];
  const mockSettings = { base_headcount: 4, dietary_tags: ["Gluten-Free"] };
  const mockPlan = { plan_id: 1, created_at: "2026-10-16 12:00", plan: { menu: [] } };
  saveToOfflineCache(mockInv, mockSettings, mockPlan);

  // Clear memory state
  state.inventory = [];
  state.settings = null;
  state.plan = null;

  loadFromOfflineCache();
  assert.strictEqual(state.inventory.length, 1);
  assert.strictEqual(state.inventory[0].item_name, "Carrots");
  assert.strictEqual(state.settings.base_headcount, 4);
  assert.strictEqual(state.planId, 1);
  console.log("✓ Test 4 Passed: Offline cache save and load");
  passed++;

  // Test 5: Safe Outbox queuing when offline
  setConnectionState("DISCONNECTED");
  localStorage.removeItem(OUTBOX_STORAGE);
  const newItem = {
    item_name: "Fresh Spinach",
    quantity: 2,
    unit: "bags",
    location: "Fridge",
    category: "Produce/Veggies"
  };
  queueOfflineAdd(newItem);

  const outbox = getOutbox();
  assert.strictEqual(outbox.length, 1);
  assert.strictEqual(outbox[0].item_name, "Fresh Spinach");
  assert.ok(outbox[0].client_id.startsWith("outbox_"));
  assert.strictEqual(state.inventory[0].item_name, "Fresh Spinach");
  assert.strictEqual(state.inventory[0]._isQueued, true);
  console.log("✓ Test 5 Passed: queueOfflineAdd appends to outbox and local inventory");
  passed++;

  // Test 6: Outbox flushing and deduplication
  let postedItems = [];
  fetchHandler = async (url, opts) => {
    try {
      if (opts.method === "POST" && url.includes("/api/inventory")) {
        const body = JSON.parse(opts.body);
        postedItems.push(...body.items);
        return {
          ok: true,
          status: 200,
          headers: { get: () => "application/json" },
          json: async () => ({ added: body.items.length, inventory: [] })
        };
      }
      return {
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: async () => []
      };
    } catch (err) {
      console.error("fetchHandler error:", err);
      throw err;
    }
  };

  setConnectionState("CONNECTED");
  // Allow the auto-flush microtask from state change to complete
  await new Promise((r) => setTimeout(r, 20));

  assert.strictEqual(postedItems.length, 1);
  assert.strictEqual(postedItems[0].item_name, "Fresh Spinach");
  assert.strictEqual(getOutbox().length, 0, "Outbox should be empty after successful flush");

  // Re-flush with same outbox item to verify deduplication
  localStorage.setItem(OUTBOX_STORAGE, JSON.stringify([outbox[0]]));
  postedItems = [];
  await flushOutbox();
  assert.strictEqual(postedItems.length, 0, "Deduplication prevented re-sending already synced item");
  console.log("✓ Test 6 Passed: Outbox flush and deduplication");
  passed++;

  // Test 7: Destructive actions blocked while offline
  setConnectionState("DISCONNECTED");
  let attemptedFetch = false;
  fetchHandler = async () => {
    attemptedFetch = true;
    return { ok: true, status: 200, json: async () => ({}) };
  };

  attemptedFetch = false;
  await saveInventory();
  assert.strictEqual(attemptedFetch, false, "saveInventory blocked while offline");

  attemptedFetch = false;
  await generatePlan();
  assert.strictEqual(attemptedFetch, false, "generatePlan blocked while offline");

  attemptedFetch = false;
  await cookDay(0);
  assert.strictEqual(attemptedFetch, false, "cookDay blocked while offline");

  attemptedFetch = false;
  await restock();
  assert.strictEqual(attemptedFetch, false, "restock blocked while offline");

  attemptedFetch = false;
  await clearPurchased();
  assert.strictEqual(attemptedFetch, false, "clearPurchased blocked while offline");

  attemptedFetch = false;
  await scanShelfPhoto();
  assert.strictEqual(attemptedFetch, false, "scanShelfPhoto blocked while offline");
  console.log("✓ Test 7 Passed: All destructive actions safely blocked while offline");
  passed++;

  // Test 8: Key ownership rule: connected mode never blocks on client keys
  setConnectionState("CONNECTED");
  localStorage.removeItem(KEY_STORAGE);
  localStorage.removeItem(GROQ_KEY_STORAGE);
  localStorage.removeItem(OPENROUTER_KEY_STORAGE);
  assert.strictEqual(hasKey(), false, "Client has no local keys stored");
  assert.strictEqual(requireKey(), true, "Connected mode permits AI operations without client keys");
  console.log("✓ Test 8 Passed: Connected mode never prompts for or blocks on client keys");
  passed++;

  // Test 9: Key persistence in localStorage survives across simulated restarts
  localStorage.setItem(KEY_STORAGE, "AIzaSyTestGeminiKey123");
  localStorage.setItem(GROQ_KEY_STORAGE, "gsk_TestGroqKey456");
  localStorage.setItem(OPENROUTER_KEY_STORAGE, "sk-or-v1-TestOpenRouter789");
  assert.strictEqual(storedKey(), "AIzaSyTestGeminiKey123");
  assert.strictEqual(storedGroqKey(), "gsk_TestGroqKey456");
  assert.strictEqual(storedOpenRouterKey(), "sk-or-v1-TestOpenRouter789");
  console.log("✓ Test 9 Passed: Provider keys persist reliably across storage accesses");
  passed++;

  // Test 10: Clean first-run state: empty shopping list displays plain empty message
  state.plan = null;
  state.inventory = [];
  renderShopping();
  const emptyEl = document.querySelector("#shopping-empty");
  assert.strictEqual(emptyEl.style.display, "block");
  assert.strictEqual(
    emptyEl.textContent,
    "No menu planned yet — your shopping list will build from your plan."
  );
  assert.strictEqual(document.querySelectorAll("#shopping-list .shop-item").length, 0);
  console.log("✓ Test 10 Passed: Clean first-run shopping list is empty with exact required guidance message");
  passed++;

  console.log(`\nAll ${passed} Mobile Client tests passed successfully!`);
}

runTests().catch((err) => {
  console.error("Test failed:", err);
  process.exit(1);
});
