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
        init_db()

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


if __name__ == "__main__":
    unittest.main()
