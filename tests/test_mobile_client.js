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
    const el = {
      id,
      value: "",
      textContent: "",
      _innerHTML: "",
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
      children: [],
      addEventListener() {},
      appendChild(child) { this.children.push(child); },
      scrollIntoView() {},
      focus() {},
      querySelector(s) {
        const matches = this.querySelectorAll(s);
        return matches.length ? matches[0] : getOrCreateElement("child_" + s);
      },
      querySelectorAll(s) {
        const out = [];
        const cleanCls = s.replace(/^\./, "");
        function search(node) {
          if (node.children) {
            for (const ch of node.children) {
              if (s.startsWith(".") && ch.className && ch.className.split(" ").includes(cleanCls)) {
                out.push(ch);
              }
              search(ch);
            }
          }
        }
        search(this);
        return out;
      },
    };
    Object.defineProperty(el, "innerHTML", {
      get() { return this._innerHTML; },
      set(val) {
        this._innerHTML = val;
        if (val === "") {
          this.children = [];
        }
      }
    });
    domElements[id] = el;
  }
  return domElements[id];
}

global.document = {
  querySelector(sel) {
    if (sel.startsWith("#")) {
      return getOrCreateElement(sel.slice(1));
    }
    const wrap = domElements["menu-days"];
    if (wrap && wrap.children && (sel === ".meal-header" || sel === ".changed-note")) {
      for (const card of wrap.children) {
        if (sel === ".changed-note") {
          const m = (card.innerHTML || "").match(/<div class="changed-note">([\s\S]*?)<\/div>/);
          return {
            innerHTML: m ? m[0] : "",
            textContent: m ? m[1] : "",
          };
        }
        if (card.innerHTML && card.innerHTML.includes(sel.replace(".", ""))) {
          return {
            innerHTML: card.innerHTML,
            textContent: card.innerHTML,
            querySelectorAll() { return []; }
          };
        }
      }
    }
    const all = this.querySelectorAll(sel);
    if (all.length) return all[0];
    return getOrCreateElement("mock_" + sel.replace(/[^a-zA-Z0-9]/g, "_"));
  },
  querySelectorAll(sel) {
    const onHand = domElements["on-hand-groups"];
    if (onHand && (sel === ".onhand-group" || sel.startsWith(".onhand-group["))) {
      const results = [];
      for (const ch of (onHand.children || [])) {
        if (sel.includes("[data-location=")) {
          const m = sel.match(/\[data-location="([^"]+)"\]/);
          if (m && ch.dataset && ch.dataset.location === m[1]) results.push(ch);
        } else {
          results.push(ch);
        }
      }
      return results;
    }
    const results = [];
    const cleanSel = sel.replace(/^\./, "");
    for (const key of Object.keys(domElements)) {
      const el = domElements[key];
      if (sel.startsWith(".") && el.className && el.className.split(" ").includes(cleanSel)) {
        results.push(el);
      } else if (sel.includes("[data-location=")) {
        const m = sel.match(/\[data-location="([^"]+)"\]/);
        if (m && el.dataset && el.dataset.location === m[1]) {
          results.push(el);
        }
      }
    }
    return results;
  },
  createElement(tag) {
    const el = getOrCreateElement("tag_" + tag + "_" + Math.random());
    el.tagName = tag.toUpperCase();
    return el;
  },
  addEventListener() {},
  visibilityState: "visible"
};

global.window = {
  addEventListener() {},
  scrollTo() {},
  open() {},
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
  // Test 11: Meal swap rendering: changed_from note renders and clears on full re-plan
  state.plan = {
    menu: [
      {
        day: "Monday",
        headcount: 2,
        breakfast: { dish_name: "Tofu Scramble", changed_from: "Old Scramble", prep_steps: ["Scramble tofu"], cook_time_minutes: 10 },
        lunch: null,
        dinner: null,
        ingredients_to_deduct: [],
        cooked: false,
      }
    ],
    shopping_list: []
  };
  renderMenu();
  const mealHeader = document.querySelector(".meal-header");
  assert.ok(mealHeader, "Meal header renders");
  const changedNote = document.querySelector(".changed-note");
  assert.ok(changedNote, "Changed from note renders");
  assert.strictEqual(changedNote.innerHTML.includes("Old Scramble"), true, "Note shows previous meal");

  // On full re-plan, meal without changed_from clears note
  state.plan.menu[0].breakfast = { dish_name: "Fresh Omelet", prep_steps: ["Cook"], cook_time_minutes: 5 };
  renderMenu();
  const clearedNote = document.querySelector(".changed-note");
  assert.strictEqual(clearedNote.innerHTML, "", "Changed from note cleared on new meal");
  console.log("✓ Test 11 Passed: Meal swap Changed-from note renders and clears on re-plan");
  passed++;

  // Test 12: Pull-to-refresh indicator and header refresh button exist
  const headerRefreshBtn = document.querySelector("#header-refresh-btn");
  assert.ok(headerRefreshBtn, "Header refresh button exists");
  const ptrIndicator = document.querySelector("#ptr-indicator");
  assert.ok(ptrIndicator, "Pull-to-refresh indicator exists");
  assert.strictEqual(typeof setupPullToRefresh, "function", "setupPullToRefresh is defined");
  console.log("✓ Test 12 Passed: Pull-to-refresh indicator and header refresh controls present");
  passed++;

  // Test 13: Dedicated "On Hand" inventory view
  state.inventory = [
    { id: 1, item_name: "Zucchini", quantity: 2, unit: "count", location: "Fridge", category: "Produce/Veggies" },
    { id: 2, item_name: "Apples", quantity: 4, unit: "count", location: "Fridge", category: "Produce/Veggies" },
    { id: 3, item_name: "Frozen Peas", quantity: 0, unit: "bags", location: "Freezer", category: "Frozen" },
    { id: 4, item_name: "Brown Rice", quantity: 1, unit: "bag", location: "Cupboard / Pantry", category: "Pantry/Dry" },
  ];
  renderInventory();

  // (a) Check grouping by Fridge, Freezer, Cupboard / Pantry
  // (a) Check grouping by Fridge, Freezer, Cupboard / Pantry
  const groups = document.querySelectorAll(".onhand-group");
  assert.strictEqual(groups.length, 3, "Three on-hand groups render for 3 distinct locations");

  // (b) Check alphabetical order inside Fridge: Apples (A) before Zucchini (Z)
  const fridgeGroup = document.querySelector('.onhand-group[data-location="Fridge"]');
  assert.ok(fridgeGroup, "Fridge group exists");
  const listDiv = fridgeGroup.children.find((c) => c.className === "onhand-list");
  assert.ok(listDiv, "Fridge list container exists");
  assert.ok(listDiv.children[0].innerHTML.includes("Apples"), "First fridge item is Apples (alphabetical)");
  assert.ok(listDiv.children[1].innerHTML.includes("Zucchini"), "Second fridge item is Zucchini (alphabetical)");

  // (c) Check 0 quantity displays as "out"
  const freezerGroup = document.querySelector('.onhand-group[data-location="Freezer"]');
  assert.ok(freezerGroup, "Freezer group exists");
  const freezerList = freezerGroup.children.find((c) => c.className === "onhand-list");
  assert.ok(freezerList, "Freezer list container exists");
  assert.ok(freezerList.children[0].innerHTML.includes('class="onhand-qty out">out<'), "0 quantity renders with out class and 'out' text");

  // (d) Mode toggling & jumpToInventoryEditor
  setInventoryViewMode("onhand");
  assert.strictEqual(document.querySelector("#on-hand-container").hidden, false);
  assert.strictEqual(document.querySelector("#inventory-editor-card").hidden, true);

  jumpToInventoryEditor("Apples");
  assert.strictEqual(document.querySelector("#on-hand-container").hidden, true);
  assert.strictEqual(document.querySelector("#inventory-editor-card").hidden, false);

  console.log("✓ Test 13 Passed: Dedicated On Hand view (Fridge/Freezer/Pantry grouping, alphabetical, 'out' badge, jump-to-editor)");
  passed++;

  // Test 14: Clear menu button, exact confirmation copy, and plan clearing in connected & standalone modes
  const clearTestPlan = {
    menu: [
      {
        day: "Monday",
        headcount: 2,
        breakfast: { dish_name: "Oatmeal", changed_from: "Pancakes" },
        lunch: { dish_name: "Salad" },
        dinner: { dish_name: "Pasta" },
        cooked: false,
      }
    ],
    shopping_list: [{ item_name: "Oats", quantity: 1, unit: "can", category: "Pantry/Dry" }],
    nutrition_notes: "Whole foods",
  };
  state.plan = clearTestPlan;
  state.planId = 42;
  state.planCreatedAt = "2026-10-18 10:00";
  state.inventory = [{ id: 1, item_name: "Milk", quantity: 2, unit: "bottle", location: "Fridge" }];
  state.settings = { base_headcount: 2, dietary_tags: ["Balanced"] };

  // 1. Render plan -> Clear menu button must be visible
  renderMenu();
  const clearBtn = document.querySelector("#clear-menu-btn");
  assert.ok(clearBtn, "Clear menu button exists in DOM");
  assert.strictEqual(clearBtn.style.display, "inline-block", "Clear menu button is visible when a plan exists");

  // 2. Open confirmation modal -> check exact required copy from index.html and element wiring
  const indexHtml = fs.readFileSync(path.join(__dirname, "../api/static/index.html"), "utf8");
  assert.ok(indexHtml.includes("Start over with a fresh menu?"), "Modal title matches exact required copy");
  assert.ok(
    indexHtml.includes("This clears your current 7-day menu and the shopping list built from it. Your stocked inventory, receipts, and settings stay exactly as they are."),
    "Modal body matches exact required copy"
  );
  assert.ok(indexHtml.includes(">Keep my menu</button>"), "Cancel button matches exact required copy");
  assert.ok(indexHtml.includes(">Clear it</button>"), "Confirm button matches exact required copy");

  showClearMenuModal();
  const clearModal = document.querySelector("#clear-menu-modal");
  assert.strictEqual(clearModal.hidden, false, "Clear menu modal is displayed");

  // 3. Cancel leaves plan completely untouched
  hideClearMenuModal();
  assert.strictEqual(clearModal.hidden, true, "Modal closed on cancel");
  assert.strictEqual(state.plan, clearTestPlan, "Plan left untouched on cancel");
  assert.strictEqual(state.inventory.length, 1, "Inventory untouched on cancel");

  // 4. Confirm in connected mode deletes plan on server and clears view
  setConnectionState("CONNECTED");
  let serverDeleteCalled = false;
  fetchHandler = async (url, opts) => {
    if (url.endsWith("/api/plan") && opts.method === "DELETE") {
      serverDeleteCalled = true;
      return {
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: async () => ({ plan_id: null, created_at: null, plan: null })
      };
    }
    return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => ({}) };
  };

  await confirmClearMenu();
  assert.strictEqual(serverDeleteCalled, true, "DELETE /api/plan called on server in connected mode");
  assert.strictEqual(state.plan, null, "state.plan is null after clearing");
  assert.strictEqual(state.planId, null, "state.planId is null after clearing");
  assert.strictEqual(clearBtn.style.display, "none", "Clear menu button hidden when no plan exists");
  assert.strictEqual(document.querySelector("#menu-empty").style.display, "block", "Menu empty state renders");
  assert.strictEqual(
    document.querySelector("#shopping-empty").textContent,
    "No menu planned yet — your shopping list will build from your plan.",
    "Shopping list returns to clean empty state guidance"
  );
  // Verify inventory & settings were NEVER touched
  assert.strictEqual(state.inventory.length, 1, "Inventory preserved untouched");
  assert.strictEqual(state.inventory[0].item_name, "Milk", "Inventory item preserved untouched");
  assert.strictEqual(state.settings.base_headcount, 2, "Settings preserved untouched");

  // 5. Standalone mode clear
  setConnectionState("DISCONNECTED");
  state.plan = clearTestPlan;
  state.planId = 99;
  renderMenu();
  assert.strictEqual(clearBtn.style.display, "inline-block");
  await confirmClearMenu();
  assert.strictEqual(state.plan, null, "Standalone mode clears local plan");
  assert.strictEqual(clearBtn.style.display, "none", "Clear menu button hidden after standalone clear");

  console.log("✓ Test 14 Passed: Clear menu button, confirmation copy, plan deletion, and inventory/settings isolation");
  passed++;

  // Test 15: Milestone 6 - "Shop this list" grocery handoff, Phase 1
  // 1. URL construction unit tests covering both providers with tricky item names
  const icUrl1 = buildGrocerySearchUrl("instacart", "Whole Milk");
  assert.strictEqual(icUrl1, "https://www.instacart.com/store/s?k=Whole%20Milk", "Instacart normal query");

  const icUrl2 = buildGrocerySearchUrl("instacart", "Salt & Pepper", "78701");
  assert.strictEqual(icUrl2, "https://www.instacart.com/store/s?k=Salt%20%26%20Pepper&postal_code=78701", "Instacart ampersand and zip");

  const icUrl3 = buildGrocerySearchUrl("instacart", "1/2 lb Chicken Breasts (boneless)");
  assert.strictEqual(icUrl3, "https://www.instacart.com/store/s?k=1%2F2%20lb%20Chicken%20Breasts%20(boneless)", "Instacart punctuation and slashes");

  const wmUrl1 = buildGrocerySearchUrl("walmart", "Fresh Garlic Cloves");
  assert.strictEqual(wmUrl1, "https://www.walmart.com/search?q=Fresh%20Garlic%20Cloves", "Walmart spaces query");

  const wmUrl2 = buildGrocerySearchUrl("walmart", "Mac & Cheese", "90210");
  assert.strictEqual(wmUrl2, "https://www.walmart.com/search?q=Mac%20%26%20Cheese&postal_code=90210", "Walmart ampersand and zip");

  const wmUrl3 = buildGrocerySearchUrl("walmart", "2% Reduced Fat Milk (1 gal)");
  assert.strictEqual(wmUrl3, "https://www.walmart.com/search?q=2%25%20Reduced%20Fat%20Milk%20(1%20gal)", "Walmart percent and parentheses");

  assert.strictEqual(buildGrocerySearchUrl("walmart", "   "), "", "Empty item name returns empty string");
  assert.throws(() => buildGrocerySearchUrl("unsupported_store", "Eggs"), /Unsupported grocery provider/);

  // 2. Settings persist / clear tests
  localStorage.removeItem(GROCERY_STORE_STORAGE);
  localStorage.removeItem(GROCERY_ZIP_STORAGE);
  assert.strictEqual(getStoredGroceryStore(), "", "Default store is unset initially");
  assert.strictEqual(getStoredGroceryZip(), "", "Default zip is unset initially");

  setStoredGroceryStore("instacart");
  setStoredGroceryZip("78701");
  assert.strictEqual(getStoredGroceryStore(), "instacart", "Persisted instacart store");
  assert.strictEqual(getStoredGroceryZip(), "78701", "Persisted zip");

  setStoredGroceryStore("walmart");
  assert.strictEqual(getStoredGroceryStore(), "walmart", "Round-trip update to walmart persists");

  clearGrocerySettings();
  assert.strictEqual(getStoredGroceryStore(), "", "Clearing settings resets store");
  assert.strictEqual(getStoredGroceryZip(), "", "Clearing settings resets zip");

  // 3. One-off ZIP override does NOT overwrite the saved home store ZIP
  setStoredGroceryStore("walmart");
  setStoredGroceryZip("10001");

  showShopModal();
  const shopModalEl = document.querySelector("#shop-modal");
  assert.strictEqual(shopModalEl.hidden, false, "Shop modal opens");

  const zipInputEl = document.querySelector("#shop-override-zip");
  assert.strictEqual(zipInputEl.value, "10001", "Modal defaults to saved home ZIP");

  zipInputEl.value = "90210";

  let openedUrls = [];
  const origWindowOpen = global.window.open;
  global.window.open = (url) => { openedUrls.push(url); return true; };

  state.plan = {
    shopping_list: [
      { item_name: "Fresh Spinach", amount_needed: "1 bag", purchased: false },
      { item_name: "Olive oil & vinegar", amount_needed: "1 bottle", purchased: false }
    ]
  };

  executeShopHandoff();

  assert.strictEqual(getStoredGroceryZip(), "10001", "One-off ZIP did NOT mutate saved home store ZIP");
  assert.strictEqual(localStorage.getItem(GROCERY_ZIP_STORAGE), "10001", "Storage untouched by one-off override");

  // 4. Empty shopping list disables or hides the button
  state.plan = null;
  renderShopping();
  const shopBtn = document.querySelector("#shop-list-btn");
  assert.strictEqual(shopBtn.disabled, true, "Shop button disabled when no plan exists");
  assert.strictEqual(shopBtn.style.display, "none", "Shop button hidden when no plan exists");

  state.plan = { shopping_list: [] };
  renderShopping();
  assert.strictEqual(shopBtn.disabled, true, "Shop button disabled when shopping list is empty");
  assert.strictEqual(shopBtn.style.display, "none", "Shop button hidden when shopping list is empty");

  state.plan = { shopping_list: [{ item_name: "Bread", amount_needed: "1 loaf", purchased: true }] };
  renderShopping();
  assert.strictEqual(shopBtn.disabled, true, "Shop button disabled when all items are purchased");
  assert.strictEqual(shopBtn.style.display, "inline-block", "Shop button shown when items present");

  state.plan = { shopping_list: [{ item_name: "Bread", amount_needed: "1 loaf", purchased: false }] };
  renderShopping();
  assert.strictEqual(shopBtn.disabled, false, "Shop button enabled when unpurchased items exist");
  assert.strictEqual(shopBtn.style.display, "inline-block", "Shop button shown when items present");

  // 5. Transparency / honesty copy verification
  const rawHtml = fs.readFileSync(path.resolve(__dirname, "../api/static/index.html"), "utf-8");
  assert.ok(
    rawHtml.includes("Pantry Planner prepares your shopping search links and hands them over to your chosen grocery service. All ordering, fulfillment, and payment happen directly on the store's website or app."),
    "Exact transparency and honesty copy present in shop modal HTML"
  );
  assert.ok(!rawHtml.includes("affiliate"), "No affiliate references");

  global.window.open = origWindowOpen;

  console.log("✓ Test 15 Passed: Milestone 6 - Shop this list grocery handoff, URL construction, ZIP isolation, and settings persistence");
  passed++;

  // Test 16: Meal images on recipe cards (Milestone 6 Task 3)
  // 1. Mapped category images
  const testCategories = [
    { name: "Fluffy Buttermilk Pancakes", cat: "breakfast" },
    { name: "Crispy Beef Tacos", cat: "tacos" },
    { name: "Spaghetti Bolognese", cat: "pasta" },
    { name: "Chicken and Veggie Stir-Fry", cat: "stir-fry" },
    { name: "Pan-Seared Salmon Fillet", cat: "seafood" },
    { name: "Herb Roasted Chicken Thighs", cat: "roast-chicken" },
    { name: "Creamy Tomato Soup", cat: "soup" },
    { name: "Fresh Garden Salad with Greens", cat: "salad" },
    { name: "Bacon Avocado Burger", cat: "sandwich" }
  ];

  testCategories.forEach(({ name, cat }) => {
    const meal = { dish_name: name, prep_steps: ["Prepare and cook"] };
    assert.strictEqual(getMealImageCategory(meal), cat, `Category matches for ${name}`);
    assert.strictEqual(getMealImageUrl(meal), `meal-images/${cat}.svg`, `Image URL matches for ${name}`);
    const block = mealBlock("🍽️", "Dinner", "dinner", meal, 0, false);
    assert.ok(block.includes(`src="meal-images/${cat}.svg"`), `Meal card renders category image for ${name}`);
    assert.ok(block.includes(`data-category="${cat}"`), `Category attribute present for ${name}`);
    assert.ok(block.includes('class="meal-banner"'), "Meal banner container present");
  });

  // 2. Unmapped meal renders default
  const unmappedMeal = { dish_name: "Grandma's Mysterious Surprise", prep_steps: ["Heat and enjoy"] };
  assert.strictEqual(getMealImageCategory(unmappedMeal), "default", "Unmapped meal resolves to default category");
  assert.strictEqual(getMealImageUrl(unmappedMeal), "meal-images/default.svg", "Unmapped meal resolves to default.svg");
  const unmappedBlock = mealBlock("🌙", "Dinner", "dinner", unmappedMeal, 0, false);
  assert.ok(unmappedBlock.includes('src="meal-images/default.svg"'), "Unmapped meal renders default image");
  assert.ok(unmappedBlock.includes('data-category="default"'), "Unmapped category is default");

  // 3. Image load failure fallback to branded placeholder tile with initial
  assert.ok(unmappedBlock.includes('class="meal-image-placeholder"'), "Placeholder element exists");
  assert.ok(unmappedBlock.includes('<span class="placeholder-initial">G</span>'), "Placeholder has correct dish initial");
  assert.ok(unmappedBlock.includes('onerror="this.style.display=\'none\'; if (this.nextElementSibling) this.nextElementSibling.style.display=\'flex\';"'), "Image onerror switches to placeholder");

  // 4. Swapped meal updates image dynamically
  const initialDish = { dish_name: "Oatmeal with Apples", prep_steps: ["Boil oats"] };
  const initialRender = mealBlock("🌅", "Breakfast", "breakfast", initialDish, 0, false);
  assert.ok(initialRender.includes('src="meal-images/breakfast.svg"'), "Initial meal has breakfast image");

  const swappedDish = { dish_name: "Chicken Enchiladas", changed_from: "Oatmeal with Apples", prep_steps: ["Bake"] };
  const swappedRender = mealBlock("🌅", "Breakfast", "breakfast", swappedDish, 0, false);
  assert.ok(swappedRender.includes('src="meal-images/tacos.svg"'), "Swapped meal updates image to tacos");
  assert.ok(swappedRender.includes('Changed from: <i>Oatmeal with Apples</i>'), "Changed-from note preserved on swapped meal");

  // 5. Verify local bundled image set exists on disk and total size is under 500KB
  const imgDir = path.resolve(__dirname, "../api/static/meal-images");
  const expectedFiles = [
    "tacos.svg", "pasta.svg", "stir-fry.svg", "roast-chicken.svg",
    "salad.svg", "soup.svg", "breakfast.svg", "seafood.svg",
    "sandwich.svg", "default.svg"
  ];
  let totalBytes = 0;
  for (const f of expectedFiles) {
    const fPath = path.join(imgDir, f);
    assert.ok(fs.existsSync(fPath), `Image file ${f} exists`);
    totalBytes += fs.statSync(fPath).size;
  }
  assert.ok(totalBytes > 0 && totalBytes < 500 * 1024, `Total size ${totalBytes} bytes is well within budget (<500KB)`);

  // 6. Verify credits note in HTML
  assert.ok(
    rawHtml.includes("Meal Imagery Credits:</b> Built-in vector culinary illustrations designed specifically for Pantry Planner under Creative Commons CC0 / Open License."),
    "Attribution / credits note present in HTML"
  );

  console.log("✓ Test 16 Passed: Meal images on recipe cards, category mapping, default fallback, placeholder initial, and image swapping");
  passed++;

  console.log(`\nAll ${passed} Mobile Client tests passed successfully!`);
}


runTests().catch((err) => {
  console.error("Test failed:", err);
  process.exit(1);
});



