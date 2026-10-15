import pytest
from httpx import AsyncClient

try:
    from tests.conftest import auth_header, create_test_user, login_user
except ImportError:  # no tests/__init__.py
    from conftest import auth_header, create_test_user, login_user

pytestmark = pytest.mark.anyio

BASE = "/api/posts"


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
async def make_user_and_token(
    client: AsyncClient,
    username: str = "testuser",
    email: str = "test@example.com",
) -> tuple[dict, str]:
    user = await create_test_user(client, username=username, email=email)
    token = await login_user(client, email=email)
    return user, token


async def make_post(
    client: AsyncClient,
    token: str,
    title: str = "Title",
    content: str = "Content",
) -> dict:
    response = await client.post(
        BASE,
        json={"title": title, "content": content},
        headers=auth_header(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------
# GET /api/posts
# ---------------------------------------------------------------------
# TARGETS routers/posts.py  L32 (count query), L34 (total), L36-42 (select posts),
# L43 (posts list), L45 (has_more = False), L47-53 (return PaginatedPostsResponse)
# Why: the whole get_posts body runs once, on an empty table.
async def test_get_posts_empty(client: AsyncClient):
    response = await client.get(BASE)
    assert response.status_code == 200
    data = response.json()
    assert data["posts"] == []
    assert data["total"] == 0
    assert data["skip"] == 0
    assert data["has_more"] is False


# TARGETS routers/posts.py  L36-42 (esp. L37 selectinload author, L38 order_by desc), L47-53
# Why: proves ordering (L38) and that the author is eagerly loaded (L37).
async def test_get_posts_newest_first(client: AsyncClient):
    _, token = await make_user_and_token(client)
    await make_post(client, token, title="first")
    await make_post(client, token, title="second")

    response = await client.get(BASE)
    data = response.json()
    assert data["total"] == 2
    assert [p["title"] for p in data["posts"]] == ["second", "first"]
    assert data["posts"][0]["author"]["username"] == "testuser"


# TARGETS routers/posts.py  L39 (offset), L40 (limit), L45 (has_more = skip + len(posts) < total)
# Why: page 1 makes has_more True, page 2 makes it False -> both outcomes of L45.
async def test_get_posts_pagination_has_more(client: AsyncClient):
    _, token = await make_user_and_token(client)
    for i in range(3):
        await make_post(client, token, title=f"post {i}")

    page1 = (await client.get(BASE, params={"skip": 0, "limit": 2})).json()
    assert len(page1["posts"]) == 2
    assert page1["total"] == 3
    assert page1["limit"] == 2
    assert page1["has_more"] is True

    page2 = (await client.get(BASE, params={"skip": 2, "limit": 2})).json()
    assert len(page2["posts"]) == 1
    assert page2["skip"] == 2
    assert page2["has_more"] is False


@pytest.mark.parametrize(
    "params",
    [{"skip": -1}, {"limit": 0}, {"limit": 101}],
)
# TARGETS routers/posts.py  L28-29 (Query(ge=0) / Query(ge=1, le=100))
# Why: FastAPI rejects the request BEFORE the function body runs, so no body lines are
# covered here. It protects behaviour, not line coverage.
async def test_get_posts_invalid_query_params(client: AsyncClient, params):
    response = await client.get(BASE, params=params)
    assert response.status_code == 422


# ---------------------------------------------------------------------
# POST /api/posts
# ---------------------------------------------------------------------
# TARGETS routers/posts.py  L63-67 (build models.Post), L68 (db.add), L69 (commit),
# L70 (refresh author), L71 (return new_post)
# Why: the single happy path through create_post.
async def test_create_post_success(client: AsyncClient):
    user, token = await make_user_and_token(client)
    response = await client.post(
        BASE,
        json={"title": "Hello", "content": "World"},
        headers=auth_header(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Hello"
    assert data["content"] == "World"
    assert data["user_id"] == user["id"]
    assert data["author"]["id"] == user["id"]


# TARGETS routers/posts.py  L59 (current_user: CurrentUser dependency, logic lives in auth.py)
# Why: request is rejected before the body runs -> no body lines covered.
async def test_create_post_requires_auth(client: AsyncClient):
    response = await client.post(BASE, json={"title": "t", "content": "c"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "", "content": "c"},
        {"title": "t", "content": ""},
        {"title": "x" * 101, "content": "c"},
        {"content": "c"},
    ],
)
# TARGETS routers/posts.py  L58 (post: PostCreate -> schemas.PostBase rules)
# Why: Pydantic rejects the payload before the body runs -> no body lines covered.
async def test_create_post_validation_errors(client: AsyncClient, payload):
    _, token = await make_user_and_token(client)
    response = await client.post(BASE, json=payload, headers=auth_header(token))
    assert response.status_code == 422


# ---------------------------------------------------------------------
# GET /api/posts/{post_id}
# ---------------------------------------------------------------------
# TARGETS routers/posts.py  L76-80 (query), L81 (post = ...), L82 (if post: True), L83 (return post)
async def test_get_post_success(client: AsyncClient):
    _, token = await make_user_and_token(client)
    created = await make_post(client, token, title="Find me")

    response = await client.get(f"{BASE}/{created['id']}")
    assert response.status_code == 200
    assert response.json()["title"] == "Find me"
    assert response.json()["author"]["username"] == "testuser"


# TARGETS routers/posts.py  L76-81, L82 (if post: False), L84-86 (raise 404 with f-string detail)
async def test_get_post_not_found(client: AsyncClient):
    response = await client.get(f"{BASE}/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Post 999999 not found"


# ---------------------------------------------------------------------
# PUT /api/posts/{post_id}
# ---------------------------------------------------------------------
# TARGETS routers/posts.py  L96-97 (fetch), L98 (post found), L102 (owner matches),
# L108-109 (assign title/content), L111 (commit), L112 (refresh), L113 (return)
async def test_update_post_full_success(client: AsyncClient):
    _, token = await make_user_and_token(client)
    created = await make_post(client, token)

    response = await client.put(
        f"{BASE}/{created['id']}",
        json={"title": "New title", "content": "New content"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "New title"
    assert data["content"] == "New content"
    assert data["author"]["username"] == "testuser"


# TARGETS routers/posts.py  L96-97, L98 (if not post: True), L99-101 (raise 404)
async def test_update_post_full_not_found(client: AsyncClient):
    _, token = await make_user_and_token(client)
    response = await client.put(
        f"{BASE}/999999",
        json={"title": "t", "content": "c"},
        headers=auth_header(token),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Post not found"


# TARGETS routers/posts.py  L102 (ownership check True), L103-106 (raise 403)
async def test_update_post_full_forbidden(client: AsyncClient):
    _, owner_token = await make_user_and_token(client)
    _, other_token = await make_user_and_token(
        client, username="other", email="other@example.com"
    )
    created = await make_post(client, owner_token)

    response = await client.put(
        f"{BASE}/{created['id']}",
        json={"title": "hack", "content": "hack"},
        headers=auth_header(other_token),
    )
    assert response.status_code == 403


# TARGETS routers/posts.py  L92 (current_user: CurrentUser dependency)
# Why: rejected before the body runs -> no body lines covered.
async def test_update_post_full_requires_auth(client: AsyncClient):
    response = await client.put(f"{BASE}/1", json={"title": "t", "content": "c"})
    assert response.status_code == 401


# ---------------------------------------------------------------------
# PATCH /api/posts/{post_id}
# ---------------------------------------------------------------------
# TARGETS routers/posts.py  L123-124 (fetch), L125 (post found), L129 (owner matches),
# L135 (model_dump exclude_unset), L136-137 (setattr loop), L139-141 (commit/refresh/return)
# Why: only 'title' is sent, so the loop sets one field and content stays untouched.
async def test_update_post_partial_only_title(client: AsyncClient):
    _, token = await make_user_and_token(client)
    created = await make_post(client, token, title="old", content="keep me")

    response = await client.patch(
        f"{BASE}/{created['id']}",
        json={"title": "new"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "new"
    assert data["content"] == "keep me"  # untouched


# TARGETS routers/posts.py  L135-137 (same lines as above, other field)
# Why: confirms the loop is generic and not hard-wired to 'title'.
async def test_update_post_partial_only_content(client: AsyncClient):
    _, token = await make_user_and_token(client)
    created = await make_post(client, token, title="keep", content="old")

    response = await client.patch(
        f"{BASE}/{created['id']}",
        json={"content": "new"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["title"] == "keep"
    assert response.json()["content"] == "new"


# TARGETS routers/posts.py  L123-124, L125 (if not post: True), L126-128 (raise 404)
async def test_update_post_partial_not_found(client: AsyncClient):
    _, token = await make_user_and_token(client)
    response = await client.patch(
        f"{BASE}/999999", json={"title": "x"}, headers=auth_header(token)
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Post not found"


# TARGETS routers/posts.py  L129 (ownership check True), L130-133 (raise 403)
async def test_update_post_partial_forbidden(client: AsyncClient):
    _, owner_token = await make_user_and_token(client)
    _, other_token = await make_user_and_token(
        client, username="other", email="other@example.com"
    )
    created = await make_post(client, owner_token)

    response = await client.patch(
        f"{BASE}/{created['id']}",
        json={"title": "hack"},
        headers=auth_header(other_token),
    )
    assert response.status_code == 403


# TARGETS routers/posts.py  L119 (post_data: PostUpdate -> min_length=1 on title)
# Why: rejected before the body runs -> no body lines covered.
async def test_update_post_partial_invalid_data(client: AsyncClient):
    _, token = await make_user_and_token(client)
    created = await make_post(client, token)
    response = await client.patch(
        f"{BASE}/{created['id']}", json={"title": ""}, headers=auth_header(token)
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------
# DELETE /api/posts/{post_id}
# ---------------------------------------------------------------------
# TARGETS routers/posts.py  L150-151 (fetch), L152 (post found), L156 (owner matches),
# L162 (db.delete), L163 (commit)
async def test_delete_post_success(client: AsyncClient):
    _, token = await make_user_and_token(client)
    created = await make_post(client, token)

    response = await client.delete(
        f"{BASE}/{created['id']}", headers=auth_header(token)
    )
    assert response.status_code == 204

    follow_up = await client.get(f"{BASE}/{created['id']}")
    assert follow_up.status_code == 404


# TARGETS routers/posts.py  L150-151, L152 (if not post: True), L153-155 (raise 404)
async def test_delete_post_not_found(client: AsyncClient):
    _, token = await make_user_and_token(client)
    response = await client.delete(f"{BASE}/999999", headers=auth_header(token))
    assert response.status_code == 404
    assert response.json()["detail"] == "Post not found"


# TARGETS routers/posts.py  L156 (ownership check True), L157-160 (raise 403)
# Note: the detail text on L159 says 'update' - that is a bug in the router (should be 'delete').
async def test_delete_post_forbidden(client: AsyncClient):
    _, owner_token = await make_user_and_token(client)
    _, other_token = await make_user_and_token(
        client, username="other", email="other@example.com"
    )
    created = await make_post(client, owner_token)

    response = await client.delete(
        f"{BASE}/{created['id']}", headers=auth_header(other_token)
    )
    assert response.status_code == 403

    # Post must still exist
    assert (await client.get(f"{BASE}/{created['id']}")).status_code == 200


# TARGETS routers/posts.py  L147 (current_user: CurrentUser dependency)
# Why: rejected before the body runs -> no body lines covered.
async def test_delete_post_requires_auth(client: AsyncClient):
    response = await client.delete(f"{BASE}/1")
    assert response.status_code == 401
