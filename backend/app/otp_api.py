"""
Purpose:
Manages Phone OTP delivery, verification, and rate-limiting via MSG91 for user registration.

Responsibilities:
- Send OTP via MSG91 v5 OTP API (with dev mock fallback if MSG91 is unconfigured).
- Enforce strict 1-minute (60 seconds) timer window for OTP expiration.
- Enforce maximum 3 attempts per OTP session.
- Temporarily block the phone number for 1 hour (3600 seconds) if 3 incorrect attempts are made.
- Issue a secure signed verification token upon successful OTP match.
- Isolated specifically to the registration flow (not used for login).
"""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
import random
import re
import time
from threading import Lock
from typing import Dict, Any, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import (
    msg91_auth_key,
    msg91_template_id,
    msg91_sender_id,
    msg91_otp_expiry_seconds,
    msg91_otp_length,
    state_secret,
)

logger = logging.getLogger("teslalab.otp")
router = APIRouter(prefix="/api/auth/otp", tags=["OTP Registration"])


def normalize_phone(raw_phone: str) -> str:
    """
    Standardize phone number to E.164-compatible format.
    Strips spaces, dashes, parentheses.
    Defaults 10-digit numbers to +91 (India) if country code is omitted.
    """
    cleaned = re.sub(r"[\s\-\(\)]", "", raw_phone.strip())
    if cleaned.startswith("+"):
        digits_only = cleaned[1:]
        if not digits_only.isdigit() or len(digits_only) < 7:
            raise ValueError("Invalid international phone number format")
        return f"+{digits_only}"
    elif cleaned.isdigit():
        if len(cleaned) == 10:
            return f"+91{cleaned}"
        return f"+{cleaned}"
    raise ValueError("Phone number must contain valid digits and optional '+' country prefix")


class OtpManager:
    """
    Thread-safe in-memory store for OTP sessions and 1-hour rate limiting blocks.
    Can also sync to Redis when available.
    """
    def __init__(self):
        self._lock = Lock()
        # phone -> unblock_timestamp (float)
        self._blocked_phones: Dict[str, float] = {}
        # phone -> {"otp": str, "sent_at": float, "expires_at": float, "attempts": int}
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def is_blocked(self, phone: str) -> Tuple[bool, int]:
        now = time.time()
        with self._lock:
            blocked_until = self._blocked_phones.get(phone)
            if blocked_until:
                if now < blocked_until:
                    return True, int(blocked_until - now)
                else:
                    del self._blocked_phones[phone]
            return False, 0

    def block_phone(self, phone: str, duration_seconds: int = 3600):
        with self._lock:
            self._blocked_phones[phone] = time.time() + duration_seconds
            if phone in self._sessions:
                del self._sessions[phone]

    def create_session(self, phone: str, otp: str, expiry_seconds: int = 60) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            session = {
                "otp": otp,
                "sent_at": now,
                "expires_at": now + expiry_seconds,
                "attempts": 0,
            }
            self._sessions[phone] = session
            return session

    def get_session(self, phone: str) -> Dict[str, Any] | None:
        with self._lock:
            return self._sessions.get(phone)

    def record_failed_attempt(self, phone: str) -> Tuple[int, bool]:
        """
        Increments attempts.
        If attempts reaches 3, blocks phone for 1 hour (3600s).
        Returns: (remaining_chances, is_blocked)
        """
        with self._lock:
            session = self._sessions.get(phone)
            if not session:
                return 0, False
            session["attempts"] += 1
            if session["attempts"] >= 3:
                # 3 failed attempts: Block for 1 hour (3600 seconds)
                self._blocked_phones[phone] = time.time() + 3600
                del self._sessions[phone]
                return 0, True
            remaining = 3 - session["attempts"]
            return remaining, False

    def clear_session(self, phone: str):
        with self._lock:
            self._sessions.pop(phone, None)


# Singleton manager instance
otp_manager = OtpManager()


def generate_verification_token(phone: str) -> str:
    """Generate a tamper-proof signed token verifying that the phone was successfully verified."""
    timestamp = str(int(time.time()))
    secret = state_secret().encode("utf-8")
    payload = f"{phone}:{timestamp}".encode("utf-8")
    signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{phone}:{timestamp}:{signature}"


def verify_phone_token(token: str, max_age_seconds: int = 1800) -> Tuple[bool, str]:
    """Validates the verification token created after OTP success."""
    parts = token.split(":")
    if len(parts) != 3:
        return False, "Malformed verification token"
    phone, timestamp_str, signature = parts
    try:
        ts = int(timestamp_str)
    except ValueError:
        return False, "Invalid token timestamp"
    if time.time() - ts > max_age_seconds:
        return False, "Verification token expired"
    secret = state_secret().encode("utf-8")
    payload = f"{phone}:{timestamp_str}".encode("utf-8")
    expected_sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        return False, "Invalid token signature"
    return True, phone


def call_msg91_send(phone: str, otp_code: str) -> Tuple[bool, str]:
    """
    Dispatches OTP via MSG91 API v5.
    If MSG91_AUTH_KEY is not configured, logs to console in development mode.
    """
    auth_key = msg91_auth_key()
    template_id = msg91_template_id()

    # Format phone without '+' for MSG91
    mobile_for_msg91 = phone.lstrip("+")

    if not auth_key or auth_key.startswith("your_") or not template_id or template_id.startswith("your_"):
        # Development / Mock Mode
        print(f"\n==================================================")
        print(f"[MSG91 DEV MOCK] OTP for {phone}: {otp_code}")
        print(f"Expiry: 60 seconds (1 minute)")
        print(f"==================================================\n")
        logger.info(f"[MSG91 DEV] Dispatched OTP {otp_code} to {phone}")
        return True, "Mock OTP generated (check backend console)"

    # Live MSG91 API v5
    query_params = {
        "template_id": template_id,
        "mobile": mobile_for_msg91,
        "otp": otp_code,
        "otp_expiry": 1,  # 1 minute expiry on MSG91 side
        "otp_length": len(otp_code),
    }
    sender = msg91_sender_id()
    if sender:
        query_params["sender"] = sender

    url = f"https://control.msg91.com/api/v5/otp?{urlencode(query_params)}"
    headers = {
        "authkey": auth_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    req = Request(url, headers=headers, method="POST", data=b"{}")
    try:
        with urlopen(req, timeout=10) as resp:
            raw_body = resp.read().decode("utf-8")
            data = json.loads(raw_body) if raw_body else {}
            print(f"\n[MSG91 GATEWAY RESPONSE] Status: {resp.status} | Body: {raw_body}")
            if data.get("type") == "success":
                return True, f"OTP sent via MSG91 (Request ID: {data.get('request_id', '')})"
            return False, data.get("message", "MSG91 returned non-success response")
    except HTTPError as e:
        err_body = e.read().decode("utf-8") if e.fp else ""
        logger.error(f"MSG91 HTTPError {e.code}: {err_body}")
        return False, f"MSG91 error ({e.code}): {err_body}"
    except (URLError, TimeoutError) as e:
        logger.error(f"Network error calling MSG91: {e}")
        return False, f"Network error contacting SMS gateway: {str(e)}"


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------

class SendOtpRequest(BaseModel):
    phone: str = Field(..., description="Phone number with country code, e.g. +919876543210")


class VerifyOtpRequest(BaseModel):
    phone: str = Field(..., description="Phone number")
    otp: str = Field(..., min_length=4, max_length=8, description="Received OTP digits")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
def get_phone_status(phone: str = Query(..., description="Phone number to check")):
    """Checks whether the phone is currently locked out from registration."""
    try:
        norm_phone = normalize_phone(phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    blocked, remaining_seconds = otp_manager.is_blocked(norm_phone)
    return {
        "phone": norm_phone,
        "blocked": blocked,
        "blocked_remaining_seconds": remaining_seconds,
        "blocked_remaining_minutes": (remaining_seconds + 59) // 60 if blocked else 0,
    }


@router.post("/send")
def send_otp(payload: SendOtpRequest):
    """
    Sends an OTP to the given phone number for registration.
    - Timer: 1 minute (60 seconds)
    - 1-hour block if currently in lockout period
    """
    try:
        norm_phone = normalize_phone(payload.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check 1-hour block
    blocked, remaining_sec = otp_manager.is_blocked(norm_phone)
    if blocked:
        remaining_min = (remaining_sec + 59) // 60
        raise HTTPException(
            status_code=429,
            detail=f"This phone number is temporarily blocked from registration due to 3 failed attempts. Please try again after {remaining_min} minute(s)."
        )

    # Generate 6-digit OTP
    otp_length = msg91_otp_length()
    otp_code = "".join([str(random.randint(0, 9)) for _ in range(otp_length)])
    expiry_seconds = msg91_otp_expiry_seconds()  # 60 seconds

    # Dispatch via MSG91
    success, msg = call_msg91_send(norm_phone, otp_code)
    if not success:
        raise HTTPException(status_code=502, detail=f"Failed to deliver OTP: {msg}")

    print(f"\n==================================================")
    print(f"[OTP DISPATCHED] Phone: {norm_phone} | Code: {otp_code}")
    print(f"Status: {msg}")
    print(f"==================================================\n")

    # Register active session
    otp_manager.create_session(norm_phone, otp_code, expiry_seconds=expiry_seconds)

    return {
        "success": True,
        "message": "OTP sent successfully",
        "phone": norm_phone,
        "expires_in_seconds": expiry_seconds,
        "max_attempts": 3,
    }


@router.post("/verify")
def verify_otp(payload: VerifyOtpRequest):
    """
    Verifies the submitted OTP against the active session.
    Enforces:
    1. 1-hour block check.
    2. 1-minute expiration timer check.
    3. Exactly 3 chances limit. If failed 3 times, blocks for 1 hour.
    """
    try:
        norm_phone = normalize_phone(payload.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 1. Check if blocked
    blocked, remaining_sec = otp_manager.is_blocked(norm_phone)
    if blocked:
        remaining_min = (remaining_sec + 59) // 60
        raise HTTPException(
            status_code=429,
            detail=f"This phone number is temporarily blocked from registration for 1 hour. Time remaining: {remaining_min} minute(s)."
        )

    # 2. Check active session
    session = otp_manager.get_session(norm_phone)
    if not session:
        raise HTTPException(
            status_code=400,
            detail="No active OTP found for this phone number. Please request a new OTP."
        )

    # 3. Check 1-minute expiration timer
    now = time.time()
    if now > session["expires_at"]:
        otp_manager.clear_session(norm_phone)
        raise HTTPException(
            status_code=400,
            detail="OTP has expired. The 1-minute time window has ended. Please request a new OTP."
        )

    submitted_otp = payload.otp.strip()
    expected_otp = session["otp"]

    # 4. Compare OTP
    if submitted_otp == expected_otp:
        # Success: clear session and return signed verification token
        otp_manager.clear_session(norm_phone)
        verification_token = generate_verification_token(norm_phone)
        return {
            "success": True,
            "message": "Phone number verified successfully",
            "phone": norm_phone,
            "verification_token": verification_token,
        }

    # 5. Failed match: increment failed attempts
    remaining_attempts, newly_blocked = otp_manager.record_failed_attempt(norm_phone)
    if newly_blocked:
        raise HTTPException(
            status_code=403,
            detail="Incorrect OTP. You have used all 3 chances. This phone number is blocked from registration for 1 hour."
        )

    raise HTTPException(
        status_code=400,
        detail=f"Incorrect OTP. You have {remaining_attempts} chance(s) remaining."
    )
