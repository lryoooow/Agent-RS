import asyncio

import pytest

from app.uploads import UploadSizeExceeded, stream_upload_to_temp


class FakeUpload:
    def __init__(self, parts):
        self.parts = list(parts)
        self.closed = False

    async def read(self, _size: int):
        part = self.parts.pop(0)
        if isinstance(part, BaseException):
            raise part
        return part

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_stream_upload_removes_partial_file_on_cancellation(tmp_path) -> None:
    upload = FakeUpload([b"partial", asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        await stream_upload_to_temp(
            upload,
            max_bytes=100,
            suffix=".bin",
            directory=tmp_path,
            chunk_bytes=4,
        )

    assert upload.closed is True
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_stream_upload_removes_file_when_limit_is_exceeded(tmp_path) -> None:
    upload = FakeUpload([b"1234", b"5678", b""])

    with pytest.raises(UploadSizeExceeded):
        await stream_upload_to_temp(
            upload,
            max_bytes=7,
            suffix=".bin",
            directory=tmp_path,
            chunk_bytes=4,
        )

    assert upload.closed is True
    assert list(tmp_path.iterdir()) == []
