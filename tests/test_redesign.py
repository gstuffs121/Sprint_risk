import unittest
from werkzeug.security import generate_password_hash
from app import app
from database import init_db, get_db_connection, get_dict_cursor
from utils.create_admin import provision_admin


class SprintAIRedesignTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret-key-security-testing"
        )
        init_db()

    def setUp(self):
        self.client = app.test_client()

    def test_health_check(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")

    def test_public_and_workspace_routes(self):
        routes = ["/", "/sprints", "/tasks", "/predictions", "/reports", "/login", "/register"]
        for r in routes:
            res = self.client.get(r)
            self.assertEqual(res.status_code, 200, f"Route {r} failed to render")

    def test_registration_privilege_escalation_blocked(self):
        """Verify that public registration rejects or neutralizes attempts to claim admin or privileged roles."""
        conn = get_db_connection()
        cur = get_dict_cursor(conn)
        # Clean test user if exists
        cur.execute("DELETE FROM users WHERE username = 'hacker_admin'")
        conn.commit()

        # Malicious registration payload attempting privilege escalation
        payload = {
            "username": "hacker_admin",
            "email": "hacker@domain.com",
            "full_name": "Attacker",
            "password": "password12345",
            "confirm_password": "password12345",
            "role": "admin"  # Malicious parameter injection
        }
        res = self.client.post("/register", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Query database directly to verify stored role
        cur.execute("SELECT role FROM users WHERE username = 'hacker_admin'")
        user_row = cur.fetchone()
        self.assertIsNotNone(user_row, "User should be created")
        self.assertEqual(user_row["role"], "user", "Privilege escalation failed: Role MUST be 'user'")

        # Clean up
        cur.execute("DELETE FROM users WHERE username = 'hacker_admin'")
        conn.commit()
        cur.close()
        conn.close()

    def test_login_demo_bypass_removed(self):
        """Verify that demo shortcuts or passwords bypasses do not exist."""
        # Attempt login with legacy demo_role
        res = self.client.post("/login", data={"demo_role": "admin"})
        # Should stay on login page with error, not redirect to admin
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Please enter both username/email and password", res.data)

        # Attempt login with missing password
        res = self.client.post("/login", data={"username": "admin", "password": ""})
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Please enter both username/email and password", res.data)

    def test_admin_access_restrictions(self):
        """Verify server-side authorization blocks unauthenticated, user, and scrum_master roles from /admin."""
        # 1. Unauthenticated request to /admin/
        res = self.client.get("/admin/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.headers.get("Location", ""))

        # 2. Regular user (role = 'user')
        with self.client.session_transaction() as sess:
            sess["user_id"] = 101
            sess["username"] = "dev_user"
            sess["role"] = "user"

        res = self.client.get("/admin/")
        self.assertEqual(res.status_code, 302)
        self.assertNotIn("/admin", res.headers.get("Location", ""))

        # Regular user attempting admin operations via POST
        res = self.client.post("/admin/ai/retrain")
        self.assertEqual(res.status_code, 302)
        self.assertNotIn("/admin", res.headers.get("Location", ""))

        res = self.client.post("/admin/settings", data={"setting_maintenance_mode": "true"})
        self.assertEqual(res.status_code, 302)

        # 3. Scrum master (role = 'scrum_master') cannot access /admin
        with self.client.session_transaction() as sess:
            sess["user_id"] = 102
            sess["username"] = "scrum_user"
            sess["role"] = "scrum_master"

        res = self.client.get("/admin/")
        self.assertEqual(res.status_code, 302)
        self.assertNotIn("/admin", res.headers.get("Location", ""))

        # 4. Verified Admin (role = 'admin') IS allowed
        with self.client.session_transaction() as sess:
            sess["user_id"] = 100
            sess["username"] = "verified_admin"
            sess["role"] = "admin"

        admin_endpoints = [
            "/admin/",
            "/admin/users",
            "/admin/sprints",
            "/admin/tasks",
            "/admin/ai",
            "/admin/logs",
            "/admin/health",
            "/admin/settings"
        ]
        for ep in admin_endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Admin endpoint {ep} should be accessible to role=admin")

    def test_secure_admin_provisioning_mechanism(self):
        """Verify the secure CLI administrator provisioning mechanism with password validation."""
        # Weak password (<8 chars) must be rejected
        with self.assertRaises(ValueError):
            provision_admin("bad_admin", "bad@test.com", "short")

        # Provision valid test admin
        conn = get_db_connection()
        cur = get_dict_cursor(conn)
        cur.execute("DELETE FROM users WHERE username = 'cli_admin_test'")
        conn.commit()

        new_admin_id = provision_admin("cli_admin_test", "cli_admin@test.com", "StrongAdminPassword123!", "CLI Administrator")
        self.assertIsInstance(new_admin_id, int)

        # Verify role in DB is admin
        cur.execute("SELECT role, is_active FROM users WHERE id = %s", (new_admin_id,))
        user_row = cur.fetchone()
        self.assertEqual(user_row["role"], "admin")
        self.assertEqual(user_row["is_active"], 1)

        # Verify audit log recorded
        cur.execute("SELECT action FROM audit_logs WHERE action = 'ADMIN_PROVISIONED_SECURELY'")
        log_row = cur.fetchone()
        self.assertIsNotNone(log_row)

        # Clean up
        cur.execute("DELETE FROM users WHERE id = %s", (new_admin_id,))
        conn.commit()
        cur.close()
        conn.close()

    def test_api_predict(self):
        payload = {
            "complexity": 4,
            "priority": "High",
            "dependencies": 2,
            "days_remaining": 4,
            "team_workload": 80
        }
        res = self.client.post("/api/predict", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("predicted_hours", data)
        self.assertIn("risk_probability", data)
        self.assertIn("risk_level", data)

    def test_chart_data_api(self):
        res = self.client.get("/api/chart-data")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("task_distribution", data)
        self.assertIn("risk_distribution", data)


if __name__ == "__main__":
    unittest.main()
