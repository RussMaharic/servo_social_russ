"""
Ephemeral Room Code Generator and Token Authentication Guard.
"""

import secrets
import string
import hmac
import hashlib
from typing import Optional

def generate_room_code(prefix: str = "T2") -> str:
    """Generates an ephemeral 6-character room pairing code."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(4))
    return f"{prefix}-{suffix}"


def generate_gated_pin() -> str:
    """Generates an operator-friendly 6-digit gated passkey PIN (e.g. 742891)."""
    return f"{secrets.randbelow(900000) + 100000}"


class TokenGuard:
    """Validates session tokens, gated PIN handshakes, and room authorizations."""

    def __init__(self, secret_key: Optional[str] = None, pin: Optional[str] = None):
        self.secret_key = secret_key or secrets.token_hex(16)
        if pin:
            clean = str(pin).replace("-", "").strip()
            self.gated_pin = clean if (len(clean) == 6 and clean.isdigit()) else generate_gated_pin()
        else:
            self.gated_pin = generate_gated_pin()

    @property
    def formatted_pin(self) -> str:
        """Returns 6-digit PIN in readable 3-3 format (e.g. 742-891)."""
        return f"{self.gated_pin[:3]}-{self.gated_pin[3:]}"

    def generate_token(self, room_code: str, role: str) -> str:
        """Generates a cryptographic HMAC-SHA256 bearer token for the room."""
        message = f"{room_code}:{role}:{self.gated_pin}".encode("utf-8")
        signature = hmac.new(self.secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return f"{room_code}.{role}.{signature[:16]}"

    def validate_pin(self, candidate_pin: str) -> bool:
        """Validates incoming 6-digit PIN (handles both 123456 and 123-456)."""
        clean = candidate_pin.replace("-", "").strip()
        return hmac.compare_digest(clean, self.gated_pin)

    def validate_token(self, token_or_pin: str, expected_room: str, expected_role: str) -> bool:
        """Validates incoming bearer token OR gated passkey PIN."""
        clean = token_or_pin.strip()
        # Direct PIN match
        if self.validate_pin(clean):
            return True

        # Token match
        try:
            parts = clean.split(".")
            if len(parts) != 3:
                return False
            room, role, sig = parts
            if room != expected_room or role != expected_role:
                return False
            expected_sig = self.generate_token(room, role).split(".")[2]
            return hmac.compare_digest(sig, expected_sig)
        except Exception:
            return False
