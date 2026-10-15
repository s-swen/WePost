import pytest
from unittest.mock import AsyncMock, patch

from email_utils import send_email, send_password_reset_email
from config import settings


# =====================================================================
# 1️⃣ SEND EMAIL TESTS
# =====================================================================
@pytest.mark.anyio
@patch("email_utils.aiosmtplib.send", new_callable=AsyncMock)
async def test_send_email_plain_text(mock_send: AsyncMock):
    """Tests sending a basic plain-text email."""
    await send_email(
        to_email="test@example.com",
        subject="Test Subject",
        plain_text="Test body content",
    )

    mock_send.assert_awaited_once()

    message = mock_send.call_args.args[0]
    kwargs = mock_send.call_args.kwargs

    assert message["From"] == settings.mail_from
    assert message["To"] == "test@example.com"
    assert message["Subject"] == "Test Subject"
    assert kwargs["hostname"] == settings.mail_server
    assert kwargs["port"] == settings.mail_port


@pytest.mark.anyio
@patch("email_utils.aiosmtplib.send", new_callable=AsyncMock)
async def test_send_email_with_html(mock_send: AsyncMock):
    """Tests sending an email with both plain text and HTML alternatives."""
    await send_email(
        to_email="test@example.com",
        subject="Test Subject",
        plain_text="Test body content",
        html_content="<h1>Test body content</h1>",
    )

    mock_send.assert_awaited_once()
    message = mock_send.call_args.args[0]

    # 🎯 TARGET: Covers lines 25-26 (if html_content: add_alternative)
    assert message.is_multipart() is True


# =====================================================================
# 2️⃣ PASSWORD RESET EMAIL TESTS
# =====================================================================
@pytest.mark.anyio
@patch("email_utils.aiosmtplib.send", new_callable=AsyncMock)
async def test_send_password_reset_email(mock_send: AsyncMock):
    """Tests the password reset email generation and dispatch."""
    await send_password_reset_email(
        to_email="user@example.com", username="johndoe", token="secure_reset_token_123"
    )

    # 🎯 TARGET: Covers lines 40-64 (template rendering and send_email call)
    mock_send.assert_awaited_once()
    message = mock_send.call_args.args[0]

    assert message["To"] == "user@example.com"
    assert "Reset Your Password" in message["Subject"]
    assert message.is_multipart() is True

    # Verify the rendered template actually contains our dynamic data
    msg_str = str(message)
    assert "johndoe" in msg_str
    assert "secure_reset_token_123" in msg_str

    assert "reset-password" in msg_str
