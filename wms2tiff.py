from osgeo import gdal
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta
import requests
import numpy as np
import os
import time
import warnings

warnings.filterwarnings("ignore")

USERNAME = os.getenv('USERNAME')
PASSWORD = os.getenv('PASSWORD')

gdal.SetConfigOption('GDAL_CACHEMAX', '2048')
os.environ['GDAL_HTTP_TIMEOUT'] = '600'

n_of_quadrants = 16 # 16, 8, 4, 2
wh_size = 25000 # 10000, 25000, 50000

delete_temp_files = True

step_begin = None
step_end = None

start_time = datetime.now()

def get_token():
    url = "https://webgis.abdac.it/portal/sharing/rest/generateToken"
    payload = {
        "username": USERNAME,
        "password": PASSWORD,
        "client": "referer",
        "ip": "",
        "referer": "https://webgis.abdac.it/",
        "expiration": 6000,
        "f": "pjson"
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(url, data=payload, headers=headers)

    g_token = response.json()["token"]
    return g_token

def clear_previous_lines(n=2):
    for _ in range(n):
        print('\033[F\033[K', end='')

def print_dataset_info(dataset):
    if dataset is None:
        print("Dataset is None.")
        return

    print("Dataset Information:")
    print(f"Driver: {dataset.GetDriver().LongName}")
    print(f"Number of Bands: {dataset.RasterCount}")

    for i in range(dataset.RasterCount):
        band = dataset.GetRasterBand(i + 1)
        print(f"\nBand {i + 1}:")
        print(f"  Type: {gdal.GetDataTypeName(band.DataType)}")
        print(f"  Size: {band.XSize} x {band.YSize}")

    print("\nGeoreference Information:")
    geotransform = dataset.GetGeoTransform()
    if geotransform:
        print(f"  Top Left: ({geotransform[0]}, {geotransform[3]})")
        print(f"  Pixel Size: {geotransform[1]} x {geotransform[5]}")
    else:
        print("  No georeference information available.")

    print(f"\nProjection: {dataset.GetProjection()}")

    metadata = dataset.GetMetadata()

    if metadata:
        print("\nMetadata:")
        for key, value in metadata.items():
            print(f"  {key}: {value}")


def get_capabilities(base_url, use_token=False):
    capabilities_url = f'{base_url}?service=WMS&version=1.3.0&request=GetCapabilities'

    try:
        if use_token:
            g_token = get_token()
            capabilities_url += f"&token={g_token}"
            response = requests.get(capabilities_url)
        else:
            response = requests.get(capabilities_url)
            
    except Exception as e:
        print(f'Error: {str(e)}')
        return None

    capabilities = ET.fromstring(response.content)

    cap_dict = {}
    namespace = {'ns0': 'http://www.opengis.net/wms'}

    cap_dict['max_width'] = capabilities.find('.//ns0:MaxWidth', namespace).text
    cap_dict['max_height'] = capabilities.find('.//ns0:MaxHeight', namespace).text

    time_dimension = capabilities.find('.//ns0:Dimension[@name="time"]', namespace)
    cap_dict['time'] = time_dimension.attrib['default'] if time_dimension is not None else None

    minx = float(capabilities.find('.//ns0:BoundingBox', namespace).attrib.get('minx'))
    maxx = float(capabilities.find('.//ns0:BoundingBox', namespace).attrib.get('maxx'))
    miny = float(capabilities.find('.//ns0:BoundingBox', namespace).attrib.get('miny'))
    maxy = float(capabilities.find('.//ns0:BoundingBox', namespace).attrib.get('maxy'))

    step_x = (maxx - minx) / n_of_quadrants
    step_y = (maxy - miny) / n_of_quadrants

    cap_dict['bboxes'] = []

    for i in range(n_of_quadrants):
        for j in range(n_of_quadrants):
            bbox_minx = minx + j * step_x
            bbox_maxx = minx + (j + 1) * step_x
            bbox_miny = miny + i * step_y
            bbox_maxy = miny + (i + 1) * step_y

            cap_dict['bboxes'].append(f'{bbox_miny},{bbox_minx},{bbox_maxy},{bbox_maxx}')

    cap_dict['title'] = capabilities.find('.//ns0:Title', namespace).text
    return cap_dict


def set_transparency(input_tiff, output_tiff, transparency):
    dataset = gdal.Open(input_tiff)
    if dataset is None:
        print("Failed to open the input TIFF file.")
        return

    geotransform = dataset.GetGeoTransform()
    projection = dataset.GetProjection()

    raster_data = dataset.ReadAsArray()

    if raster_data.ndim == 3:
        bands, rows, cols = raster_data.shape
        if bands == 3:
            alpha_channel = np.full((rows, cols), int(255 * transparency), dtype=np.uint8)
            rgba_data = np.vstack((raster_data, alpha_channel[np.newaxis, ...]))
        elif bands == 4:
            rgba_data = raster_data.copy()
            rgba_data[3, :, :] = (rgba_data[3, :, :] * transparency).astype(np.uint8)
    elif raster_data.ndim == 2:
        rows, cols = raster_data.shape
        rgba_data = np.zeros((4, rows, cols), dtype=np.uint8)
        for i in range(3):
            rgba_data[i, :, :] = raster_data
        rgba_data[3, :, :] = int(255 * transparency)

    driver = gdal.GetDriverByName('GTiff')
    out_dataset = driver.Create(output_tiff, cols, rows, 4, gdal.GDT_Byte, [
        'COMPRESS=LZW',  
        'TILED=YES',
        'ALPHA=YES'
    ])

    out_dataset.SetGeoTransform(geotransform)
    out_dataset.SetProjection(projection)

    for i in range(4):
        out_band = out_dataset.GetRasterBand(i + 1)
        out_band.WriteArray(rgba_data[i, :, :])

    dataset = None
    out_dataset = None


def merge_tiffs(files, output_file):
    try:
        print("Merging TIFF files...", end='\r', flush=True)

        warp_options = gdal.WarpOptions(
            format='GTiff',
            creationOptions=["COMPRESS=LZW", "TILED=YES", "ALPHA=YES"]
        )

        gdal.Warp(destNameOrDestDS=output_file, srcDSOrSrcDSTab=files, options=warp_options)

        print(f"TIFF files merged successfully into {output_file}", end='\r', flush=True)

        if delete_temp_files:
            for file in files:
                if os.path.exists(file):
                    os.remove(file)
            if os.listdir('temp') == []:
                os.removedirs('temp')

    except Exception as e:
        print(f"Error during merging: {str(e)}")


def download_wms_layer(wms_url, output_tiff):
    global step_begin
    global step_end

    output_files = []
    time_diffs = []

    try:
        capabilities = get_capabilities(wms_url, use_token=True)

        max_width = capabilities['max_width']
        max_height = capabilities['max_height']

        width = max_width
        height = max_height

        width, height = wh_size, wh_size

        if 'temp' not in os.listdir():
            os.mkdir('temp')

        temp_output_tiff = os.path.join('temp', output_tiff)

        for idx, bbox in enumerate(capabilities['bboxes']):
            options = [
                '-co', 'ALPHA=YES',
                '-co', 'TILED=YES',
                '-co', 'COMPRESS=LZW'
            ]

            g_token = get_token()

            wms_url_with_size = f'{wms_url}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&styles=default&LAYERS=0&WIDTH={width}&HEIGHT={height}\
                &FORMAT=image/png&TRANSPARENT=true&CRS=EPSG:4326&BBOX={bbox}&token={g_token}'

            wms_dataset = gdal.Open(wms_url_with_size)

            if wms_dataset is None:
                print("GDAL failed to open the WMS dataset.")
                return
            
            tot_quadrants = n_of_quadrants * n_of_quadrants
            i = idx + 1

            step_begin = time.time()

            if time_diffs:
                avg_time_per_quadrant = sum(time_diffs) / len(time_diffs)
                remaining_quadrants = tot_quadrants - i + 1
                eta = avg_time_per_quadrant * remaining_quadrants
                if eta < 60:
                    eta_finish = datetime.now() + timedelta(seconds=eta)
                    eta_str = f'~ {int(eta)} seconds remaining (finishes downloading at around: {eta_finish.strftime("%H:%M:%S")})'
                elif 60 <= eta < 3600:
                    eta_finish = datetime.now() + timedelta(minutes=eta/60)
                    eta_str = f'~ {round(eta/60, 2)} minutes remaining (finishes downloading at around: {eta_finish.strftime("%H:%M:%S")})'
                elif 3600 <= eta:
                    eta_finish = datetime.now() + timedelta(hours=eta/3600)
                    eta_str = f'~ {round(eta/3600, 2)} hours remaining (finishes downloading at around: {eta_finish.strftime("%H:%M:%S")})'
            else:
                eta_str = ''

            print('\r' + (' ' * 150), end='', flush=True)
            print(f'\rDownloading {i}/{tot_quadrants}...  {eta_str}', end='', flush=True)

            output_file_with_idx = temp_output_tiff.replace('.tiff', f'_{i}.tiff')
            gdal.Translate(output_file_with_idx, wms_dataset, format='GTiff', width=width, height=height, options=options)
            
            output_files.append(output_file_with_idx)

            set_transparency(output_file_with_idx, output_file_with_idx.replace('.tiff', '_transp.tiff'), transparency=0.5)
            output_files.remove(output_file_with_idx)
            if os.path.exists(output_file_with_idx):
                os.remove(output_file_with_idx)
            output_files.append(output_file_with_idx.replace('.tiff', '_transp.tiff'))

            step_end = time.time()

            elapsed = step_end - step_begin
            time_diffs.append(elapsed)

        print('\r' + ' ' * 150, end='\r', flush=True)

        merge_tiffs(output_files, output_tiff)
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    print('------WMS to TIFF------')
    
    # base_wms_url = 'https://webgis.abdac.it/server/services/ETT_PERIC_FRANA_DISTR/MapServer/WMSServer'
    # base_wms_url = 'https://webgis.abdac.it/server/services/Pericolosit%C3%A0_idraulica_Progetto_PAI_distr___solo_fluviale___bozza_/MapServer/WMSServer'

    base_wms_url = input('Please write the URL to the WMS Layer:\n')

    clear_previous_lines(n=2)

    output_path = input('Please write a name for the output tiff file:\n')
    if not output_path.endswith('.tiff'):
        output_path += '.tiff'

    clear_previous_lines(n=2)
    
    print(f'Job started at {start_time}' + ' ' * 50)
    download_wms_layer(base_wms_url, output_path)
    print(f'Job finished at {datetime.now()}')
    cwd = os.getcwd()
    print(f'File saved as {output_path} in {cwd}')
