from __future__ import annotations

import hmac
import json
import secrets
import struct
from datetime import datetime, timezone
from hashlib import sha1, sha256
from io import BytesIO

import frappe
from frappe.utils import get_datetime, now_datetime
from frappe.utils.password import get_decrypted_password


DEFAULT_TOTP_STEP_SECONDS = 30
MIN_TOTP_STEP_SECONDS = 30
MAX_TOTP_STEP_SECONDS = 45
TOTP_DIGITS = 6


def generate_session_secret() -> str:
    return secrets.token_bytes(32).hex()


def get_totp_step_seconds() -> int:
    configured = int(frappe.conf.get("attendance_totp_step_seconds") or DEFAULT_TOTP_STEP_SECONDS)
    return max(MIN_TOTP_STEP_SECONDS, min(configured, MAX_TOTP_STEP_SECONDS))


def calculate_totp(secret_hex: str, for_time=None, step_seconds: int | None = None, digits: int = TOTP_DIGITS) -> str:
    return calculate_totp_bytes(
        bytes.fromhex(secret_hex),
        for_time=for_time,
        step_seconds=step_seconds,
        digits=digits,
    )


def calculate_totp_bytes(secret: bytes, for_time=None, step_seconds: int | None = None, digits: int = TOTP_DIGITS) -> str:
    timestamp = _timestamp(for_time)
    step = step_seconds or get_totp_step_seconds()
    counter = int(timestamp // step)
    return _hotp(secret, counter, digits=digits)


def _hotp(secret: bytes, counter: int, digits: int = TOTP_DIGITS) -> str:
    digest = hmac.new(secret, struct.pack(">Q", counter), sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def build_qr_payload(local_session, issued_at=None) -> dict:
    issued = get_datetime(issued_at) if issued_at else now_datetime()
    secret = get_session_secret(local_session.name)
    payload = {
        "session_id": local_session.attendance_session_id,
        "totp_value": calculate_totp(secret, for_time=issued),
        "issued_at": issued.isoformat(),
    }
    payload["signature"] = sign_payload(secret, payload)
    return payload


def sign_payload(secret_hex: str, payload: dict) -> str:
    unsigned = _canonical_unsigned_payload(payload)
    return hmac.new(bytes.fromhex(secret_hex), unsigned.encode("utf-8"), sha256).hexdigest()


def verify_payload_signature(secret_hex: str, payload: dict) -> bool:
    provided = payload.get("signature") or ""
    expected = sign_payload(secret_hex, payload)
    return hmac.compare_digest(provided, expected)


def validate_qr_payload(local_session, payload: dict, reference_time=None) -> tuple[bool, str | None]:
    if not isinstance(payload, dict):
        return False, "invalid_payload"
    for key in ("session_id", "totp_value", "issued_at", "signature"):
        if not payload.get(key):
            return False, f"missing_{key}"
    if payload["session_id"] not in {local_session.attendance_session_id, local_session.session_id}:
        return False, "session_mismatch"

    secret = get_session_secret(local_session.name)
    if not verify_payload_signature(secret, payload):
        return False, "invalid_signature"

    now = get_datetime(reference_time) if reference_time else now_datetime()
    issued_at = get_datetime(payload["issued_at"])
    if _timestamp(issued_at) > _timestamp(now) + 1:
        return False, "future_qr_payload"

    step = get_totp_step_seconds()
    valid_values = {
        calculate_totp(secret, for_time=now, step_seconds=step),
        calculate_totp(secret, for_time=_from_timestamp(_timestamp(now) - step), step_seconds=step),
    }
    if payload["totp_value"] not in valid_values:
        return False, "expired_or_invalid_totp"
    return True, None


@frappe.whitelist()
def get_qr_frame(attendance_session_id: str) -> dict:
    session = _get_local_session(attendance_session_id)
    if session.status != "Open":
        frappe.throw("Session is not open.")
    payload = build_qr_payload(session)
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "session_id": session.attendance_session_id,
        "payload": payload,
        "payload_json": payload_json,
        "qr_svg": render_qr_svg(payload_json),
        "refresh_seconds": get_totp_step_seconds(),
    }


def render_qr_svg(payload_json: str) -> str:
    from pyqrcode import create as qrcreate

    qr = qrcreate(payload_json, error="Q")
    stream = BytesIO()
    try:
        qr.svg(stream, scale=10, module_color="#111111", background="#ffffff")
        return stream.getvalue().decode("utf-8")
    finally:
        stream.close()


def get_session_secret(local_session_name: str) -> str:
    secret = get_decrypted_password("Local Session", local_session_name, "secret_session", raise_exception=False)
    if not secret:
        frappe.throw("Secret session absent.")
    return secret


def _canonical_unsigned_payload(payload: dict) -> str:
    return json.dumps(
        {
            "issued_at": payload.get("issued_at"),
            "session_id": payload.get("session_id"),
            "totp_value": payload.get("totp_value"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _get_local_session(identifier: str):
    name = (
        frappe.db.exists("Local Session", identifier)
        or frappe.db.exists("Local Session", {"attendance_session_id": identifier})
        or frappe.db.exists("Local Session", {"session_id": identifier})
    )
    if not name:
        frappe.throw("Session locale introuvable.")
    return frappe.get_doc("Local Session", name)


def _timestamp(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    dt = get_datetime(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _from_timestamp(timestamp: int):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
