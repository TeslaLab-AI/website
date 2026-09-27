import time
import pytest
from fastapi import HTTPException
from app.github_install import sign_install_state, verify_install_state

def test_sign_and_verify_install_state():
    secret = "test_secret_123"
    user_id = "user_123"
    workspace_id = "workspace_456"

    # Sign the state
    state = sign_install_state(user_id=user_id, workspace_id=workspace_id, secret=secret)
    assert "." in state

    # Verify the state
    payload = verify_install_state(state, secret)
    assert payload["uid"] == user_id
    assert payload["wid"] == workspace_id
    assert "exp" in payload
    assert payload["exp"] > time.time()

def test_verify_install_state_invalid_signature():
    secret = "test_secret_123"
    state = sign_install_state(user_id="u1", workspace_id="w1", secret=secret)
    
    # Tamper with the state
    body, sig = state.rsplit(".", 1)
    tampered_state = f"{body}.invalid_signature"

    with pytest.raises(HTTPException) as excinfo:
        verify_install_state(tampered_state, secret)
    assert excinfo.value.status_code == 400
    assert "Invalid or expired state" in excinfo.value.detail

def test_verify_install_state_expired():
    secret = "test_secret_123"
    # Create an expired payload manually
    import json, base64, hmac, hashlib
    payload = json.dumps({
        "uid": "u1",
        "wid": "w1",
        "exp": int(time.time()) - 100
    }).encode("utf-8")
    
    body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    state = f"{body}.{signature}"
    
    with pytest.raises(HTTPException) as excinfo:
        verify_install_state(state, secret)
    assert excinfo.value.status_code == 400
    assert "Invalid or expired state" in excinfo.value.detail
