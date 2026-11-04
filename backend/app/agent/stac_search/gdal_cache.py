"""Invalidate one failed remote asset in the GDAL instance used by Rasterio."""

from __future__ import annotations

import ctypes
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _partial_clear():
    import rasterio._base

    # Resolve the library used by Rasterio, never another system GDAL: its cache
    # would be unrelated. Linux/macOS resolve symbols through the extension;
    # Windows wheels keep their already-loaded GDAL DLL in rasterio.libs.
    extension = Path(rasterio._base.__file__)
    if os.name == "nt":
        libraries = list((extension.parent.parent / "rasterio.libs").glob("gdal*.dll"))
        if len(libraries) != 1:
            raise RuntimeError("Cannot identify Rasterio's GDAL library for cache recovery")
        library_path = libraries[0]
    else:
        library_path = extension
    library = ctypes.CDLL(str(library_path))
    clear = library.VSICurlPartialClearCache
    clear.argtypes = [ctypes.c_char_p]
    clear.restype = None
    return clear


def clear_remote_raster_cache(vsi_path: str) -> None:
    """Clear only this /vsicurl/ filename, including a cached incomplete block.

    The GDAL API requires the /vsicurl/ prefix; passing a plain URL is a no-op.
    Successful assets and the application's completed PNG/TIFF cache stay intact.
    """
    if not vsi_path.startswith(("/vsicurl/http://", "/vsicurl/https://")):
        raise ValueError("Cache recovery requires a remote raster filename")
    _partial_clear()(vsi_path.encode("utf-8"))
