"""
Tests de `core/security.py`: hashing de contraseñas (bcrypt) y JWT de
sesión (pyjwt) usados por la autenticación armada desde cero.
"""
import pytest

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_password_roundtrip():
    hashed = hash_password("mi-clave-segura-123")
    assert hashed != "mi-clave-segura-123"
    assert verify_password("mi-clave-segura-123", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("mi-clave-segura-123")
    assert verify_password("otra-clave", hashed) is False


def test_verify_password_handles_corrupt_hash_gracefully():
    # No debe lanzar excepción ante un hash con formato inválido.
    assert verify_password("cualquier-cosa", "no-es-un-hash-bcrypt-valido") is False


def test_create_and_decode_access_token_roundtrip():
    token = create_access_token(user_id=42, email="test@example.com")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["email"] == "test@example.com"


def test_decode_access_token_rejects_garbage():
    assert decode_access_token("esto-no-es-un-jwt") is None


def test_decode_access_token_rejects_token_signed_with_different_secret():
    import jwt as pyjwt

    bad_token = pyjwt.encode({"sub": "1"}, "otro-secreto-distinto", algorithm="HS256")
    assert decode_access_token(bad_token) is None
