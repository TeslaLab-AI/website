import unittest
from unittest.mock import patch
from fastapi import HTTPException
from app.github_api import remove_repository

class TestRemoveRepository(unittest.TestCase):
    def test_remove_repository_missing_auth(self):
        with self.assertRaises(HTTPException) as ctx:
            remove_repository("repo-123", authorization=None)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Authentication required", ctx.exception.detail)

    def test_remove_repository_invalid_auth_header(self):
        with self.assertRaises(HTTPException) as ctx:
            remove_repository("repo-123", authorization="Basic 12345")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Authentication required", ctx.exception.detail)

    @patch("app.github_api._authenticated_user_id")
    @patch("app.github_api._workspace_id_for_user")
    @patch("app.github_api._json_request")
    def test_remove_repository_success(self, mock_json_request, mock_workspace_id, mock_user_id):
        mock_user_id.return_value = "user-1"
        mock_workspace_id.return_value = "ws-1"
        mock_json_request.return_value = (204, None)

        res = remove_repository("repo-123", authorization="Bearer token123")
        self.assertEqual(res, {"status": "success", "message": "Repository removed"})

        self.assertTrue(mock_json_request.called)
        called_url, kwargs = mock_json_request.call_args[0][0], mock_json_request.call_args[1]
        self.assertIn("id=eq.repo-123", called_url)
        self.assertIn("workspace_id=eq.ws-1", called_url)
        self.assertEqual(kwargs.get("method"), "DELETE")

    @patch("app.github_api._authenticated_user_id")
    @patch("app.github_api._workspace_id_for_user")
    @patch("app.github_api._json_request")
    def test_remove_repository_db_error(self, mock_json_request, mock_workspace_id, mock_user_id):
        mock_user_id.return_value = "user-1"
        mock_workspace_id.return_value = "ws-1"
        mock_json_request.return_value = (500, None)

        with self.assertRaises(HTTPException) as ctx:
            remove_repository("repo-123", authorization="Bearer token123")
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("Failed to remove repository", ctx.exception.detail)

if __name__ == "__main__":
    unittest.main()

