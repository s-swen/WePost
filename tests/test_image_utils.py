import pytest
from unittest.mock import patch, MagicMock
from io import BytesIO
from PIL import Image

from image_utils import (
    process_profile_image,
    delete_profile_image,
)


# =====================================================================
# 🛠️ HELPER UTILITIES
# =====================================================================
def create_image_bytes(mode: str = "RGB", size: tuple = (500, 500)) -> bytes:
    """Generates dummy image bytes in memory for testing."""
    img = Image.new(mode, size, color="red")
    buffer = BytesIO()
    # PNG supports transparency (RGBA/LA/P), while JPEG does not
    fmt = "PNG" if mode in ("RGBA", "LA", "P") else "JPEG"
    img.save(buffer, format=fmt)
    return buffer.getvalue()


# =====================================================================
# 1️⃣ IMAGE PROCESSING TESTS
# =====================================================================
def test_process_profile_image_rgb():
    """Tests standard RGB image processing (Baseline test)."""
    content = create_image_bytes(mode="RGB")
    processed_bytes, filename = process_profile_image(content)

    assert filename.endswith(".jpg")
    assert len(processed_bytes) > 0

    # Verify the output is a valid, resized JPEG
    with Image.open(BytesIO(processed_bytes)) as img:
        assert img.format == "JPEG"
        assert img.size == (300, 300)
        assert img.mode == "RGB"


def test_process_profile_image_rgba():
    """🎯 TARGET: Covers line 35 (converting RGBA/LA/P to RGB)."""
    content = create_image_bytes(mode="RGBA")
    processed_bytes, filename = process_profile_image(content)

    assert filename.endswith(".jpg")

    # If line 35 is missing, this will throw an OSError when saving as JPEG
    with Image.open(BytesIO(processed_bytes)) as img:
        assert img.format == "JPEG"
        assert img.size == (300, 300)
        assert img.mode == "RGB"


# =====================================================================
# 2️⃣ S3 DELETION TESTS
# =====================================================================
@pytest.mark.anyio
async def test_delete_profile_image_none():
    """🎯 TARGET: Covers lines 67-68 (early return if filename is None)."""
    # We mock the S3 client to ensure it is NEVER called when filename is None
    with patch("image_utils._get_s3_client") as mock_s3_client:
        await delete_profile_image(None)
        mock_s3_client.assert_not_called()


@pytest.mark.anyio
async def test_delete_profile_image_success():
    """🎯 TARGET: Covers lines 57-58, 69-70 (successful S3 deletion)."""
    mock_s3 = MagicMock()

    with patch("image_utils._get_s3_client", return_value=mock_s3):
        await delete_profile_image("test_image.jpg")

        # Verify delete_object was called with the correct key
        mock_s3.delete_object.assert_called_once()
        call_kwargs = mock_s3.delete_object.call_args.kwargs
        assert call_kwargs["Key"] == "profile_pics/test_image.jpg"
