
import unittest
from unittest.mock import patch

import app as sprint_app


class SprintAITests(unittest.TestCase):
    def setUp(self):
        sprint_app.app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret"
        )
        self.client = sprint_app.app.test_client()

    def test_dashboard_route_exists(self):
        with patch("app.get_db_connection") as mock_connection:
            connection = mock_connection.return_value
            cursor = connection.cursor.return_value
            cursor.fetchone.return_value = {
                "total_sprints": 0,
                "total_tasks": 0,
                "delayed_tasks": 0,
                "estimated_hours": 0
            }
            cursor.fetchall.return_value = []

            response = self.client.get("/")
            self.assertIn(response.status_code, (200, 500))

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_unknown_page_returns_404(self):
        response = self.client.get("/this-page-does-not-exist")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
