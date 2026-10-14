# 🥘 Pantry-to-Menu Planner

Snap photos of your fridge, freezer, and pantry — get a 7-day menu, step-by-step
recipes, and a smart shopping list, all matched to your household's dietary needs.

Powered by Google's **free** Gemini AI: every user brings their own free Gemini
API key (one-tap setup inside the app — no credit card, ~30 seconds).

## Two ways to run it

### 1. Mobile app (recommended) — FastAPI + PWA

```bash
pip install -r api/requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Open `http://<your-pc-ip>:8000` on your phone and choose **Add to Home Screen** —
it installs and opens like a real app. See `api/README.md` for details.

### 2. Desktop original — Streamlit

```bash
pip install streamlit google-genai pillow pydantic pandas
streamlit run app.py --server.address 0.0.0.0
```

## Features

- 📸 Gemini Vision shelf scans (fridge / freezer / cupboard) with quantities
- 🧾 Grocery receipt scanner — decodes store abbreviations, auto-restocks inventory
- 📅 7-day menu scaled per-day (guests, holidays) with step-by-step recipe cards
- 🥗 Strict dietary enforcement from *your* household's own restrictions
- 🍳 "Cooked" buttons deduct exact ingredient amounts from inventory
- 🛒 Categorized shopping list with 1-click restock + printable Markdown export
- 🎨 Seasonal / holiday themes

Both versions share one SQLite database (`pantry_planner.db`).
