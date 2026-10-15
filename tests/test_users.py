from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
import pprint
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import func, select

import models
from auth import CurrentUser, hash_reset_token
from config import settings
from main import app
from tests.conftest import auth_header, create_test_user, login_user

# =====================================================================
# LINE NUMBERS BELOW REFER TO routers/users.py AS SHOWN IN YOUR COVERAGE
# REPORT (the one rendered at 19:31).
#   "L74-77"  = lines 74 to 77
#   "(False)" = the `if` was NOT taken; "(True)" = the `if` WAS taken
#
# NOTE: your report shows L74-77, L125-162 and L392-428 as missing even
# though tests 2, 4 and 5 below already target them. That report was most
# likely generated BEFORE those tests existed. Delete htmlcov/ + .coverage
# and rerun before trusting it.
# =====================================================================


# ---------------------------------------------------------------------
# Helpers (new)
# ---------------------------------------------------------------------
OTHER_EMAIL = "other@example.com"


async def create_other_user(client: AsyncClient) -> tuple[dict, str]:
    user = await create_test_user(client, username="other", email=OTHER_EMAIL)
    token = await login_user(client, email=OTHER_EMAIL)
    return user, token


def make_image_bytes(fmt: str = "PNG") -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 64), "red").save(buf, format=fmt)
    return buf.getvalue()


async def upload_picture(
    client: AsyncClient,
    user_id: int,
    token: str,
    data: bytes | None = None,
):
    return await client.patch(
        f"/api/users/{user_id}/picture",
        files={"file": ("p.png", BytesIO(data or make_image_bytes()), "image/png")},
        headers=auth_header(token),
    )


async def count_reset_tokens(db_session, user_id: int) -> int:
    result = await db_session.execute(
        select(func.count())
        .select_from(models.PasswordResetToken)
        .where(models.PasswordResetToken.user_id == user_id)
    )
    return result.scalar()


# =====================================================================
# 1) YOUR EXISTING TESTS  (code unchanged, only coverage comments added)
# =====================================================================
@pytest.mark.anyio
async def test_create_user_validation_error(client: AsyncClient):
    test_data = {"username": "testuser"}
    # No body lines: Pydantic rejects the payload at the L60 signature
    # (user: UserCreate) before create_user runs.
    response = await client.post("/api/users", json=test_data)
    assert response.status_code == 422
    assert "email" in response.text
    assert "password" in response.text


@pytest.mark.anyio
async def test_create_user_duplicate_email(client: AsyncClient):
    await create_test_user(client)  # L78-86 (happy path creates the first user)
    test_data = {
        "username": "different_user",
        "email": "test@example.com",
        "password": "password123",
    }
    response = await client.post(  # L61-72 query, L73 (True), L74-77 raise 400
        "/api/users",
        json=test_data,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email or user name already used"


@pytest.mark.anyio
async def test_create_user_success(client: AsyncClient):
    test_data = {
        "username": "newuser",
        "email": "newuser@example.com",
        "password": "securepassword123",
    }
    response = await client.post(  # L73 (False), L78-82 build User, L83 add,
        "/api/users",  # L84 commit, L85 refresh, L86 return new_user
        json=test_data,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == test_data["username"]
    assert data["email"] == test_data["email"]
    assert "id" in data
    assert "image_path" in data
    assert "password" not in data
    assert "password_hash" not in data


@pytest.mark.anyio
async def test_upload_profile_picture(client: AsyncClient, mocked_aws):
    user = await create_test_user(client)
    token = await login_user(client)  # L94-99, L100 (False), L106-111 (login)
    test_image_path = Path(__file__).parent / "test_image.jpg"
    image_bytes = test_image_path.read_bytes()
    response = await client.patch(  # L392 (False), L397 read, L398 (False),
        f"/api/users/{user['id']}/picture",  # L404-407 process image,
        files={"file": ("profile.jpg", BytesIO(image_bytes), "image/jpeg")},
        headers=auth_header(token),  # L414-415 upload to S3,
    )  # L422-425 save filename, L426 (False: no old pic), L428 return
    assert response.status_code == 200
    data = response.json()
    assert data["image_file"] is not None
    assert data["image_file"].endswith(".jpg")
    assert "s3" in data["image_path"]
    s3_objects = mocked_aws.list_objects_v2(Bucket="test-bucket")
    assert "Contents" in s3_objects
    assert len(s3_objects["Contents"]) == 1
    assert s3_objects["Contents"][0]["Key"].endswith(data["image_file"])


@pytest.mark.anyio
async def test_forgot_password_sends_email(client: AsyncClient):
    await create_test_user(client)
    with patch(
        "routers.users.send_password_reset_email",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await client.post(  # L125-130 find user, L132 (True),
            "/api/users/forgot-password",  # L133-137 delete old tokens,
            json={"email": "test@example.com"},  # L139-143 make token + expiry,
        )  # L145-151 save PasswordResetToken, L153-158 add_task, L160-162 return
        assert response.status_code == 202
        mock_send.assert_awaited_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["to_email"] == "test@example.com"
        assert call_kwargs["username"] == "testuser"
        assert "token" in call_kwargs


# =====================================================================
# 2) NEW: create_user  (L59-86)
# =====================================================================
@pytest.mark.anyio
async def test_create_user_duplicate_username_case_insensitive(client: AsyncClient):
    await create_test_user(client)
    response = await client.post(  # L65 (username half of the OR), L73 (True),
        "/api/users",  # L74-77 raise 400
        json={
            "username": "TESTUSER",
            "email": "brand-new@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 400


# =====================================================================
# 3) NEW: login  POST /token  (L89-111)
# =====================================================================
@pytest.mark.anyio
async def test_login_success(client: AsyncClient):
    await create_test_user(client)
    response = await client.post(  # L94-99 query, L100 (False),
        "/api/users/token",  # L106 expires, L107-110 token, L111 return
        data={"username": "TEST@example.com", "password": "testpassword123"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


@pytest.mark.anyio
async def test_login_wrong_password(client: AsyncClient):
    await create_test_user(client)
    response = await client.post(  # L100 (True via verify_password -> False),
        "/api/users/token",  # L101-105 raise 401
        data={"username": "test@example.com", "password": "WRONG-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_login_unknown_email(client: AsyncClient):
    response = await client.post(  # L100 (True via `not user` short-circuit),
        "/api/users/token",  # L101-105 raise 401
        data={"username": "nobody@example.com", "password": "whatever123"},
    )
    assert response.status_code == 401


# =====================================================================
# 4) NEW: GET /me  (L114-116)
# =====================================================================
@pytest.mark.anyio
async def test_get_current_user_success(client: AsyncClient):
    await create_test_user(client)
    token = await login_user(client)
    response = await client.get(  # L116 return current_user
        "/api/users/me",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"


@pytest.mark.anyio
async def test_get_current_user_requires_auth(client: AsyncClient):
    # No body lines: the CurrentUser dependency (L115) rejects first.
    response = await client.get("/api/users/me")
    assert response.status_code == 401


# =====================================================================
# 5) NEW: forgot_password  (L119-162)
# =====================================================================
@pytest.mark.anyio
async def test_forgot_password_unknown_email_same_response(client: AsyncClient):
    with patch(
        "routers.users.send_password_reset_email",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await client.post(  # L125-130 query, L132 (False) -> skips
            "/api/users/forgot-password",  # L133-158, L160-162 return message
            json={"email": "ghost@example.com"},
        )
        assert response.status_code == 202
        assert "If an account exists" in response.json()["message"]
        mock_send.assert_not_awaited()  # proves L153-158 did NOT run


@pytest.mark.anyio
async def test_forgot_password_replaces_previous_token(client: AsyncClient, db_session):
    user = await create_test_user(client)
    with patch(
        "routers.users.send_password_reset_email",
        new_callable=AsyncMock,
    ):
        await client.post(  # first call: L133-137 deletes nothing, L145-151 saves token
            "/api/users/forgot-password", json={"email": "test@example.com"}
        )
        assert await count_reset_tokens(db_session, user["id"]) == 1
        await client.post(  # second call: L133-137 DELETES the old token first
            "/api/users/forgot-password", json={"email": "test@example.com"}
        )
    assert await count_reset_tokens(db_session, user["id"]) == 1


# =====================================================================
# 6) NEW: reset_password  (L165-215)
# =====================================================================
@pytest.mark.anyio
async def test_reset_password_invalid_token(client: AsyncClient):
    response = await client.post(  # L170 hash, L172-177 query (nothing found),
        "/api/users/reset-password",  # L179 (True), L180-183 raise 400
        json={"token": "does-not-exist", "new_password": "newpassword123"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired reset token"


@pytest.mark.anyio
async def test_reset_password_expired_token(client: AsyncClient, db_session):
    user = await create_test_user(client)
    db_session.add(
        models.PasswordResetToken(
            user_id=user["id"],
            token_hash=hash_reset_token("expired-raw-token"),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    response = await client.post(  # L179 (False), L185 (True), L186 delete,
        "/api/users/reset-password",  # L187 commit, L188-191 raise 400
        json={"token": "expired-raw-token", "new_password": "newpassword123"},
    )
    assert response.status_code == 400
    assert await count_reset_tokens(db_session, user["id"]) == 0  # L186-187 proof


@pytest.mark.anyio
async def test_reset_password_success_full_flow(client: AsyncClient, db_session):
    user = await create_test_user(client)
    with patch(
        "routers.users.send_password_reset_email",
        new_callable=AsyncMock,
    ) as mock_send:
        await client.post(
            "/api/users/forgot-password", json={"email": "test@example.com"}
        )
    token = mock_send.call_args.kwargs["token"]

    response = await client.post(  # L185 (False), L193-196 load user, L198 (False),
        "/api/users/reset-password",  # L204 set new hash, L206-210 delete tokens,
        json={"token": token, "new_password": "brand-new-password"},
    )  # L212 commit, L213-215 return message
    assert response.status_code == 200
    assert "Password reset successfully" in response.json()["message"]
    assert await count_reset_tokens(db_session, user["id"]) == 0

    # New password works, old one does not.
    assert await login_user(client, password="brand-new-password")
    old = await client.post(
        "/api/users/token",
        data={"username": "test@example.com", "password": "testpassword123"},
    )
    assert old.status_code == 401


@pytest.mark.anyio
async def test_reset_password_user_missing(client: AsyncClient, db_session):
    # L198-202 is defensive code: the FK makes "token exists but user does
    # not" impossible through the API. So we fake an empty result for the
    # SECOND db.execute call (the user lookup) only.
    user = await create_test_user(client)
    db_session.add(
        models.PasswordResetToken(
            user_id=user["id"],
            token_hash=hash_reset_token("orphan-token"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()

    real_execute = db_session.execute
    calls = {"n": 0}

    class _Empty:
        def scalars(self):
            return self

        def first(self):
            return None

    async def flaky_execute(stmt, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:  # 1st = token query, 2nd = user query
            return _Empty()
        return await real_execute(stmt, *args, **kwargs)

    with patch.object(db_session, "execute", flaky_execute):
        response = await client.post(  # L193-196 (user = None), L198 (True),
            "/api/users/reset-password",  # L199-202 raise 400
            json={"token": "orphan-token", "new_password": "newpassword123"},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired reset token"


# =====================================================================
# 7) NEW: change_password  PATCH /me/password  (L219-240)
# =====================================================================
@pytest.mark.anyio
async def test_change_password_wrong_current_password(client: AsyncClient):
    await create_test_user(client)
    token = await login_user(client)
    response = await client.patch(  # L225 (True), L226-229 raise 400
        "/api/users/me/password",
        json={"current_password": "not-my-password", "new_password": "newpassword123"},
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect"


@pytest.mark.anyio
async def test_change_password_success(client: AsyncClient):
    await create_test_user(client)
    token = await login_user(client)
    response = await client.patch(  # L225 (False), L231 set hash,
        "/api/users/me/password",  # L233-237 delete reset tokens,
        json={
            "current_password": "testpassword123",
            "new_password": "changed-password-1",
        },
        headers=auth_header(token),
    )  # L239 commit, L240 return message
    assert response.status_code == 200
    assert response.json()["message"] == "Password changed successfully"

    assert await login_user(client, password="changed-password-1")
    old = await client.post(
        "/api/users/token",
        data={"username": "test@example.com", "password": "testpassword123"},
    )
    assert old.status_code == 401


# =====================================================================
# 8) NEW: get_user  GET /{user_id}  (L243-254)
# =====================================================================
@pytest.mark.anyio
async def test_get_user_success(client: AsyncClient):
    user = await create_test_user(client)
    response = await client.get(  # L248 query, L249 first(), L250 (False), L254 return
        f"/api/users/{user['id']}"
    )
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"
    assert "email" not in response.json()  # UserPublic hides email


@pytest.mark.anyio
async def test_get_user_not_found(client: AsyncClient):
    response = await client.get("/api/users/999999")  # L250 (True), L251-253 raise 404
    assert response.status_code == 404
    assert response.json()["detail"] == "User 999999 not found"


# =====================================================================
# 9) NEW: get_user_posts  GET /{user_id}/posts  (L257-297)
# =====================================================================
@pytest.mark.anyio
async def test_get_user_posts_user_not_found(client: AsyncClient):
    response = await client.get(  # L264-265 query, L266 (True), L267-270 raise 404
        "/api/users/999999/posts"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


@pytest.mark.anyio
async def test_get_user_posts_empty(client: AsyncClient):
    user = await create_test_user(client)
    response = await client.get(  # L266 (False), L272-277 count, L279-287 posts,
        f"/api/users/{user['id']}/posts"  # L289 has_more (False), L291-297 return
    )
    assert response.status_code == 200
    data = response.json()
    assert data["posts"] == []
    assert data["total"] == 0
    assert data["has_more"] is False


@pytest.mark.anyio
async def test_get_user_posts_pagination_and_isolation(client: AsyncClient):
    user, token = await create_test_user(client), None
    token = await login_user(client)
    other, other_token = await create_other_user(client)
    for i in range(3):
        await client.post(
            "/api/posts",
            json={"title": f"mine {i}", "content": "c"},
            headers=auth_header(token),
        )
    await client.post(
        "/api/posts",
        json={"title": "not mine", "content": "c"},
        headers=auth_header(other_token),
    )

    page1 = (  # L275 where user_id, L282-285 filter/order/offset/limit,
        await client.get(  # L289 has_more (True)
            f"/api/users/{user['id']}/posts", params={"skip": 0, "limit": 2}
        )
    ).json()
    assert page1["total"] == 3  # other user's post is excluded
    assert [p["title"] for p in page1["posts"]] == ["mine 2", "mine 1"]
    assert page1["has_more"] is True

    page2 = (  # L289 has_more (False)
        await client.get(
            f"/api/users/{user['id']}/posts", params={"skip": 2, "limit": 2}
        )
    ).json()
    assert [p["title"] for p in page2["posts"]] == ["mine 0"]
    assert page2["has_more"] is False


# =====================================================================
# 10) NEW: update_user  PATCH /{user_id}  (L300-357)
# =====================================================================
@pytest.mark.anyio
async def test_update_user_forbidden(client: AsyncClient):
    await create_test_user(client)
    token = await login_user(client)
    other, _ = await create_other_user(client)
    response = await client.patch(  # L307 (True), L308-311 raise 403
        f"/api/users/{other['id']}",
        json={"username": "hacked"},
        headers=auth_header(token),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_update_user_not_found(client: AsyncClient):
    # L314-318 is defensive: a logged-in user always exists. We override the
    # auth dependency to return a fake user whose id has no DB row.
    dependency = get_args(CurrentUser)[1].dependency
    app.dependency_overrides[dependency] = lambda: SimpleNamespace(id=424242)
    try:
        response = await client.patch(  # L307 (False), L312-313 query -> None,
            "/api/users/424242",  # L314 (True), L315-318 raise 404
            json={"username": "ghost"},
        )
    finally:
        app.dependency_overrides.pop(dependency, None)
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


@pytest.mark.anyio
async def test_update_user_username_success(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    response = await client.patch(  # L307 (False), L312-313, L314 (False),
        f"/api/users/{user['id']}",  # L319-322 (True), L323-328 uniqueness query,
        json={"username": "renamed"},  # L329 (False), L350-351 assign,
        headers=auth_header(token),  # L352 (False), L355 commit, L356 refresh, L357
    )
    assert response.status_code == 200
    assert response.json()["username"] == "renamed"


@pytest.mark.anyio
async def test_update_user_email_success_and_lowercased(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    response = await client.patch(  # L334-337 (True), L338-343 uniqueness query,
        f"/api/users/{user['id']}",  # L344 (False), L352 (True),
        json={"email": "NEW.Address@Example.com"},  # L353 stores lower-cased email
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["email"] == "new.address@example.com"


@pytest.mark.anyio
async def test_update_user_username_taken(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    await create_other_user(client)
    response = await client.patch(  # L323-328 query finds "other", L329 (True),
        f"/api/users/{user['id']}",  # L330-333 raise 400
        json={"username": "OTHER"},  # case-insensitive clash
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Username already exists"


@pytest.mark.anyio
async def test_update_user_email_taken(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    await create_other_user(client)
    response = await client.patch(  # L338-343 query finds other, L344 (True),
        f"/api/users/{user['id']}",  # L345-348 raise 400
        json={"email": "OTHER@example.com"},
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


@pytest.mark.anyio
async def test_update_user_empty_body_changes_nothing(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    response = await client.patch(  # L320 / L335 short-circuit (None) -> skip checks,
        f"/api/users/{user['id']}",  # L350 (False), L352 (False), L355-357
        json={},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"
    assert response.json()["email"] == "test@example.com"


@pytest.mark.anyio
async def test_update_user_case_only_rename_allowed(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    response = await client.patch(  # L321 lower() equal -> uniqueness check skipped
        f"/api/users/{user['id']}",  # (L323-333 NOT run), L350-351 still assigns
        json={"username": "TestUser"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["username"] == "TestUser"


# =====================================================================
# 11) NEW: delete_user  DELETE /{user_id}  (L360-382)
# =====================================================================
@pytest.mark.anyio
async def test_delete_user_forbidden(client: AsyncClient):
    await create_test_user(client)
    token = await login_user(client)
    other, _ = await create_other_user(client)
    response = await client.delete(  # L366 (True), L367-370 raise 403
        f"/api/users/{other['id']}",
        headers=auth_header(token),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_delete_user_not_found(client: AsyncClient):
    # L373-377 is defensive (see update_user_not_found for why we override).
    dependency = get_args(CurrentUser)[1].dependency
    app.dependency_overrides[dependency] = lambda: SimpleNamespace(id=424242)
    try:
        response = await client.delete("/api/users/424242")  # L366 (False),
    finally:  # L371-372 query -> None, L373 (True), L374-377 raise 404
        app.dependency_overrides.pop(dependency, None)
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


@pytest.mark.anyio
async def test_delete_user_success_without_picture(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    response = await client.delete(  # L371-372, L373 (False), L378 old_filename,
        f"/api/users/{user['id']}",  # L379 delete, L380 commit, L381 (False)
        headers=auth_header(token),
    )
    assert response.status_code == 204
    assert (await client.get(f"/api/users/{user['id']}")).status_code == 404


@pytest.mark.anyio
async def test_delete_user_success_removes_picture_from_s3(
    client: AsyncClient, mocked_aws
):
    user = await create_test_user(client)
    token = await login_user(client)
    await upload_picture(client, user["id"], token)
    assert "Contents" in mocked_aws.list_objects_v2(Bucket="test-bucket")

    response = await client.delete(  # L378, L379-380, L381 (True),
        f"/api/users/{user['id']}",  # L382 delete_profile_image(old_filename)
        headers=auth_header(token),
    )
    assert response.status_code == 204
    assert "Contents" not in mocked_aws.list_objects_v2(Bucket="test-bucket")


# =====================================================================
# 12) NEW: upload_profile_picture  PATCH /{user_id}/picture  (L385-428)
# =====================================================================
@pytest.mark.anyio
async def test_upload_picture_forbidden(client: AsyncClient):
    await create_test_user(client)
    token = await login_user(client)
    other, _ = await create_other_user(client)
    response = await upload_picture(  # L392 (True), L393-396 raise 403
        client, other["id"], token
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_upload_picture_too_large(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    too_big = b"0" * (settings.max_upload_size_bytes + 1)
    response = await upload_picture(  # L397 read, L398 (True),
        client, user["id"], token, data=too_big  # L399-402 raise 400
    )
    assert response.status_code == 400
    assert "File too large" in response.json()["detail"]


@pytest.mark.anyio
async def test_upload_picture_invalid_image(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    response = await upload_picture(  # L404-407 process raises UnidentifiedImageError,
        client, user["id"], token, data=b"definitely not an image"  # L408 except,
    )  # L409-412 raise 400 (chained `from err`)
    assert response.status_code == 400
    assert "Invalid image file" in response.json()["detail"]


@pytest.mark.anyio
async def test_upload_picture_s3_failure(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    boom = ClientError({"Error": {"Code": "500", "Message": "boom"}}, "PutObject")
    with patch(
        "routers.users.upload_profile_image",
        new_callable=AsyncMock,
        side_effect=boom,
    ):
        response = await upload_picture(  # L414-415 upload raises, L416 except,
            client, user["id"], token  # L417-420 raise 500
        )
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to upload image. Please try again."


@pytest.mark.anyio
async def test_upload_picture_replaces_old_picture(client: AsyncClient, mocked_aws):
    user = await create_test_user(client)
    token = await login_user(client)
    first = (await upload_picture(client, user["id"], token)).json()["image_file"]

    response = await upload_picture(  # L422 old_filename (truthy), L426 (True),
        client, user["id"], token  # L427 delete_profile_image(old_filename)
    )
    assert response.status_code == 200
    assert response.json()["image_file"] != first
    objects = mocked_aws.list_objects_v2(Bucket="test-bucket")
    assert len(objects["Contents"]) == 1  # old file was removed from S3


# =====================================================================
# 13) NEW: delete_user_picture  DELETE /{user_id}/picture  (L431-452)
# =====================================================================
@pytest.mark.anyio
async def test_delete_picture_forbidden(client: AsyncClient):
    await create_test_user(client)
    token = await login_user(client)
    other, _ = await create_other_user(client)
    response = await client.delete(  # L437 (True), L438-441 raise 403
        f"/api/users/{other['id']}/picture",
        headers=auth_header(token),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_delete_picture_when_none_set(client: AsyncClient):
    user = await create_test_user(client)
    token = await login_user(client)
    response = await client.delete(  # L437 (False), L442 old_filename = None,
        f"/api/users/{user['id']}/picture",  # L443 (True), L444-447 raise 400
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "No profile picture to delete"


@pytest.mark.anyio
async def test_delete_picture_success(client: AsyncClient, mocked_aws):
    user = await create_test_user(client)
    token = await login_user(client)
    await upload_picture(client, user["id"], token)

    response = await client.delete(  # L443 (False), L448 image_file = None,
        f"/api/users/{user['id']}/picture",  # L449 commit, L450 refresh,
        headers=auth_header(token),  # L451 delete from S3, L452 return
    )
    assert response.status_code == 200
    assert response.json()["image_file"] is None
    assert "Contents" not in mocked_aws.list_objects_v2(Bucket="test-bucket")
