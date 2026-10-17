import json
import os
import re
import sqlite3
from datetime import datetime
from typing import List, Optional
import pandas as pd
from PIL import Image
from pydantic import BaseModel, Field
import streamlit as st
from google import genai
from google.genai import types

from api.ai_fallback import (
    ProviderKeys,
    extract_provider_keys,
    generate_structured_with_fallback,
    validate_provider_key,
)

# ==========================================
# 1. SEASONAL & HOLIDAY THEME ENGINE
# ==========================================

THEMES = {
    "🎃 Halloween / October": {
        "bg": "#16121d",
        "card": "#241d30",
        "accent": "#ff7518",
        "accent_soft": "#ffb347",
        "text": "#f8f5fa",
        "banner": "🎃 Spooky Harvest Kitchen Mode",
    },
    "🦃 Thanksgiving / November": {
        "bg": "#1b130e",
        "card": "#2b1f18",
        "accent": "#d96b27",
        "accent_soft": "#e6b35a",
        "text": "#fdf8f5",
        "banner": "🦃 Thanksgiving & Autumn Harvest Mode",
    },
    "🎄 Christmas / December": {
        "bg": "#0f1d16",
        "card": "#193024",
        "accent": "#d64545",
        "accent_soft": "#e6c280",
        "text": "#f4fbf7",
        "banner": "🎄 Holiday Evergreen Kitchen Mode",
    },
    "❄️ Winter Frost (Jan–Feb)": {
        "bg": "#0f172a",
        "card": "#1e293b",
        "accent": "#38bdf8",
        "accent_soft": "#94a3b8",
        "text": "#f8fafc",
        "banner": "❄️ Winter Comfort Kitchen Mode",
    },
    "🌱 Spring Garden (Mar–May)": {
        "bg": "#112218",
        "card": "#1b3326",
        "accent": "#10b981",
        "accent_soft": "#fbbf24",
        "text": "#f2fbf6",
        "banner": "🌱 Fresh Spring Garden Mode",
    },
    "☀️ Summer BBQ (Jun–Sep)": {
        "bg": "#111827",
        "card": "#1f2937",
        "accent": "#f97316",
        "accent_soft": "#84cc16",
        "text": "#f9fafb",
        "banner": "☀️ Summer Grill & Citrus Mode",
    },
}


def get_auto_theme_name() -> str:
    month = datetime.now().month
    if month == 10:
        return "🎃 Halloween / October"
    elif month == 11:
        return "🦃 Thanksgiving / November"
    elif month == 12:
        return "🎄 Christmas / December"
    elif month in (1, 2):
        return "❄️ Winter Frost (Jan–Feb)"
    elif month in (3, 4, 5):
        return "🌱 Spring Garden (Mar–May)"
    else:
        return "☀️ Summer BBQ (Jun–Sep)"


def apply_seasonal_css(theme_name: str):
    t = THEMES[theme_name]
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-color: {t['bg']};
            color: {t['text']};
        }}
        button[data-baseweb="tab"] {{
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            padding: 12px 18px !important;
            border-radius: 10px 10px 0 0 !important;
            background-color: {t['card']} !important;
            color: {t['text']} !important;
            margin-right: 6px !important;
            border: 1px solid rgba(255,255,255,0.08) !important;
        }}
        button[data-baseweb="tab"][aria-selected="true"] {{
            background-color: {t['accent']} !important;
            color: #ffffff !important;
            border-bottom: 3px solid {t['accent_soft']} !important;
        }}
        div[data-testid="stMetric"], div[data-testid="stExpander"] {{
            background-color: {t['card']};
            border: 1px solid {t['accent']}55;
            border-radius: 12px;
            padding: 10px 14px;
        }}
        .stButton > button[kind="primary"] {{
            background-color: {t['accent']} !important;
            border-color: {t['accent_soft']} !important;
            color: #ffffff !important;
            font-weight: 700 !important;
            border-radius: 10px !important;
            padding: 0.6rem 1rem !important;
        }}
        .stButton > button {{
            border-radius: 10px !important;
            font-weight: 600 !important;
        }}
        .seasonal-banner {{
            background: linear-gradient(90deg, {t['card']}, {t['accent']}44);
            border-left: 5px solid {t['accent']};
            padding: 12px 18px;
            border-radius: 10px;
            margin-bottom: 16px;
            font-weight: 600;
            font-size: 1.05rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==========================================
# 2. PYDANTIC SCHEMAS FOR STRUCTURED AI OUTPUT
# ==========================================


class DetectedItem(BaseModel):
    item_name: str = Field(description="Clear name of the food, drink, or seasoning")
    category: str = Field(
        description="One of: Produce/Veggies, Protein, Dairy, Seasoning/Spice, Drink/Beverage, Pantry/Dry, Frozen"
    )
    quantity: float = Field(description="Numeric estimate of the amount visible")
    unit: str = Field(description="Unit of measure, e.g., oz, lbs, count, bottle, bag, can")


class VisionInventoryResult(BaseModel):
    items: List[DetectedItem]


class UsedIngredient(BaseModel):
    inventory_id: int = Field(
        description="The exact 'id' from CURRENT KITCHEN INVENTORY (use -1 if not in inventory)"
    )
    item_name: str = Field(description="Name of the inventory item used")
    amount_used: float = Field(
        description="Numeric quantity used for this day's meals, in the same unit as the inventory item"
    )
    unit: str = Field(description="Unit of measure matching the inventory item")


class MealDetail(BaseModel):
    dish_name: str = Field(description="Name of the recipe")
    prep_steps: List[str] = Field(
        description="Step-by-step cooking instructions (include air fryer, oven, or stovetop guidance)"
    )
    cook_time_minutes: int = Field(description="Estimated cooking time in minutes")


class DayMealPlan(BaseModel):
    day: str = Field(description="Day of the week (e.g., Monday)")
    headcount: int = Field(description="Number of people being fed this day")
    breakfast: MealDetail
    lunch: MealDetail
    dinner: MealDetail
    ingredients_to_deduct: List[UsedIngredient] = Field(
        description="Exact inventory items and numeric amounts used on this day"
    )
    cooked: bool = Field(
        default=False, description="Always initialize as False when generating a plan"
    )


class ShoppingListItem(BaseModel):
    item_name: str = Field(description="Clean name of the grocery item to buy")
    category: str = Field(
        description="One of: Veggies & Produce, Proteins, Seasonings & Spices, Drinks & Beverages, Pantry & Dairy"
    )
    amount_needed: str = Field(description="Human-readable amount to buy, e.g., '2 lbs' or '1 bottle'")
    numeric_quantity: float = Field(
        description="Numeric amount to add to inventory when purchased, e.g., 2.0"
    )
    unit: str = Field(description="Unit of measure, e.g., lbs, oz, count, bottle, bag, can")
    default_location: str = Field(
        description="Where this item belongs when bought: 'Fridge', 'Freezer', or 'Cupboard / Pantry'"
    )
    inventory_category: str = Field(
        description="One of: Produce/Veggies, Protein, Dairy, Seasoning/Spice, Drink/Beverage, Pantry/Dry, Frozen"
    )
    reason: str = Field(description="Which meal(s) or essential restock this covers")
    purchased: bool = Field(default=False, description="Always initialize as False")


class WeeklyPlanOutput(BaseModel):
    menu: List[DayMealPlan]
    shopping_list: List[ShoppingListItem]
    nutrition_notes: str = Field(
        description="Brief summary of how this menu strictly complies with the household's custom dietary restrictions"
    )


class ReceiptLineItem(BaseModel):
    item_name: str = Field(
        description="Decoded, human-readable food/drink/seasoning name from the receipt"
    )
    quantity: float = Field(description="Numeric quantity purchased (e.g., 1.0, 2.5, 12.0)")
    unit: str = Field(description="Unit of measure, e.g., lbs, oz, count, bag, bottle, can")
    default_location: str = Field(
        description="Best storage spot: 'Fridge', 'Freezer', or 'Cupboard / Pantry'"
    )
    inventory_category: str = Field(
        description="One of: Produce/Veggies, Protein, Dairy, Seasoning/Spice, Drink/Beverage, Pantry/Dry, Frozen"
    )
    matched_shopping_list_index: int = Field(
        description="Exact 'index' from the provided shopping list if this item fulfills it; otherwise -1"
    )


class ReceiptScanResult(BaseModel):
    store_name: str = Field(description="Store name if visible on receipt, otherwise 'Grocery Store'")
    items: List[ReceiptLineItem]


# ==========================================
# 3. SQLITE DATABASE LAYER
# ==========================================

DB_FILE = "pantry_planner.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location TEXT,
            item_name TEXT,
            category TEXT,
            quantity REAL,
            unit TEXT,
            updated_at TEXT
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            base_headcount INTEGER,
            dietary_tags TEXT,
            custom_diet_notes TEXT,
            essential_staples TEXT
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            plan_json TEXT
        )
    """
    )
    c.execute("SELECT COUNT(*) FROM settings")
    if c.fetchone()[0] == 0:
        default_tags = json.dumps(["Balanced & Whole Foods"])
        default_staples = (
            "Olive oil, garlic powder, onion powder, black pepper, broth, fresh veggies, water"
        )
        c.execute(
            """
            INSERT INTO settings (id, base_headcount, dietary_tags, custom_diet_notes, essential_staples)
            VALUES (1, 2, ?, 'Provide wholesome meals tailored to any household restrictions entered below.', ?)
        """,
            (default_tags, default_staples),
        )
    conn.commit()
    conn.close()


def add_inventory_items(location: str, items: List[DetectedItem]):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for item in items:
        c.execute(
            """
            INSERT INTO inventory (location, item_name, category, quantity, unit, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (location, item.item_name, item.category, item.quantity, item.unit, now),
        )
    conn.commit()
    conn.close()


def get_inventory_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM inventory ORDER BY location, category, item_name", conn)
    conn.close()
    return df


def replace_inventory_from_df(df: pd.DataFrame):
    # FIX (2026-10-14): preserve existing row IDs on save. The original version
    # deleted all rows and re-inserted without IDs, so every save renumbered the
    # inventory and broke the inventory_id references stored in saved meal plans
    # (deduct fell back to fuzzy name matching). Rows carrying a valid existing
    # id now keep it; brand-new editor rows (id empty/NaN) get a fresh id.
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM inventory")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    seen_ids = set()
    for _, row in df.iterrows():
        raw_id = row.get("id")
        keep_id = None
        if raw_id is not None and not (isinstance(raw_id, float) and pd.isna(raw_id)):
            try:
                candidate = int(raw_id)
                if candidate > 0 and candidate not in seen_ids:
                    keep_id = candidate
                    seen_ids.add(candidate)
            except (TypeError, ValueError):
                keep_id = None
        values = (
            row.get("location", "Cupboard / Pantry"),
            row.get("item_name", ""),
            row.get("category", "Pantry/Dry"),
            float(row.get("quantity", 0.0)),
            row.get("unit", "count"),
            row.get("updated_at") or now,
        )
        if keep_id is not None:
            c.execute(
                """
                INSERT INTO inventory (id, location, item_name, category, quantity, unit, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (keep_id,) + values,
            )
        else:
            c.execute(
                """
                INSERT INTO inventory (location, item_name, category, quantity, unit, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                values,
            )
    conn.commit()
    conn.close()


def deduct_day_from_inventory(plan_id: int, day_idx: int) -> List[str]:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT plan_json FROM saved_plans WHERE id = ?", (plan_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return []

    plan_data = json.loads(row[0])
    day_obj = plan_data["menu"][day_idx]

    if day_obj.get("cooked", False):
        conn.close()
        return []

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    deducted_summary = []

    for ing in day_obj.get("ingredients_to_deduct", []):
        inv_id = ing.get("inventory_id", -1)
        amt = float(ing.get("amount_used", 0.0))
        name = ing.get("item_name", "")
        unit = ing.get("unit", "")

        if amt <= 0:
            continue

        c.execute("SELECT id, quantity FROM inventory WHERE id = ?", (inv_id,))
        target = c.fetchone()
        if not target:
            c.execute(
                "SELECT id, quantity FROM inventory WHERE LOWER(item_name) = LOWER(?) LIMIT 1",
                (name,),
            )
            target = c.fetchone()

        if target:
            target_id, current_qty = target
            new_qty = max(0.0, round(float(current_qty) - amt, 2))
            c.execute(
                "UPDATE inventory SET quantity = ?, updated_at = ? WHERE id = ?",
                (new_qty, now, target_id),
            )
            deducted_summary.append(f"{name}: -{amt} {unit} (now {new_qty} {unit})")

    plan_data["menu"][day_idx]["cooked"] = True
    c.execute(
        "UPDATE saved_plans SET plan_json = ? WHERE id = ?",
        (json.dumps(plan_data), plan_id),
    )
    conn.commit()
    conn.close()
    return deducted_summary


def restock_checked_shopping_items(plan_id: int, item_indices: List[int]) -> List[str]:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT plan_json FROM saved_plans WHERE id = ?", (plan_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return []

    plan_data = json.loads(row[0])
    shopping_list = plan_data.get("shopping_list", [])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    restocked_log = []

    for idx in item_indices:
        if idx < 0 or idx >= len(shopping_list):
            continue
        item = shopping_list[idx]
        if item.get("purchased", False):
            continue

        name = item.get("item_name", "Unknown Item")
        qty = item.get("numeric_quantity")
        if qty is None:
            match = re.search(r"(\d+(\.\d+)?)", str(item.get("amount_needed", "1")))
            qty = float(match.group(1)) if match else 1.0
        else:
            qty = float(qty)

        unit = item.get("unit") or "count"
        loc = item.get("default_location") or "Cupboard / Pantry"
        inv_cat = item.get("inventory_category") or "Pantry/Dry"

        c.execute(
            "SELECT id, quantity FROM inventory WHERE LOWER(item_name) = LOWER(?) LIMIT 1",
            (name,),
        )
        existing = c.fetchone()

        if existing:
            ex_id, ex_qty = existing
            new_qty = round(float(ex_qty) + qty, 2)
            c.execute(
                "UPDATE inventory SET quantity = ?, updated_at = ? WHERE id = ?",
                (new_qty, now, ex_id),
            )
            restocked_log.append(f"Updated {name}: +{qty} {unit} (Total: {new_qty} {unit})")
        else:
            c.execute(
                """
                INSERT INTO inventory (location, item_name, category, quantity, unit, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (loc, name, inv_cat, qty, unit, now),
            )
            restocked_log.append(f"Added {name} ({qty} {unit}) to {loc}")

        shopping_list[idx]["purchased"] = True

    plan_data["shopping_list"] = shopping_list
    c.execute(
        "UPDATE saved_plans SET plan_json = ? WHERE id = ?",
        (json.dumps(plan_data), plan_id),
    )
    conn.commit()
    conn.close()
    return restocked_log


def process_scanned_receipt_items(
    plan_id: Optional[int], receipt_items: List[ReceiptLineItem]
) -> List[str]:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    plan_data = None
    shopping_list = []
    if plan_id is not None:
        c.execute("SELECT plan_json FROM saved_plans WHERE id = ?", (plan_id,))
        row = c.fetchone()
        if row:
            plan_data = json.loads(row[0])
            shopping_list = plan_data.get("shopping_list", [])

    restocked_log = []

    for r_item in receipt_items:
        name = r_item.item_name.strip()
        qty = max(0.1, round(float(r_item.quantity), 2))
        unit = r_item.unit.strip() or "count"
        loc = r_item.default_location
        if loc not in ["Fridge", "Freezer", "Cupboard / Pantry"]:
            loc = "Cupboard / Pantry"
        inv_cat = r_item.inventory_category

        c.execute(
            "SELECT id, quantity FROM inventory WHERE LOWER(item_name) = LOWER(?) LIMIT 1",
            (name,),
        )
        existing = c.fetchone()
        if existing:
            ex_id, ex_qty = existing
            new_qty = round(float(ex_qty) + qty, 2)
            c.execute(
                "UPDATE inventory SET quantity = ?, updated_at = ? WHERE id = ?",
                (new_qty, now, ex_id),
            )
            log_entry = f"🔄 **{name}**: +{qty} {unit} (Now {new_qty} {unit} in {loc})"
        else:
            c.execute(
                """
                INSERT INTO inventory (location, item_name, category, quantity, unit, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (loc, name, inv_cat, qty, unit, now),
            )
            log_entry = f"➕ **{name}**: Added {qty} {unit} to {loc}"

        matched_idx = r_item.matched_shopping_list_index
        if shopping_list:
            if 0 <= matched_idx < len(shopping_list):
                shopping_list[matched_idx]["purchased"] = True
                log_entry += f" *(✅ Checked off Shopping List)*"
            else:
                for s_idx, s_item in enumerate(shopping_list):
                    s_name = s_item.get("item_name", "").lower()
                    if s_name and (s_name in name.lower() or name.lower() in s_name):
                        shopping_list[s_idx]["purchased"] = True
                        log_entry += f" *(✅ Checked off Shopping List)*"
                        break

        restocked_log.append(log_entry)

    if plan_data is not None and plan_id is not None:
        plan_data["shopping_list"] = shopping_list
        c.execute(
            "UPDATE saved_plans SET plan_json = ? WHERE id = ?",
            (json.dumps(plan_data), plan_id),
        )

    conn.commit()
    conn.close()
    return restocked_log


def get_settings():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT base_headcount, dietary_tags, custom_diet_notes, essential_staples FROM settings WHERE id = 1"
    )
    row = c.fetchone()
    conn.close()
    return {
        "base_headcount": row[0],
        "dietary_tags": json.loads(row[1]),
        "custom_diet_notes": row[2],
        "essential_staples": row[3],
    }


def save_settings(base_headcount: int, dietary_tags: list, custom_notes: str, staples: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        UPDATE settings
        SET base_headcount = ?, dietary_tags = ?, custom_diet_notes = ?, essential_staples = ?
        WHERE id = 1
    """,
        (base_headcount, json.dumps(dietary_tags), custom_notes, staples),
    )
    conn.commit()
    conn.close()


def save_plan(plan_dict: dict):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO saved_plans (created_at, plan_json) VALUES (?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M"), json.dumps(plan_dict)),
    )
    conn.commit()
    conn.close()


def get_latest_plan():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, created_at, plan_json FROM saved_plans ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return row[0], row[1], json.loads(row[2])
    return None, None, None


# ==========================================
# 4. GEMINI AI FUNCTIONS
# ==========================================

# FIX (2026-10-14): all Gemini calls now raise a friendly RuntimeError on any
# API/parse failure instead of crashing the app with a raw traceback. The UI
# catches RuntimeError and shows it with st.error.


def get_client(api_key: str):
    return genai.Client(api_key=api_key)


def _generate_structured(keys_or_key, contents, schema, temperature: float, what: str):
    """Shared structured-output call routed through the AI provider fallback chain."""
    if isinstance(keys_or_key, ProviderKeys):
        keys = keys_or_key
    elif isinstance(keys_or_key, str):
        keys = ProviderKeys(gemini_key=keys_or_key)
    else:
        keys = ProviderKeys()
    result, _served_by = generate_structured_with_fallback(keys, contents, schema, temperature, what)
    return result


def analyze_storage_photo(keys_or_key, image: Image.Image, location: str) -> List[DetectedItem]:
    prompt = f"""
    You are scanning a user's {location}.
    Identify all visible food items, ingredients, veggies, drinks, and seasonings.
    Estimate the remaining quantity and unit for each item as accurately as possible
    (e.g., 0.5 gallon, 2 cans, 12 oz, 1 bottle).
    """
    parsed = _generate_structured(
        keys_or_key, [image, prompt], VisionInventoryResult, 0.2, f"scan your {location} photo"
    )
    return parsed.items


def analyze_grocery_receipt(
    api_key: str, image: Image.Image, shopping_list: list
) -> ReceiptScanResult:
    indexed_shopping = [
        {
            "index": idx,
            "item_name": item.get("item_name"),
            "amount_needed": item.get("amount_needed"),
            "purchased": item.get("purchased", False),
        }
        for idx, item in enumerate(shopping_list)
    ]

    prompt = f"""
    You are scanning a grocery store receipt image.
    1. Extract every food, drink, produce, meat, dairy, or seasoning item purchased.
    2. Decode abbreviated store receipt text into clean, standard grocery names.
    3. Ignore non-food items (paper towels, tax, etc.).
    4. Estimate numeric quantity, unit, default storage location, and category.
    5. Match against the ACTIVE SHOPPING LIST below where applicable.

    ACTIVE SHOPPING LIST:
    {json.dumps(indexed_shopping, indent=2)}
    """
    return _generate_structured(
        api_key, [image, prompt], ReceiptScanResult, 0.1, "read your grocery receipt"
    )


def generate_weekly_menu_and_list(
    api_key: str,
    inventory_df: pd.DataFrame,
    settings: dict,
    daily_headcounts: dict,
    active_theme: str,
) -> WeeklyPlanOutput:
    if inventory_df.empty:
        inv_records = []
    else:
        inv_records = inventory_df[
            ["id", "location", "item_name", "category", "quantity", "unit"]
        ].to_dict(orient="records")

    prompt = f"""
    Build a practical, delicious 7-day meal plan and a consolidated shopping list.
    Current Season/Holiday Context: {active_theme}

    CURRENT KITCHEN INVENTORY (Cupboard, Fridge, Freezer):
    {json.dumps(inv_records, indent=2)}

    DAILY HEADCOUNT SCHEDULE (Scale portion sizes and ingredient math to match each day):
    {json.dumps(daily_headcounts, indent=2)}

    HOUSEHOLD DIETARY RESTRICTIONS & MEDICAL NEEDS (STRICT ENFORCEMENT):
    - Selected Tags/Diets: {", ".join(settings["dietary_tags"])}
    - Specific Household Rules & Allergies: {settings["custom_diet_notes"]}

    DIETARY ENFORCEMENT RULES FOR THE AI:
    1. STRICTLY OBEY all dietary tags, medical restrictions, and food allergies specified by the household above. Avoid all allergens and restricted ingredients completely across every meal.
    2. Provide clear step-by-step preparation instructions for breakfast, lunch, and dinner, including timings and recommendations for countertop appliances (like an air fryer or stovetop/oven).

    INSTRUCTIONS:
    1. Prioritize using existing fridge, freezer, and cupboard items before they spoil.
    2. Scale recipes accurately for the exact headcount on each day.
    3. For each day's `ingredients_to_deduct`, reference the exact `id` (`inventory_id`), `item_name`, `amount_used` (numeric), and matching `unit` from CURRENT KITCHEN INVENTORY. Set `cooked` to False.
    4. Compare total ingredients needed for the 7 days against CURRENT KITCHEN INVENTORY and generate a categorized Shopping List for missing items. Populate `numeric_quantity`, `unit`, `default_location`, and `inventory_category`. Set `purchased` to False.
    """

    return _generate_structured(
        api_key, prompt, WeeklyPlanOutput, 0.3, "build your weekly menu"
    )


# ==========================================
# 5. STREAMLIT UI (SEASONAL + MOBILE/DESKTOP NAV)
# ==========================================

st.set_page_config(page_title="Pantry-to-Menu Planner", page_icon="🥘", layout="wide")
init_db()

with st.sidebar:
    st.header("🎨 Season & Holiday Theme")
    auto_theme = get_auto_theme_name()
    theme_options = ["Auto (Current Season/Holiday)"] + list(THEMES.keys())
    selected_theme_mode = st.selectbox("Color Scheme", options=theme_options, index=0)

    active_theme_name = (
        auto_theme
        if selected_theme_mode == "Auto (Current Season/Holiday)"
        else selected_theme_mode
    )
    apply_seasonal_css(active_theme_name)

    st.divider()
    st.header("⚙️ Configuration")
    env_key = os.environ.get("GEMINI_API_KEY", "")
    api_key = st.text_input("Gemini API Key", value=env_key, type="password")
    st.caption("📱 Mobile Tip: Open the Network URL on your phone to snap shelves & receipts.")

st.title("🥘 Smart Pantry-to-Menu & Shopping Planner")
st.markdown(
    f'<div class="seasonal-banner">{THEMES[active_theme_name]["banner"]} — Active Theme: <b>{active_theme_name}</b></div>',
    unsafe_allow_html=True,
)

inv_df_top = get_inventory_df()
settings_top = get_settings()
plan_id_top, created_at_top, latest_plan_top = get_latest_plan()

days_cooked_count = 0
unpurchased_count = 0
if latest_plan_top:
    days_cooked_count = sum(1 for d in latest_plan_top.get("menu", []) if d.get("cooked", False))
    unpurchased_count = sum(
        1 for s in latest_plan_top.get("shopping_list", []) if not s.get("purchased", False)
    )

m1, m2, m3, m4 = st.columns(4)
m1.metric("📦 Stocked Items", len(inv_df_top))
m2.metric("👨‍👩‍👧 Base Headcount", f"{settings_top['base_headcount']} People")
m3.metric("🍳 Meals Cooked", f"{days_cooked_count} / 7 Days")
m4.metric("🛒 To Buy", f"{unpurchased_count} Items")

tab_scan, tab_diet, tab_menu, tab_shop = st.tabs([
    "📸 1. Scan & Stock",
    "👨‍👩‍👧 2. Household & Diet",
    "📅 3. Weekly Menu & Recipes",
    "🛒 4. Shopping & Receipts",
])

# ------------------------------------------
# TAB 1: SCAN & INVENTORY
# ------------------------------------------
with tab_scan:
    col_cam, col_inv = st.columns([1, 1.4])

    with col_cam:
        st.subheader("📸 Snap or Upload Shelves")
        storage_loc = st.radio(
            "Storage Area",
            ["Fridge", "Freezer", "Cupboard / Pantry"],
            horizontal=True,
        )
        input_mode = st.radio(
            "Camera Source",
            ["📁 Upload Photo", "📷 Live Phone Camera"],
            horizontal=True,
        )

        img_file = (
            st.camera_input(f"Snap {storage_loc}")
            if "Live Phone" in input_mode
            else st.file_uploader(
                f"Upload {storage_loc} photo", type=["jpg", "jpeg", "png", "webp"]
            )
        )

        if img_file is not None:
            image = Image.open(img_file)
            st.image(image, caption=f"{storage_loc} Snapshot", use_container_width=True)

            if st.button(
                f"🔍 Scan {storage_loc} & Log Amounts", type="primary", use_container_width=True
            ):
                if not api_key:
                    st.error("Please enter your Gemini API Key in the sidebar first.")
                else:
                    with st.spinner(f"Scanning {storage_loc} and estimating amounts..."):
                        try:
                            detected = analyze_storage_photo(api_key, image, storage_loc)
                            add_inventory_items(storage_loc, detected)
                            st.success(f"Added {len(detected)} items to {storage_loc}!")
                            st.rerun()
                        except RuntimeError as e:
                            st.error(str(e))

    with col_inv:
        st.subheader("📦 Kitchen Inventory")
        loc_filter = st.radio(
            "Filter by Location",
            ["All", "Fridge", "Freezer", "Cupboard / Pantry"],
            horizontal=True,
        )

        display_df = (
            inv_df_top
            if loc_filter == "All"
            else inv_df_top[inv_df_top["location"] == loc_filter]
        )

        edited_df = st.data_editor(
            display_df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": None,
                "location": st.column_config.SelectboxColumn(
                    "Location", options=["Fridge", "Freezer", "Cupboard / Pantry"], required=True
                ),
                "item_name": st.column_config.TextColumn("Item", required=True),
                "category": st.column_config.SelectboxColumn(
                    "Category",
                    options=[
                        "Produce/Veggies",
                        "Protein",
                        "Dairy",
                        "Seasoning/Spice",
                        "Drink/Beverage",
                        "Pantry/Dry",
                        "Frozen",
                    ],
                ),
                "quantity": st.column_config.NumberColumn("Amount", min_value=0.0, step=0.5),
                "unit": st.column_config.TextColumn("Unit"),
                "updated_at": st.column_config.TextColumn("Updated", disabled=True),
            },
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 Save Inventory Edits", type="primary", use_container_width=True):
                if loc_filter == "All":
                    replace_inventory_from_df(edited_df)
                else:
                    other_rows = inv_df_top[inv_df_top["location"] != loc_filter]
                    combined = pd.concat([other_rows, edited_df], ignore_index=True)
                    replace_inventory_from_df(combined)
                st.toast("Inventory updated!")
                st.rerun()
        with c2:
            if st.button("🗑️ Clear All Inventory", use_container_width=True):
                conn = sqlite3.connect(DB_FILE)
                conn.execute("DELETE FROM inventory")
                conn.commit()
                conn.close()
                st.rerun()

# ------------------------------------------
# TAB 2: HOUSEHOLD HEADCOUNT & CUSTOM DIET SPECS
# ------------------------------------------
with tab_diet:
    col_hh, col_dt = st.columns(2)

    with col_hh:
        st.subheader("👨‍👩‍👧 Household Size & Holiday Scaling")
        base_hc = st.number_input(
            "Standard Household Headcount",
            min_value=1,
            max_value=50,
            value=settings_top["base_headcount"],
        )
        st.caption("Scale individual days below for guests or holidays (e.g., 20 for Thanksgiving).")

        days_of_week = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        daily_headcounts = {}
        hc_cols = st.columns(2)
        for idx, day in enumerate(days_of_week):
            with hc_cols[idx % 2]:
                daily_headcounts[day] = st.number_input(
                    f"{day} Headcount", min_value=1, max_value=100, value=base_hc, key=f"hc_{day}"
                )

    with col_dt:
        st.subheader("🥗 Household Dietary Restrictions & Allergies")
        available_tags = [
            "Balanced & Whole Foods",
            "Diabetic / Low Glycemic",
            "Anti-Inflammatory / Low Saturated Fat",
            "Gluten-Free",
            "Dairy-Free / Lactose Intolerant",
            "Nut / Peanut Allergy",
            "Low Sodium / Heart Healthy",
            "Low Carb / Keto",
            "Vegetarian",
            "Vegan",
        ]
        selected_tags = st.multiselect(
            "Common Household Diets & Allergies",
            options=available_tags,
            default=settings_top["dietary_tags"],
        )
        custom_notes = st.text_area(
            "Specific Household Medical Needs, Allergies, or Favorite Cuisines",
            value=settings_top["custom_diet_notes"],
            placeholder="e.g., Type 2 diabetes for one member, severe peanut allergy for another, prefer Tex-Mex or German cuisine.",
        )
        staples = st.text_area(
            "Essential Staples to Always Check (Seasonings, Drinks, Veggies)",
            value=settings_top["essential_staples"],
        )

        if st.button("💾 Save Household & Diet Settings", type="primary", use_container_width=True):
            save_settings(base_hc, selected_tags, custom_notes, staples)
            st.success("Household dietary preferences saved!")
            st.rerun()

# ------------------------------------------
# TAB 3: WEEKLY MENU & STEP-BY-STEP RECIPES
# ------------------------------------------
with tab_menu:
    st.subheader("📅 7-Day Custom Menu & Step-by-Step Recipes")
    if st.button(
        "🚀 Generate 7-Day Menu & Recipes from Inventory",
        type="primary",
        use_container_width=True,
    ):
        if not api_key:
            st.error("Please enter your Gemini API Key in the sidebar first.")
        else:
            with st.spinner(
                "Building allergy-compliant menu, portion scaling, and recipe steps..."
            ):
                try:
                    plan_output = generate_weekly_menu_and_list(
                        api_key, inv_df_top, settings_top, daily_headcounts, active_theme_name
                    )
                    save_plan(plan_output.model_dump())
                    st.success("Weekly Menu & Recipes ready!")
                    st.rerun()
                except RuntimeError as e:
                    st.error(str(e))

    if latest_plan_top:
        st.caption(f"Plan generated: {created_at_top}")
        st.info(f"**Dietary & Nutrition Note:** {latest_plan_top['nutrition_notes']}")

        for day_idx, day_item in enumerate(latest_plan_top["menu"]):
            is_cooked = day_item.get("cooked", False)
            status_badge = "✅ [COOKED]" if is_cooked else "⏳ [PLANNED]"
            header_label = (
                f"**{day_item['day']}** — Feeding {day_item['headcount']} People {status_badge}"
            )

            with st.expander(header_label, expanded=not is_cooked):
                b_meal = day_item.get("breakfast", {})
                st.markdown(f"### 🌅 Breakfast: {b_meal.get('dish_name', 'Breakfast')}")
                st.caption(f"⏱️ Cook Time: {b_meal.get('cook_time_minutes', 15)} mins")
                for step in b_meal.get("prep_steps", []):
                    st.markdown(f"- {step}")

                st.divider()

                l_meal = day_item.get("lunch", {})
                st.markdown(f"### ☀️ Lunch: {l_meal.get('dish_name', 'Lunch')}")
                st.caption(f"⏱️ Cook Time: {l_meal.get('cook_time_minutes', 15)} mins")
                for step in l_meal.get("prep_steps", []):
                    st.markdown(f"- {step}")

                st.divider()

                d_meal = day_item.get("dinner", {})
                st.markdown(f"### 🌙 Dinner: {d_meal.get('dish_name', 'Dinner')}")
                st.caption(f"⏱️ Cook Time: {d_meal.get('cook_time_minutes', 30)} mins")
                for step in d_meal.get("prep_steps", []):
                    st.markdown(f"- {step}")

                deductions = day_item.get("ingredients_to_deduct", [])
                if deductions:
                    formatted_ing = [
                        f"{d['item_name']} ({d['amount_used']} {d['unit']})" for d in deductions
                    ]
                    st.caption(f"**Inventory to Deduct:** {', '.join(formatted_ing)}")

                st.markdown("")
                if is_cooked:
                    st.button(
                        f"✅ {day_item['day']} Cooked & Deducted from Inventory",
                        key=f"cooked_btn_{plan_id_top}_{day_idx}",
                        disabled=True,
                        use_container_width=True,
                    )
                else:
                    if st.button(
                        f"🍳 Cooked {day_item['day']}'s Meals — Subtract from Inventory",
                        key=f"cook_btn_{plan_id_top}_{day_idx}",
                        use_container_width=True,
                    ):
                        changes = deduct_day_from_inventory(plan_id_top, day_idx)
                        st.toast(
                            f"Subtracted {len(changes)} items from inventory!"
                            if changes
                            else f"Marked {day_item['day']} as cooked!"
                        )
                        st.rerun()
    else:
        st.write("No menu generated yet. Scan your shelves and click **Generate** above.")

# ------------------------------------------
# TAB 4: SHOPPING & RECEIPTS
# ------------------------------------------
with tab_shop:
    col_list, col_receipt = st.columns([1.2, 1])

    with col_list:
        st.subheader("🛒 Smart Shopping Checklist")
        if latest_plan_top and "shopping_list" in latest_plan_top:
            shopping_items = latest_plan_top["shopping_list"]
            if shopping_items:
                st.caption(
                    "Check items off manually or scan your store receipt on the right to auto-restock."
                )

                checked_indices = []
                categories = sorted(
                    list({item.get("category", "General") for item in shopping_items})
                )

                for cat in categories:
                    st.markdown(f"#### {cat}")
                    for idx, item in enumerate(shopping_items):
                        if item.get("category", "General") != cat:
                            continue

                        is_bought = item.get("purchased", False)
                        loc_badge = item.get("default_location", "Cupboard / Pantry")
                        label = (
                            f"**{item['item_name']}** — Need: `{item['amount_needed']}` "
                            f"*(Dest: {loc_badge} | {item['reason']})*"
                        )

                        if is_bought:
                            st.checkbox(
                                f"~~{item['item_name']} ({item['amount_needed']})~~ — ✅ **Restocked in {loc_badge}**",
                                value=True,
                                disabled=True,
                                key=f"shop_done_{plan_id_top}_{idx}",
                            )
                        else:
                            if st.checkbox(label, key=f"shop_chk_{plan_id_top}_{idx}"):
                                checked_indices.append(idx)

                st.divider()
                if st.button(
                    f"📥 Add Checked Items ({len(checked_indices)}) to Kitchen Inventory",
                    type="primary",
                    disabled=(len(checked_indices) == 0),
                    use_container_width=True,
                ):
                    restocked = restock_checked_shopping_items(plan_id_top, checked_indices)
                    st.success(
                        f"Added {len(restocked)} grocery items directly into your SQLite inventory!"
                    )
                    st.rerun()

                st.divider()
                st.markdown("#### 🖨️ Printable / Shareable Shopping List")
                include_bought = st.checkbox(
                    "Include already-restocked items", value=False, key="export_include_bought"
                )
                export_lines = [
                    "# 🛒 Shopping List",
                    f"_Plan generated: {created_at_top}_",
                    "",
                    "## This Week's Menu",
                ]
                for d in latest_plan_top.get("menu", []):
                    export_lines.append(
                        f"- **{d['day']}** — Breakfast: {d.get('breakfast', {}).get('dish_name', '')} | "
                        f"Lunch: {d.get('lunch', {}).get('dish_name', '')} | "
                        f"Dinner: {d.get('dinner', {}).get('dish_name', '')}"
                    )
                export_lines += ["", "## To Buy"]
                export_cats = sorted(
                    list({i.get("category", "General") for i in shopping_items})
                )
                any_to_buy = False
                for cat in export_cats:
                    cat_items = [
                        i
                        for i in shopping_items
                        if i.get("category", "General") == cat
                        and (include_bought or not i.get("purchased", False))
                    ]
                    if not cat_items:
                        continue
                    any_to_buy = True
                    export_lines.append(f"\n### {cat}")
                    for i in cat_items:
                        mark = "x" if i.get("purchased", False) else " "
                        export_lines.append(
                            f"- [{mark}] {i['item_name']} — {i['amount_needed']} "
                            f"(store to: {i.get('default_location', 'Cupboard / Pantry')})"
                        )
                if not any_to_buy:
                    export_lines.append("\n🎉 Nothing to buy — inventory covers the week!")
                export_md = "\n".join(export_lines)
                st.download_button(
                    "⬇️ Download Shopping List (.md)",
                    data=export_md,
                    file_name="shopping_list.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
                with st.expander("Preview / Copy Shopping List"):
                    st.code(export_md, language="markdown")
            else:
                st.success("🎉 Your kitchen inventory covers the entire week's menu!")
        else:
            st.write("Generate a weekly menu in Tab 3 first to populate your shopping list.")

    with col_receipt:
        st.subheader("🧾 Scan Grocery Receipt")
        st.caption("Snap your paper receipt to auto-restock your kitchen and check off your list.")

        receipt_mode = st.radio(
            "Receipt Input Method",
            ["📁 Upload Receipt Photo", "📷 Live Phone Camera"],
            horizontal=True,
            key="receipt_input_mode",
        )

        receipt_file = (
            st.camera_input("Snap Grocery Receipt", key="receipt_cam")
            if "Live Phone" in receipt_mode
            else st.file_uploader(
                "Upload Grocery Receipt",
                type=["jpg", "jpeg", "png", "webp"],
                key="receipt_upload",
            )
        )

        if receipt_file is not None:
            r_image = Image.open(receipt_file)
            st.image(r_image, caption="Grocery Receipt Preview", use_container_width=True)

            if st.button(
                "🧾 Scan Receipt & Auto-Restock Kitchen",
                type="primary",
                use_container_width=True,
            ):
                if not api_key:
                    st.error("Please enter your Gemini API Key in the sidebar first.")
                else:
                    active_shop_list = (
                        latest_plan_top.get("shopping_list", []) if latest_plan_top else []
                    )
                    with st.spinner(
                        "Reading receipt, decoding abbreviations, and updating SQLite inventory..."
                    ):
                        try:
                            scan_res = analyze_grocery_receipt(api_key, r_image, active_shop_list)
                            logs = process_scanned_receipt_items(plan_id_top, scan_res.items)
                            st.session_state["last_receipt_store"] = scan_res.store_name
                            st.session_state["last_receipt_logs"] = logs
                            st.rerun()
                        except RuntimeError as e:
                            st.error(str(e))

        if "last_receipt_logs" in st.session_state and st.session_state["last_receipt_logs"]:
            store_title = st.session_state.get("last_receipt_store", "Grocery Store")
            st.success(
                f"✅ Restocked {len(st.session_state['last_receipt_logs'])} items from **{store_title}**:"
            )
            with st.expander("View Receipt Restock Breakdown", expanded=True):
                for entry in st.session_state["last_receipt_logs"]:
                    st.markdown(f"- {entry}")
