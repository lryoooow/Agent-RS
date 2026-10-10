"""Preview using the same band metadata, mask and actual grid as analysis."""
from pathlib import Path
import numpy as np

class RasterPreviewBudgetError(ValueError):
    pass

def generate_preview(source: Path, output: Path, max_dimension: int) -> None:
    import rasterio
    from rasterio.enums import Resampling
    from PIL import Image
    from app.services.raster_semantics import band_semantics
    meta = band_semantics(source)
    roles = meta.get('band_roles') or {}
    from app.core.settings import get_settings
    with rasterio.Env(GDAL_CACHEMAX=32*1024*1024), rasterio.open(source) as src:
        factor = min(1.0, max_dimension / max(src.width,src.height))
        shape = (max(1,round(src.height*factor)), max(1,round(src.width*factor)))
        bands = [roles[r] for r in ('red','green','blue')] if all(r in roles for r in ('red','green','blue')) else [1]
        # Account for masks, float conversion, stretching, and the RGBA encoder.
        itemsize=max(np.dtype(src.dtypes[i-1]).itemsize for i in bands)
        estimated=shape[0]*shape[1]*(len(bands)*(itemsize+1)+48)+32*1024*1024
        if estimated > get_settings().imagery_preprocess_max_bytes:
            raise RasterPreviewBudgetError("Raster preview exceeds its memory budget.")
        raw = src.read(bands,out_shape=(len(bands),*shape),masked=True,resampling=Resampling.bilinear)
        data = raw.astype('float32').filled(np.nan)
        valid = np.isfinite(data).all(axis=0)
        alpha = np.where(valid,255,0).astype('uint8')
        if meta.get('alpha_bands'):
            alpha_band = src.read(meta['alpha_bands'][0],out_shape=shape,resampling=Resampling.nearest)
            if alpha_band.dtype == np.uint8:
                alpha = np.where(valid,alpha_band,0).astype('uint8')
            else:
                alpha = np.where(valid & (alpha_band > 0),255,0).astype('uint8')
        channels=[]
        for i,channel in enumerate(data):
            if src.dtypes[bands[i]-1] == 'uint8':
                byte=np.nan_to_num(channel).clip(0,255).astype('uint8')
            else:
                finite=channel[valid & (alpha > 0)]
                lo,hi=np.percentile(finite,[2,98]) if finite.size else (0,0)
                byte=(np.nan_to_num((channel-lo)/max(float(hi-lo),1e-9)).clip(0,1)*255).astype('uint8')
            channels.append(byte)
        if len(channels)==1: channels*=3
        image=np.dstack([*channels,alpha])
    output.parent.mkdir(parents=True,exist_ok=True)
    Image.fromarray(image).save(output,optimize=True)
