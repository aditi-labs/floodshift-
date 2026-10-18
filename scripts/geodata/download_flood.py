"""Download only windows of the verified official tile; no account or API key."""
import argparse
from pathlib import Path

BASE='https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/'
FILES=[('RP10','ID192_N30_E80_RP10_depth.tif'),('RP100','ID192_N30_E80_RP100_depth.tif'),
       ('Spurious_Depths','ID192_N30_E80_spurious_depth_areas.tif')]


def download(output):
    import rasterio
    from rasterio.windows import from_bounds
    import urllib.request
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    for folder,name in FILES:
        with rasterio.Env(GDAL_HTTP_TIMEOUT='30',GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif'):
            with rasterio.open(BASE+folder+'/'+name) as src:
                window=from_bounds(85.329,28.152,85.357,28.177,src.transform).round_offsets().round_lengths()
                values=src.read(1,window=window)
                profile=src.profile.copy()
                profile.update(width=values.shape[1],height=values.shape[0],transform=src.window_transform(window),compress='deflate',tiled=False)
                with rasterio.open(output/name,'w',**profile) as dst:dst.write(values,1)
    for name in ('README.txt','copyright.txt'):
        with urllib.request.urlopen(BASE+name,timeout=30) as response:
            text=response.read().decode('utf-8')
            (output/name).write_text('\n'.join(line.rstrip() for line in text.splitlines()).rstrip()+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    download(parser.parse_args().output)
