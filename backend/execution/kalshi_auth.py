"""Kalshi API authentication using RSA-PSS signatures.

Kalshi requires RSA-PSS signed headers for all authenticated endpoints.
The signature covers: timestamp + method + path (no body).
"""
import base64
import logging
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger(__name__)


def load_private_key(path: str) -> tuple:
    """Load an RSA private key from a PEM file.

    Returns (key, error) tuple.
    """
    try:
        with open(path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            return None, f"Key at {path} is not an RSA private key"
        return key, None
    except FileNotFoundError:
        return None, f"Private key file not found: {path}"
    except Exception as e:
        return None, f"Failed to load private key: {e}"


def load_private_key_from_string(pem_data: str) -> tuple:
    """Load an RSA private key from a PEM string.

    Returns (key, error) tuple.
    """
    try:
        key = serialization.load_pem_private_key(pem_data.encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            return None, "Provided key is not an RSA private key"
        return key, None
    except Exception as e:
        return None, f"Failed to load private key: {e}"


def sign_request(private_key: rsa.RSAPrivateKey, timestamp: str, method: str, path: str) -> tuple:
    """Generate RSA-PSS signature for Kalshi API authentication.

    The message format is: timestamp + method_uppercase + path
    Signed with RSA-PSS using SHA-256 and maximum salt length.

    Returns (base64_signature, error) tuple.
    """
    try:
        message = (timestamp + method.upper() + path).encode("utf-8")
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8"), None
    except Exception as e:
        return None, f"Failed to sign request: {e}"


def build_auth_headers(api_key_id: str, signature: str, timestamp: str) -> dict:
    """Build the authentication headers for a Kalshi API request."""
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }


def get_current_timestamp() -> str:
    """Return the current Unix timestamp as a string (seconds)."""
    return str(int(time.time()))
