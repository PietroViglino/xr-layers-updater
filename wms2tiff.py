
from osgeo import gdal
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta
from dotenv import load_dotenv
from colorama import init, Cursor
import sys
import requests
import numpy as np
import os
import boto3
import time
import json
import warnings

warnings.filterwarnings("ignore")

init(autoreset=True)

load_dotenv()

USERNAME = os.getenv('USERNAME_DOTENV')
PASSWORD = os.getenv('PASSWORD_DOTENV')

CESIUM_TOKEN = os.getenv('CESIUM_TOKEN')

gdal.SetConfigOption('GDAL_CACHEMAX', '2048')
os.environ['GDAL_HTTP_TIMEOUT'] = '600'

# n_of_quadrants = 32 # 16, 8, 4, 2
# wh_size = 5000 # 10000, 25000, 50000

delete_temp_files = True

step_begin = None
step_end = None

start_time = datetime.now()

previous_line_len = 100


def get_token():
    """This function takes the username and password from the env file
    and makes a request to webgis.abdac to gather the token that will be used
    in the following requests
    """
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
    try:
        response = requests.post(url, data=payload, headers=headers)

        g_token = response.json()["token"]
    except Exception as e:
        print(f'Something went wrong when requesting the token: {str(e)}')
        time.sleep(2)
        sys.exit(0)
    return g_token


def clear_previous_lines(n=2):
    """This function clears the n previously written lines in the terminal
    """
    for _ in range(n):
        sys.stdout.write(Cursor.UP(1))
        sys.stdout.write('\033[K')
        sys.stdout.flush()


def get_capabilities(base_url, use_token=False, qs=4):
    """This function makes a request to the WMS, using the token if needed,
    to obtain the Capabilities of the layer"""
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
        sys.stdout.flush()
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

    n_of_quadrants = qs

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
    """This function post processes the downloaded tiff file
    and sets its transparency
    """
    dataset = gdal.Open(input_tiff)
    if dataset is None:
        print("Failed to open the input TIFF file.")
        sys.stdout.flush()
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
    """This function merges the temp files obtained with the split requests
    into a single tiff file. If the process is successfull and the variable
    delete_temp_files is set to True, it will also delete the temp folder
    and its content
    """
    try:
        print("Merging TIFF files...", end='\r', flush=True)
        sys.stdout.flush()

        warp_options = gdal.WarpOptions(
            format='GTiff',
            creationOptions=["COMPRESS=LZW", "TILED=YES", "ALPHA=YES"]
        )

        gdal.Warp(destNameOrDestDS=output_file, srcDSOrSrcDSTab=files, options=warp_options)

        print(f"TIFF files merged successfully into {output_file}", end='\r', flush=True)
        sys.stdout.flush()

        if delete_temp_files:
            for file in files:
                if os.path.exists(file):
                    os.remove(file)
            if os.listdir(f'temp_{output_file.replace('.tiff', '')}') == []:
                os.removedirs(f'temp_{output_file.replace('.tiff', '')}')

    except Exception as e:
        print(f"Error during merging: {str(e)}")
        print('Exiting...')
        sys.stdout.flush()
        time.sleep(2)
        sys.exit(0)

def retry_download(bbox, i, wms_url, g_token, wh, temp_output_tiff, output_files):
    """If some chunk requests have failed this function will 
    try to download those parts of the file again"""
    try:
        options = [
                    '-co', 'ALPHA=YES',
                    '-co', 'TILED=YES',
                    '-co', 'COMPRESS=LZW'
                ]

        width, height = wh, wh

        wms_url_with_size = f'{wms_url}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&styles=default&LAYERS=0&WIDTH={width}&HEIGHT={height}\
            &FORMAT=image/png&TRANSPARENT=true&CRS=EPSG:4326&BBOX={bbox}&token={g_token}'

        wms_dataset = gdal.Open(wms_url_with_size)

        if wms_dataset is None:
            print("GDAL failed to open the WMS dataset.")
            sys.stdout.flush()
            return

        output_file_with_idx = temp_output_tiff.replace('.tiff', f'_{i}.tiff')
        gdal.Translate(output_file_with_idx, wms_dataset, format='GTiff', width=width, height=height, options=options)
        
        output_files.append(output_file_with_idx)

        set_transparency(output_file_with_idx, output_file_with_idx.replace('.tiff', '_transp.tiff'), transparency=0.5)
        output_files.remove(output_file_with_idx)
        if os.path.exists(output_file_with_idx):
            os.remove(output_file_with_idx)
        output_files.append(output_file_with_idx.replace('.tiff', '_transp.tiff'))
    except Exception as e:
        with open('error_log.txt', 'a') as f:
            f.write(f'{datetime.now()} - file at index {i} - BoundingBox: {bbox} - ERROR:{str(e)}')


def download_wms_layer(wms_url, output_tiff, wh, qs):
    """This is the main function. It will get the capabilities for the layer,
    make split requests to obtain the portions of the layer and if the process
    is successfull it will merge these files into the final tiff output
    """
    global step_begin
    global step_end
    global previous_line_len

    output_files = []
    time_diffs = []
    failed = []

    try:
        capabilities = get_capabilities(wms_url, use_token=True, qs=qs)

        max_width = capabilities['max_width']
        max_height = capabilities['max_height']

        width = max_width
        height = max_height

        width, height = wh, wh

        if f'temp_{output_tiff.replace('.tiff', '')}' not in os.listdir():
            os.mkdir(f'temp_{output_tiff.replace('.tiff', '')}')

        temp_output_tiff = os.path.join(f'temp_{output_tiff.replace('.tiff', '')}', output_tiff)

        g_token = get_token()

        for idx, bbox in enumerate(capabilities['bboxes']):
            options = [
                '-co', 'ALPHA=YES',
                '-co', 'TILED=YES',
                '-co', 'COMPRESS=LZW'
            ]

            wms_url_with_size = f'{wms_url}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&styles=default&LAYERS=0&WIDTH={width}&HEIGHT={height}\
                &FORMAT=image/png&TRANSPARENT=true&CRS=EPSG:4326&BBOX={bbox}&token={g_token}'

            try:
                wms_dataset = gdal.Open(wms_url_with_size)
            except:
                failed.append((bbox, i))
                continue

            if wms_dataset is None:
                print("GDAL failed to open the WMS dataset.")
                sys.stdout.flush()
                return
            
            tot_quadrants = qs * qs
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

            print('\r' + (' ' * previous_line_len), end='', flush=True)
            sys.stdout.flush()
            print(f'\rDownloading {i}/{tot_quadrants}...  {eta_str}', end='', flush=True)
            sys.stdout.flush()

            previous_line_len = len(f'\rDownloading {i}/{tot_quadrants}...  {eta_str}')

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

        if failed:
            print(f'\rRetrying failed downloads...', end='', flush=True)
            g_token = get_token()
            for idx, to_retry in enumerate(failed):
                print('\r' + (' ' * previous_line_len), end='', flush=True)
                sys.stdout.flush()
                print(f'\rRetrying {i} {idx+1}/{len(failed)}...', end='', flush=True)
                sys.stdout.flush()
                previous_line_len = len(f'\rRetrying {i} {idx}/{len(failed)}...')
                retry_download(to_retry[0], to_retry[1], wms_url, g_token, wh, temp_output_tiff, output_files)  
        
        print('\r' + ' ' * 150, end='\r', flush=True)
        sys.stdout.flush()

        merge_tiffs(output_files, output_tiff)
    except Exception as e:
        print(f"Error: {str(e)}")
        print('Exiting...')
        sys.stdout.flush()
        time.sleep(2)
        sys.exit(0)

def authenticate(file_name):
    url = "https://api.cesium.com/v1/assets"

    headers = {
        "Authorization": f"Bearer {CESIUM_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "name": file_name,
        "description": "GeoTIFF test upload",
        "type": "IMAGERY",
        "options": {
            "sourceType": "RASTER_IMAGERY"
        }
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload))
    response_data = response.json()

    if response.status_code == 201 or response.status_code == 200:
        return response_data
    else:
        print(response.status_code)
        print(f"Error: {response_data}")


def cesium_upload(file_path):
    file_name = os.path.basename(file_path)
    response_data = authenticate(file_name)

    bucket_name = response_data['uploadLocation']['bucket']
    prefix = response_data['uploadLocation']['prefix']
    access_key = response_data['uploadLocation']['accessKey']
    secret_key = response_data['uploadLocation']['secretAccessKey']
    session_token = response_data['uploadLocation']['sessionToken']

    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token
    )

    s3 = session.client('s3')

    with open(file_path, 'rb') as data:
        s3.upload_fileobj(data, bucket_name, prefix + file_name)

    upload_complete_url = response_data['onComplete']['url']
    completion_headers = {
    "Authorization": f"Bearer {CESIUM_TOKEN}"
    }

    response = requests.post(upload_complete_url, headers=completion_headers)

    if response.status_code == 200 or response.status_code == 204:
        print("Upload complete!")
    else:
        print(f"Error: {response.status_code} {response.text}")


if __name__ == "__main__":
    print('------WMS to TIFF------')
    sys.stdout.flush()
    
    # base_wms_url = 'https://webgis.abdac.it/server/services/ETT_PERIC_FRANA_DISTR/MapServer/WMSServer'
    # base_wms_url = 'https://webgis.abdac.it/server/services/Pericolosit%C3%A0_idraulica_Progetto_PAI_distr___solo_fluviale___bozza_/MapServer/WMSServer'

    # base_wms_url = input('Please write the URL to the WMS Layer:\n')
    # clear_previous_lines(n=2)

    urls = ['https://webgis.abdac.it/server/services/ETT_PERIC_FRANA_DISTR/MapServer/WMSServer', 'https://webgis.abdac.it/server/services/Pericolosit%C3%A0_idraulica_Progetto_PAI_distr___solo_fluviale___bozza_/MapServer/WMSServer']
    for i, url in enumerate(urls):
        print(i + 1, url)
    base_wms_url_idx = int(input('Select the layer by index:\n')) - 1
    base_wms_url = urls[base_wms_url_idx]
    clear_previous_lines(n=len(urls) + 2)

    print(f'You selected: {base_wms_url}')
    time.sleep(2)
    clear_previous_lines(n=1)

    qs = int(input('Enter in how many parts you want to split the request (will be valid for x and y axes):\n'))
    clear_previous_lines(n=2)

    wh = int(input('Enter a value for width and height resolution:\n'))
    clear_previous_lines(n=2)

    output_path = input('Please write a name for the output tiff file:\n')
    if not output_path.endswith('.tiff'):
        output_path += '.tiff'
    clear_previous_lines(n=2)

    print(f'Job started at {start_time}' + ' ' * 50)
    sys.stdout.flush()
    try:
        download_wms_layer(base_wms_url, output_path, wh, qs)
        
        print(f'Job finished at {datetime.now()}' + ' ' * 50)
        sys.stdout.flush()
        cwd = os.getcwd()
        print(f'File saved as {output_path} in {cwd}')
        sys.stdout.flush()

        cesium_upload(output_path)

    except Exception as e:
        print(f'Something went wrong: {str(e)}')
        print('Exiting...')
        sys.stdout.flush()
        time.sleep(2)
        sys.exit(0)
