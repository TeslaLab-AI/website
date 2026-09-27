"""
Unit tests for MSG91 Registration OTP API:
- 1-minute expiration window
- 3 failed attempts lockout
- 1-hour block enforcement
- Cryptographic verification token generation
"""

import sys
import time
import unittest
from pathlib import Path

_backend_dir = Path(__file__).resolve().parents[1]
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from fastapi.testclient import TestClient

from app.main import app
from app.otp_api import otp_manager, generate_verification_token, verify_phone_token

client = TestClient(app)

TEST_PHONE = "+919999900001"
BLOCKED_TEST_PHONE = "+919999900002"


class TestOtpApi(unittest.TestCase):
    def setUp(self):
        otp_manager.clear_session(TEST_PHONE)
        otp_manager.clear_session(BLOCKED_TEST_PHONE)
        with otp_manager._lock:
            otp_manager._blocked_phones.pop(TEST_PHONE, None)
            otp_manager._blocked_phones.pop(BLOCKED_TEST_PHONE, None)

    def test_send_otp_success(self):
        res = client.post("/api/auth/otp/send", json={"phone": TEST_PHONE})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["phone"], TEST_PHONE)
        self.assertEqual(data["expires_in_seconds"], 60)
        self.assertEqual(data["max_attempts"], 3)

    def test_verify_otp_success(self):
        # 1. Send OTP
        client.post("/api/auth/otp/send", json={"phone": TEST_PHONE})
        session = otp_manager.get_session(TEST_PHONE)
        self.assertIsNotNone(session)
        valid_otp = session["otp"]

        # 2. Verify with correct OTP
        res = client.post("/api/auth/otp/verify", json={"phone": TEST_PHONE, "otp": valid_otp})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("verification_token", data)
        
        # Check token validity
        valid, phone = verify_phone_token(data["verification_token"])
        self.assertTrue(valid)
        self.assertEqual(phone, TEST_PHONE)

    def test_three_failed_attempts_blocks_for_one_hour(self):
        # Send OTP
        client.post("/api/auth/otp/send", json={"phone": TEST_PHONE})
        session = otp_manager.get_session(TEST_PHONE)
        self.assertIsNotNone(session)

        # Attempt 1: wrong OTP
        res1 = client.post("/api/auth/otp/verify", json={"phone": TEST_PHONE, "otp": "000000"})
        self.assertEqual(res1.status_code, 400)
        self.assertIn("2 chance(s) remaining", res1.json()["detail"])

        # Attempt 2: wrong OTP
        res2 = client.post("/api/auth/otp/verify", json={"phone": TEST_PHONE, "otp": "000001"})
        self.assertEqual(res2.status_code, 400)
        self.assertIn("1 chance(s) remaining", res2.json()["detail"])

        # Attempt 3: wrong OTP -> must trigger 1-hour block
        res3 = client.post("/api/auth/otp/verify", json={"phone": TEST_PHONE, "otp": "000002"})
        self.assertEqual(res3.status_code, 403)
        self.assertIn("blocked from registration for 1 hour", res3.json()["detail"])

        # Check status endpoint
        status_res = client.get(f"/api/auth/otp/status?phone={TEST_PHONE}")
        status_data = status_res.json()
        self.assertTrue(status_data["blocked"])
        self.assertGreater(status_data["blocked_remaining_seconds"], 3500)

        # Sending a new OTP must now be rejected
        send_blocked = client.post("/api/auth/otp/send", json={"phone": TEST_PHONE})
        self.assertEqual(send_blocked.status_code, 429)
        self.assertIn("temporarily blocked", send_blocked.json()["detail"])

    def test_otp_expires_after_one_minute(self):
        # Send OTP
        client.post("/api/auth/otp/send", json={"phone": TEST_PHONE})
        session = otp_manager.get_session(TEST_PHONE)
        self.assertIsNotNone(session)
        valid_otp = session["otp"]

        # Manually backdate the session expires_at to simulate 1-minute expiration
        session["expires_at"] = time.time() - 5

        res = client.post("/api/auth/otp/verify", json={"phone": TEST_PHONE, "otp": valid_otp})
        self.assertEqual(res.status_code, 400)
        self.assertIn("expired", res.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
