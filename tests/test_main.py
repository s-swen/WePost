import pytest
from httpx import AsyncClient
from main import app, lifespan

from unittest.mock import AsyncMock, patch


@pytest.mark.anyio
async def test_html_404_exception_handler(client: AsyncClient):
    # Hit a route that doesn't exist and is NOT under /api/
    response = await client.get("/this-page-does-not-exist-at-all")

    assert response.status_code == 404
    # Verify it's returning HTML, proving the 'else' branch of the handler executed
    assert "text/html" in response.headers.get("content-type", "")
    assert "application/json" not in response.headers.get("content-type", "")


@pytest.mark.anyio
async def test_api_404_exception_handler_bypasses_html(client: AsyncClient):
    response = await client.get("/api/users/99999")

    assert response.status_code == 404
    # Verify it's returning JSON, proving the HTML handler was bypassed
    assert "application/json" in response.headers.get("content-type", "")


@pytest.mark.anyio
async def test_html_validation_exception_handler(client: AsyncClient):
    # This will fail to parse "abc" as an integer for `post_id`
    response = await client.get("/posts/abc")

    assert response.status_code == 422
    # Verify it returned HTML, proving the 'else' branch executed
    assert "text/html" in response.headers.get("content-type", "")
    assert "Invalid request" in response.text


@pytest.mark.anyio
async def test_lifespan_teardown():
    with patch("main.engine") as mock_engine:
        mock_engine.dispose = AsyncMock()

        # Entering and exiting the context manager triggers the code after `yield`
        async with lifespan(app):
            pass  # App is "running"

        # Verify the teardown logic was executed
        mock_engine.dispose.assert_awaited_once()
