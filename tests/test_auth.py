import pytest
from datetime import timedelta, datetime, UTC
import jwt

from fastapi import HTTPException, status

from auth import (
    hash_password,
    verify_password,
    generate_reset_token,
    hash_reset_token,
    create_access_token,
    verify_access_token,
    get_current_user,
)
from config import settings
from models import User


# =====================================================================
# 1️⃣ PASSWORD HASHING TESTS
# =====================================================================
def test_hash_and_verify_password():
    """Ensures passwords are hashed and correctly verified."""
    plain = "super_secret_password"
    hashed = hash_password(plain)

    assert hashed != plain
    assert verify_password(plain, hashed) is True
    assert verify_password("wrong_password", hashed) is False


# =====================================================================
# 2️⃣ RESET TOKEN TESTS
# =====================================================================
def test_generate_and_hash_reset_token():
    """Validates token generation and SHA-256 hashing."""
    token = generate_reset_token()
    assert len(token) > 30  # secrets.token_urlsafe(32) yields 43 chars

    token_hash = hash_reset_token(token)
    assert len(token_hash) == 64  # SHA-256 hexdigest is always 64 chars
    assert hash_reset_token("different_token") != token_hash


# =====================================================================
# 3️⃣ ACCESS TOKEN CREATION & VERIFICATION TESTS
# =====================================================================
def test_create_access_token_with_default_expiry():
    """Covers the 'else' branch of expires_delta in create_access_token."""
    data = {"sub": "123"}
    token = create_access_token(data)

    payload = jwt.decode(
        token, settings.secret_key.get_secret_value(), algorithms=[settings.algorithm]
    )
    assert payload["sub"] == "123"
    assert "exp" in payload


def test_create_access_token_with_custom_expiry():
    """Covers the 'if expires_delta' branch in create_access_token."""
    data = {"sub": "123"}
    custom_delta = timedelta(hours=1)
    token = create_access_token(data, expires_delta=custom_delta)

    payload = jwt.decode(
        token, settings.secret_key.get_secret_value(), algorithms=[settings.algorithm]
    )
    assert payload["sub"] == "123"
    assert "exp" in payload


def test_verify_access_token_valid():
    """Ensures a correctly signed token returns the 'sub' claim."""
    data = {"sub": "123"}
    token = create_access_token(data)
    assert verify_access_token(token) == "123"


def test_verify_access_token_invalid():
    """🎯 TARGET: Covers lines 65-66 (jwt.InvalidTokenError -> return None)."""
    # Test 1: Completely garbage string
    assert verify_access_token("invalid_token_string") is None

    # Test 2: Token signed with the wrong secret key
    wrong_payload = {"sub": "123", "exp": datetime.now(UTC) + timedelta(minutes=30)}
    wrong_token = jwt.encode(
        wrong_payload, "wrong_secret_key", algorithm=settings.algorithm
    )
    assert verify_access_token(wrong_token) is None


def test_verify_access_token_missing_claims():
    """🎯 TARGET: Covers lines 65-66 via missing required claims."""
    # The verify function requires both "exp" and "sub". Missing them triggers InvalidTokenError.
    payload = {"other": "data"}
    token = jwt.encode(
        payload, settings.secret_key.get_secret_value(), algorithm=settings.algorithm
    )
    assert verify_access_token(token) is None


# =====================================================================
# 4️⃣ GET CURRENT USER TESTS (The Core Missing Coverage)
# =====================================================================
@pytest.mark.anyio
async def test_get_current_user_success(db_session):
    """🎯 TARGET: Covers lines 90-92, 100 (Successful DB lookup and return)."""
    new_user = User(
        username="testuser",
        email="test@example.com",
        password_hash=hash_password("password123"),
    )
    db_session.add(new_user)
    await db_session.commit()
    await db_session.refresh(new_user)

    token = create_access_token(data={"sub": str(new_user.id)})
    user = await get_current_user(token=token, db=db_session)

    assert user.id == new_user.id
    assert user.username == "testuser"


@pytest.mark.anyio
async def test_get_current_user_invalid_token(db_session):
    """🎯 TARGET: Covers lines 75-81 (verify_access_token returns None -> HTTP 401)."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token="invalid_token", db=db_session)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid or expired token"


@pytest.mark.anyio
async def test_get_current_user_non_integer_sub(db_session):
    """🎯 TARGET: Covers lines 83-89 (ValueError on int() conversion -> HTTP 401)."""
    # Create a token where 'sub' is a string that cannot be cast to int
    token = create_access_token(data={"sub": "not_an_integer"})

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=db_session)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid or expired token"


@pytest.mark.anyio
async def test_get_current_user_not_found_in_db(db_session):
    """🎯 TARGET: Covers lines 93-99 (Valid token, but user ID doesn't exist in DB -> HTTP 401)."""
    # Use an arbitrarily high ID that does not exist in the test database
    token = create_access_token(data={"sub": "99999"})

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=db_session)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "User not found"
