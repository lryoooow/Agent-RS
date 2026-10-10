"""Pixel-space tiling and auditable mask-based cross-tile suppression."""
# ruff: noqa

import math
from dataclasses import dataclass
import numpy as np

def starts(length,tile,overlap):
    if length<=0 or tile<=0 or not 0<=overlap<tile:raise ValueError('Invalid tiling dimensions')
    if length<=tile:return [0]
    n=math.ceil((length-tile)/(tile-overlap))+1
    return [round(i*(length-tile)/(n-1)) for i in range(n)]

def tiles(width,height,size=512,overlap=128):
    return [(x,y,min(x+size,width),min(y+size,height)) for y in starts(height,size,overlap) for x in starts(width,size,overlap)]

@dataclass
class Instance:
    ident:str
    concept:str
    score:float
    tile_id:int
    box:tuple
    mask:np.ndarray
    truncated:bool
    source_tiles:tuple=()
    source_ids:tuple=()

    def __post_init__(self):
        if not self.source_tiles:self.source_tiles=(self.tile_id,)
        if not self.source_ids:self.source_ids=(self.ident,)

    @property
    def area(self):return int(self.mask.sum())

def make_instance(mask,extent,image_size,ident,concept,score,tile_id,roi=None):
    x0,y0,x1,y1=extent;w,h=image_size
    if mask.shape!=(y1-y0,x1-x0):raise ValueError('Mask and extent mismatch')
    if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('Extent outside image')
    mask=np.asarray(mask,dtype=bool).copy()
    truncated=bool((x0>0 and mask[:,:2].any()) or (y0>0 and mask[:2,:].any()) or (x1<w and mask[:,-2:].any()) or (y1<h and mask[-2:,:].any()))
    if roi is not None:
        if roi.shape!=(h,w):raise ValueError('ROI shape mismatch')
        mask &= roi[y0:y1,x0:x1]
    yy,xx=np.nonzero(mask)
    if not len(xx):return None
    left,top,right,bottom=int(xx.min()),int(yy.min()),int(xx.max())+1,int(yy.max())+1
    return Instance(ident,concept,float(score),tile_id,(x0+left,y0+top,x0+right,y0+bottom),mask[top:bottom,left:right].copy(),truncated)

def overlap_metrics(a,b):
    ax,ay,ar,ab=a.box;bx,by,br,bb=b.box
    x,y,r,d=max(ax,bx),max(ay,by),min(ar,br),min(ab,bb)
    if r<=x or d<=y:return 0.,0.,0.
    inter=int(np.logical_and(a.mask[y-ay:d-ay,x-ax:r-ax],b.mask[y-by:d-by,x-bx:r-bx]).sum())
    aa,ba=a.area,b.area
    return inter/(aa+ba-inter),inter/min(aa,ba),min(aa,ba)/max(aa,ba)

def deduplicate(instances,iou_threshold=.5,fragment_ios=.85,min_area_ratio=.35):
    # Merge the masks of a matched cross-tile group instead of dropping its
    # lower-ranked view: both views may hold unique pieces of a large object.
    # Track every contributing tile, so a group cannot absorb two instances
    # detected within the same tile. Revisit pairs until a deterministic fixed
    # point; a merged mask can change its overlap with other views.
    kept=list(instances);audit=[]
    while True:
        kept.sort(key=lambda i:(i.truncated,-i.score,-i.area,i.ident))
        merged=False
        for j,item in enumerate(kept):
            for k in range(j):
                prev=kept[k]
                if item.concept!=prev.concept or set(item.source_tiles)&set(prev.source_tiles):continue
                iou,ios,ratio=overlap_metrics(item,prev)
                reason=None
                if iou>=iou_threshold:reason='mask_iou'
                elif (item.truncated or prev.truncated) and ios>=fragment_ios and ratio>=min_area_ratio:reason='boundary_fragment'
                if not reason:continue
                x,y=min(prev.box[0],item.box[0]),min(prev.box[1],item.box[1])
                r,b=max(prev.box[2],item.box[2]),max(prev.box[3],item.box[3])
                mask=np.zeros((b-y,r-x),bool)
                for value in [prev,item]:
                    vx,vy,vr,vb=value.box;mask[vy-y:vb-y,vx-x:vr-x]|=value.mask
                audit.append({'removed':item.ident,'kept':prev.ident,'operation':'merge_mask_union','reason':reason,'mask_iou':iou,'intersection_over_smaller':ios,'area_ratio':ratio,'merged_source_ids':list(prev.source_ids+item.source_ids),'unique_pixels_preserved':int(mask.sum())-prev.area})
                kept[k]=Instance(prev.ident,prev.concept,max(prev.score,item.score),prev.tile_id,(x,y,r,b),mask,prev.truncated or item.truncated,tuple(sorted(prev.source_tiles+item.source_tiles)),prev.source_ids+item.source_ids)
                kept.pop(j);merged=True;break
            if merged:break
        if not merged:return kept,audit

def union_mask(instances,size,concept=None):
    w,h=size;result=np.zeros((h,w),dtype=bool)
    for i in instances:
        if concept is not None and i.concept!=concept:continue
        x,y,r,b=i.box;result[y:b,x:r]|=i.mask
    return result
