"""Clip-derived Copernicus hazard footprints in the shared board frame.

Consumes small downloaded raster windows; never treats return periods as a forecast.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil


def build(raw, output, source_bundle):
    import numpy as np
    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import shape, LineString, Point, mapping
    from shapely.ops import transform, unary_union
    from pyproj import Transformer
    data = Path(source_bundle) / 'data'
    manifest = json.loads((data/'source_manifest.json').read_text())
    roads = json.loads((data/'roads.json').read_text())
    sites = json.loads((data/'sites.json').read_text())
    left,bottom,right,top = manifest['projected_bounds']
    project = Transformer.from_crs('EPSG:4326',manifest['projected_crs'],always_xy=True)
    def uv(x,y,z=None):
        xx,yy = project.transform(x,y)
        return (np.asarray(xx)-left)/(right-left),(top-np.asarray(yy))/(top-bottom)
    base='https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/'
    quality_name='ID192_N30_E80_spurious_depth_areas.tif'
    with rasterio.open(Path(raw)/quality_name) as src:
        quality = src.read(1)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    result={'method':'copernicus_glofas_return_period_footprint', 'stages':[[]], 'site_stages':[[]],
            'non_restorable_stages':[[]], 'node_stages':[[]], 'footprints':[], 'sources':[],
            'limitations': [
                'Version 2.1.2 statistical riverine hazard maps at approximately 90 m, not live observations.',
                'RP10 and RP100 are alternative return-period scenarios, not chronological flood evolution.',
                'Source no-data pixels are not evidence of a verified dry or safe location.',
                'The quality mask flags potentially spurious depths in this AOI; local depth accuracy is not validated.',
                'Any intersection with positive modeled depth closes an entire compacted road edge conservatively.',
                'Bridges cannot override flood-footprint closures; shelter and service sites in the footprint are excluded.',
                'Suitable for an explicitly unvalidated educational hazard demonstration, not operational routing.']}
    for rp in (10,100):
        name=f'ID192_N30_E80_RP{rp}_depth.tif'
        path=Path(raw)/name
        with rasterio.open(path) as src:
            values=src.read(1)
            wet=(values>0)&(values!=src.nodata)
            polygons=[transform(uv,shape(g)) for g,value in shapes(wet.astype('uint8'),mask=wet,transform=src.transform) if value]
            area=unary_union(polygons)
            result['footprints'].append({'stage':len(result['stages']), 'return_period_years':rp,
                'coordinate_space':'board_uv','geometry':mapping(area),
                'wet_pixels':int(wet.sum()),'quality_flagged_wet_pixels':int((wet&(quality==1)).sum()),
                'source_nodata_pixels':int((values==src.nodata).sum()),'depth_values_not_locally_validated':True})
            blocked=[e['id'] for e in roads['edges'] if area.intersects(LineString(e['board_uv']))]
            result['stages'].append(sorted(blocked));result['non_restorable_stages'].append(sorted(blocked))
            result['site_stages'].append(sorted(s['id'] for s in sites if s['kind']!='control_start_pad' and area.intersects(Point(s['board_uv']))))
            result['node_stages'].append(sorted(n['id'] for n in roads['nodes'] if area.intersects(Point(n['board_uv']))))
            result['sources'].append({'url':base+f'RP{rp}/'+name,'clip_sha256':sha256(path.read_bytes()).hexdigest(),
                'clip_file':'flood/'+name,'crs':str(src.crs),'transform':list(src.transform),'units':'metres',
                'retrieved_date':'2026-10-17','version':'2.1.2','license':'free and open Copernicus product',
                'copyright_url':base+'copyright.txt','readme_url':base+'README.txt'})
        shutil.copyfile(path,output/name)
    shutil.copyfile(Path(raw)/quality_name, output/quality_name)
    result['quality_source']={'url':base+'Spurious_Depths/'+quality_name,
        'clip_sha256':sha256((Path(raw)/quality_name).read_bytes()).hexdigest(), 'clip_file':'flood/'+quality_name}
    (output/'hazard_analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'closed_edges_by_stage':result['stages'],'excluded_sites':result['site_stages'],
                      'footprint_quality':[{k:f[k] for k in ['return_period_years','wet_pixels','quality_flagged_wet_pixels']} for f in result['footprints']]},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('scenarios/nepal_rasuwa_reasoning_v1/data/flood'))
    parser.add_argument('--source-bundle',type=Path,default=Path('scenarios/nepal_rasuwa_reasoning_v1'))
    args=parser.parse_args();build(args.raw,args.output,args.source_bundle)
