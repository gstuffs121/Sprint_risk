import unittest
from app import app
from database import init_db, get_db_connection, get_dict_cursor


class SprintAIProjectsTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret-key-projects"
        )
        init_db()

    def setUp(self):
        self.client = app.test_client()

    def test_project_listing_and_api(self):
        # 1. HTML view
        res = self.client.get("/projects")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Projects & Initiatives", res.data)

        # 2. JSON API
        res = self.client.get("/api/projects")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(len(data["projects"]) > 0)

    def test_project_crud_lifecycle(self):
        # Create
        unique_key = "TESTPRJ"
        res = self.client.post("/projects", data={
            "name": "Integration Test System",
            "key_code": unique_key,
            "description": "Created during automated project lifecycle testing.",
            "status": "active"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Verify persisted in database
        conn = get_db_connection()
        cur = get_dict_cursor(conn)
        cur.execute("SELECT * FROM projects WHERE key_code = %s", (unique_key,))
        proj = cur.fetchone()
        self.assertIsNotNone(proj, "Project should exist in database")
        proj_id = proj["id"]

        # Detail view
        res = self.client.get(f"/projects/{proj_id}")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Integration Test System", res.data)

        # Edit
        res = self.client.post(f"/projects/{proj_id}/edit", data={
            "name": "Updated Test System",
            "key_code": unique_key,
            "description": "Updated description.",
            "status": "completed"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        cur.execute("SELECT name, status FROM projects WHERE id = %s", (proj_id,))
        updated = cur.fetchone()
        self.assertEqual(updated["name"], "Updated Test System")
        self.assertEqual(updated["status"], "completed")

        # Delete
        res = self.client.post(f"/projects/{proj_id}/delete", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        cur.execute("SELECT id FROM projects WHERE id = %s", (proj_id,))
        self.assertIsNone(cur.fetchone(), "Project should be deleted")

        cur.close()
        conn.close()

    def test_kanban_status_persistence(self):
        # Update task #1 to in_progress
        res = self.client.post("/tasks/1/update-status", json={"status": "in_progress"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["new_status"], "in_progress")

        # Verify DB
        conn = get_db_connection()
        cur = get_dict_cursor(conn)
        cur.execute("SELECT status FROM tasks WHERE id = 1")
        row = cur.fetchone()
        self.assertEqual(row["status"], "in_progress")

        # Update to completed
        res = self.client.post("/tasks/1/update-status", json={"status": "completed"})
        self.assertEqual(res.status_code, 200)
        cur.execute("SELECT status, is_delayed FROM tasks WHERE id = 1")
        row = cur.fetchone()
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["is_delayed"], 0)

        cur.close()
        conn.close()

    def test_admin_projects_oversight(self):
        # Unauthenticated request blocked
        res = self.client.get("/admin/projects")
        self.assertEqual(res.status_code, 302)

        # Authenticated admin request succeeds
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"

        res = self.client.get("/admin/projects")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Project Portfolio Oversight", res.data)


if __name__ == "__main__":
    unittest.main()
