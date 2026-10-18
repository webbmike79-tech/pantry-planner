"""
Tests for pantry-planner mobile FastAPI backend using unittest.
Verifies CORS headers, health endpoint, inventory routes, and DB isolation.
"""

import os
import tempfile
import unittest
from starlette.testclient import TestClient

# Set temporary DB before importing api.main
temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db.close()
os.environ["PANTRY_DB_FILE"] = temp_db.name

from api.main import app, init_db


class TestMobileApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        import sqlite3
        from api.main import DB_FILE
        init_db()
        conn = sqlite3.connect(DB_FILE)
        conn.execute("DELETE FROM inventory")
        conn.execute("DELETE FROM saved_plans")
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(temp_db.name):
                os.unlink(temp_db.name)
        except Exception:
            pass

    def test_health_endpoint(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["app"], "pantry-planner")

    def test_cors_headers_localhost(self):
        res = self.client.options(
            "/api/inventory",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "http://localhost:8000")

    def test_cors_headers_capacitor(self):
        res = self.client.options(
            "/api/inventory",
            headers={
                "Origin": "capacitor://localhost",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "capacitor://localhost")

    def test_cors_headers_lan_ip(self):
        res = self.client.options(
            "/api/inventory",
            headers={
                "Origin": "http://192.168.4.159:8000",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "http://192.168.4.159:8000")

    def test_inventory_crud_and_add(self):
        # 1. Clear inventory
        res = self.client.delete("/api/inventory")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["inventory"], [])

        # 2. Add item via POST /api/inventory (hand-add / outbox format)
        res = self.client.post(
            "/api/inventory",
            json={
                "location": "Fridge",
                "items": [
                    {
                        "item_name": "Organic Milk",
                        "category": "Dairy",
                        "quantity": 1.0,
                        "unit": "gallon",
                    }
                ],
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["added"], 1)
        self.assertEqual(len(data["inventory"]), 1)
        item = data["inventory"][0]
        self.assertEqual(item["item_name"], "Organic Milk")
        self.assertEqual(item["location"], "Fridge")
        self.assertEqual(item["quantity"], 1.0)

        # 3. Add second item
        res = self.client.post(
            "/api/inventory",
            json={
                "location": "Cupboard / Pantry",
                "items": [
                    {
                        "item_name": "Rolled Oats",
                        "category": "Pantry/Dry",
                        "quantity": 2.5,
                        "unit": "lbs",
                    }
                ],
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["inventory"]), 2)

        # 4. Get inventory
        res = self.client.get("/api/inventory")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()), 2)

        # 5. Bulk replace via PUT /api/inventory
        res = self.client.put(
            "/api/inventory",
            json=[
                {
                    "id": 1,
                    "location": "Fridge",
                    "item_name": "Almond Milk",
                    "category": "Dairy",
                    "quantity": 0.5,
                    "unit": "carton",
                }
            ],
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["inventory"]), 1)
        self.assertEqual(res.json()["inventory"][0]["item_name"], "Almond Milk")

    def test_clear_purchased_shopping(self):
        # 404 when no plan
        res = self.client.post("/api/shopping/clear-purchased")
        self.assertEqual(res.status_code, 404)

        # Now save a plan with shopping items
        from api.main import save_plan
        test_plan = {
            "menu": [],
            "shopping_list": [
                {"item_name": "Milk", "purchased": True, "amount_needed": "1 gallon"},
                {"item_name": "Eggs", "purchased": False, "amount_needed": "1 doz"},
            ],
        }
        save_plan(test_plan)

        res = self.client.post("/api/shopping/clear-purchased")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["cleared"], 1)
        # Verify only unpurchased item remains
        remaining = data["plan"]["shopping_list"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["item_name"], "Eggs")


    def test_scan_request_succeeds_using_server_keys_when_client_sends_no_key(self):
        """Connected client with no key headers succeeds when server has env provider keys configured."""
        from unittest.mock import patch
        import io
        from PIL import Image

        # Ensure server has an env key configured
        with patch.dict(os.environ, {"GEMINI_API_KEY": "server-env-key-12345"}):
            with patch("api.ai_fallback._call_gemini") as mock_gemini:
                mock_gemini.return_value = '{"items": [{"item_name": "Milk", "category": "Dairy", "quantity": 1.0, "unit": "gallon"}]}'

                # Create dummy image bytes
                img = Image.new("RGB", (32, 32), color="blue")
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                buf.seek(0)

                # Client sends NO x-gemini-key, x-groq-key, or x-openrouter-key headers
                res = self.client.post(
                    "/api/scan-photo",
                    data={"location": "Fridge"},
                    files={"file": ("shelf.jpg", buf, "image/jpeg")},
                )
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["added"], 1)
                self.assertEqual(data["served_by"], "gemini")
                self.assertEqual(data["items"][0]["item_name"], "Milk")

    def test_fresh_db_boot_all_lists_empty(self):
        """Fresh database boot: inventory empty, saved_plans empty, latest plan payload returns None."""
        from api.main import get_inventory, get_latest_plan, latest_plan_payload
        # Verify direct DB functions
        self.assertEqual(get_inventory(), [])
        plan_id, created_at, plan = get_latest_plan()
        self.assertIsNone(plan_id)
        self.assertIsNone(created_at)
        self.assertIsNone(plan)

        # Verify API endpoints
        inv_res = self.client.get("/api/inventory")
        self.assertEqual(inv_res.status_code, 200)
        self.assertEqual(inv_res.json(), [])

        plan_res = self.client.get("/api/plan/latest")
        self.assertEqual(plan_res.status_code, 200)
        self.assertEqual(plan_res.json(), {"plan_id": None, "created_at": None, "plan": None})

    def test_existing_db_boot_inventory_and_settings_preserved(self):
        """Upgrade safety: existing inventory and settings survive untouched across init_db."""
        import sqlite3
        from api.main import DB_FILE, init_db, get_inventory, get_settings, add_inventory_items, DetectedItem

        # Add existing user inventory and customize settings
        add_inventory_items("Fridge", [
            DetectedItem(item_name="Ground Beef", category="Protein", quantity=2.0, unit="lbs")
        ])
        conn = sqlite3.connect(DB_FILE)
        conn.execute("UPDATE settings SET base_headcount = 4 WHERE id = 1")
        conn.commit()
        conn.close()

        # Re-run init_db (simulating app boot/upgrade on existing database)
        init_db()

        inv = get_inventory()
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv[0]["item_name"], "Ground Beef")
        self.assertEqual(inv[0]["quantity"], 2.0)

        settings = get_settings()
        self.assertEqual(settings["base_headcount"], 4)

    def test_plan_menu_shopping_list_contains_only_plan_minus_inventory(self):
        """When menu plan is saved, shopping list derives strictly from the saved plan and contains only needed items."""
        from api.main import save_plan, get_latest_plan, latest_plan_payload

        # Save a plan where 2 items are needed (e.g. Avocado and Sourdough Bread)
        test_plan = {
            "menu": [
                {
                    "day": "Monday",
                    "headcount": 2,
                    "breakfast": {"dish_name": "Avocado Toast", "cook_time_minutes": 10, "prep_steps": ["Toast bread", "Mash avocado"]},
                    "lunch": None,
                    "dinner": None,
                    "ingredients_to_deduct": [],
                    "cooked": False,
                }
            ],
            "shopping_list": [
                {
                    "item_name": "Avocados",
                    "category": "Veggies & Produce",
                    "amount_needed": "2 count",
                    "numeric_quantity": 2.0,
                    "unit": "count",
                    "default_location": "Fridge",
                    "inventory_category": "Produce/Veggies",
                    "reason": "For Monday breakfast",
                    "purchased": False,
                },
                {
                    "item_name": "Sourdough Bread",
                    "category": "Pantry/Dry",
                    "amount_needed": "1 loaf",
                    "numeric_quantity": 1.0,
                    "unit": "loaf",
                    "default_location": "Cupboard / Pantry",
                    "inventory_category": "Pantry/Dry",
                    "reason": "For Monday breakfast",
                    "purchased": False,
                },
            ],
            "nutrition_notes": "Whole food balanced breakfast",
        }
        save_plan(test_plan)

        payload = latest_plan_payload()
        self.assertIsNotNone(payload["plan_id"])
        self.assertIsNotNone(payload["plan"])
        shop_items = [i["item_name"] for i in payload["plan"]["shopping_list"]]
        self.assertEqual(shop_items, ["Avocados", "Sourdough Bread"])


if __name__ == "__main__":
    unittest.main()

