# Pantry Planner — Mobile (API + PWA) Version

A clean, mobile-first version of the Pantry-to-Menu Planner. A FastAPI backend
(`main.py`) serves both the REST API and a small installable web app
(`static/`) — same SQLite database, same AI logic as the Streamlit version
in `../app.py`. Both apps can be used interchangeably; they share
`pantry_planner.db` in the project root.

## Run it

From the project root (`~/workspace/projects/pantry-planner`):

```bash
# one-time setup (or reuse the existing .venv)
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt

# start the server
.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
```

## Open it on your phone

1. Find your PC's local IP (e.g. `192.168.1.42`) — on Windows: `ipconfig`;
   on Linux/Mac: `ip addr` / `ifconfig`.
2. On your phone (same Wi-Fi), open **http://\<pc-ip\>:8000**
3. Tap your browser's menu → **"Add to Home Screen"** to install it as an app.

## Gemini key (bring your own — it's free)

The app uses Google's free Gemini AI tier. The first time you open the app,
a setup screen walks you through it:

1. Tap **🔑 Get My Free Gemini Key** (opens https://aistudio.google.com/apikey — no credit card).
2. Paste the key into the app and tap **Save & Connect**.
3. The app checks the key against Google (one tiny test call via
   `POST /api/validate-key`) and only saves it on your device
   (browser localStorage) after Google accepts it.

You can replace the key anytime in the **Diet** tab (🔑 Gemini API Key section).
The key is stored only on your device, is only ever sent to Google through
the backend, and is never logged. Alternatively, start the server with the
`GEMINI_API_KEY` environment variable set and no per-device key is needed.

## API endpoints

| Endpoint | What it does |
|---|---|
| `GET /health` | Liveness check |
| `GET /api/inventory` | List inventory |
| `POST /api/inventory` | Add items `{location, items[]}` |
| `PUT /api/inventory` | Bulk-replace inventory (existing row IDs are preserved) |
| `DELETE /api/inventory` | Clear all inventory |
| `GET /api/settings` / `PUT /api/settings` | Household & diet settings |
| `POST /api/scan-photo` | Multipart photo + `location` → Gemini shelf scan |
| `POST /api/plan/generate` | `{daily_headcounts, theme_name}` → new 7-day plan |
| `GET /api/plan/latest` | Latest saved plan |
| `POST /api/plan/cook` | `{day_index}` → deduct that day's ingredients |
| `POST /api/shopping/restock` | `{indices}` → add checked items to inventory |
| `POST /api/shopping/clear-purchased` | Remove all purchased items from the latest plan's shopping list |
| `POST /api/receipt/scan` | Multipart receipt photo → auto-restock + check off list |
| `GET /api/shopping-list/export?include_purchased=bool` | Shopping list as Markdown |
| `POST /api/validate-key` | Validate the `X-Gemini-Key` header with one tiny Gemini call |
| `GET /` | The mobile web app (PWA) |

Gemini-backed endpoints accept the key via the `X-Gemini-Key` header
(the web app sends it automatically) or fall back to `GEMINI_API_KEY`.

## Notes

- Set `PANTRY_DB_FILE` to point the backend at a different SQLite file
  (handy for testing) — default is `pantry_planner.db` in the project root.
