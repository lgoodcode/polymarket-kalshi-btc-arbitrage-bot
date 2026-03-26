"""Tests for Kalshi RSA-PSS authentication."""
import sys
import os
import base64
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from execution.kalshi_auth import (
    load_private_key,
    load_private_key_from_string,
    sign_request,
    build_auth_headers,
    get_current_timestamp,
)


@pytest.fixture
def rsa_key_pair():
    """Generate a test RSA key pair."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    pem_data = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_key, pem_data


@pytest.fixture
def rsa_key_file(rsa_key_pair):
    """Write test RSA key to a temporary file."""
    _, pem_data = rsa_key_pair
    with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
        f.write(pem_data)
        path = f.name
    yield path
    os.unlink(path)


@pytest.mark.execution
class TestLoadPrivateKey:
    def test_load_from_file(self, rsa_key_file):
        key, err = load_private_key(rsa_key_file)
        assert key is not None
        assert err is None

    def test_file_not_found(self):
        key, err = load_private_key("/nonexistent/path.pem")
        assert key is None
        assert "not found" in err

    def test_invalid_pem(self):
        with tempfile.NamedTemporaryFile(suffix=".pem", delete=False, mode="w") as f:
            f.write("not a valid key")
            path = f.name
        try:
            key, err = load_private_key(path)
            assert key is None
            assert "Failed to load" in err
        finally:
            os.unlink(path)


@pytest.mark.execution
class TestLoadPrivateKeyFromString:
    def test_load_valid_pem(self, rsa_key_pair):
        _, pem_data = rsa_key_pair
        key, err = load_private_key_from_string(pem_data.decode())
        assert key is not None
        assert err is None

    def test_invalid_pem_string(self):
        key, err = load_private_key_from_string("not a valid key")
        assert key is None
        assert "Failed to load" in err


@pytest.mark.execution
class TestSignRequest:
    def test_sign_and_verify(self, rsa_key_pair):
        private_key, _ = rsa_key_pair
        public_key = private_key.public_key()

        timestamp = "1711400000"
        method = "POST"
        path = "/trade-api/v2/portfolio/orders"

        sig_b64, err = sign_request(private_key, timestamp, method, path)
        assert err is None
        assert sig_b64 is not None

        # Verify the signature with the public key
        signature = base64.b64decode(sig_b64)
        message = (timestamp + method + path).encode("utf-8")
        # Should not raise
        public_key.verify(
            signature,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

    def test_message_format(self, rsa_key_pair):
        """Verify the signature message is timestamp + METHOD + path."""
        private_key, _ = rsa_key_pair
        public_key = private_key.public_key()

        sig_b64, err = sign_request(private_key, "12345", "get", "/portfolio/balance")
        assert err is None

        # Method should be uppercased in the message
        signature = base64.b64decode(sig_b64)
        message = "12345GET/portfolio/balance".encode("utf-8")
        public_key.verify(
            signature,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

    def test_different_inputs_produce_different_signatures(self, rsa_key_pair):
        private_key, _ = rsa_key_pair
        sig1, _ = sign_request(private_key, "100", "GET", "/a")
        sig2, _ = sign_request(private_key, "100", "GET", "/b")
        assert sig1 != sig2


@pytest.mark.execution
class TestBuildAuthHeaders:
    def test_header_keys(self):
        headers = build_auth_headers("key123", "sig456", "1711400000")
        assert headers["KALSHI-ACCESS-KEY"] == "key123"
        assert headers["KALSHI-ACCESS-SIGNATURE"] == "sig456"
        assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1711400000"
        assert headers["Content-Type"] == "application/json"


@pytest.mark.execution
class TestGetCurrentTimestamp:
    def test_returns_string(self):
        ts = get_current_timestamp()
        assert isinstance(ts, str)
        assert int(ts) > 0

    def test_is_reasonable(self):
        ts = int(get_current_timestamp())
        # Should be after 2024
        assert ts > 1700000000
