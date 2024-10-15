from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
from utils import get_existing_assets
from osgeo import gdal
from config import *
import numpy as np
import requests
import boto3
import json
import time
import sys
import os


previous_line_len = 0


def exists(name, id=None):
    on_cesium = False
    in_json = False
    cesium_assets = get_existing_assets()
    for cesium_asset in cesium_assets:
        if cesium_asset['name'] == name or cesium_asset['id'] == id:
            on_cesium = True
            break
    with open(os.path.join(CONFIGS_DIR, ASSETS_JSON), 'r') as f:
        json_content = json.load(f)
    found_doc = None
    for doc in json_content:
        if doc["name"] == name:
            found_doc = doc
            in_json = True
            break
    if on_cesium and in_json:
        return True, found_doc
    else:
        return False, found_doc


def create_new_asset(name, url, description):
    payload = {
        "name": name,
        "description": description,
        "type": "IMAGERY",
        "options": {
            "sourceType": "RASTER_IMAGERY"
        }
    }

    response = requests.post(CESIUM_BASE_URL, headers=HEADERS["with_payload"], data=json.dumps(payload))
    response_data = response.json()

    if response.status_code == 201 or response.status_code == 200:
        bucket_name = response_data['uploadLocation']['bucket']
        prefix = response_data['uploadLocation']['prefix']
        id = prefix.split('/')[-2]
        access_key = response_data['uploadLocation']['accessKey']
        secret_key = response_data['uploadLocation']['secretAccessKey']
        session_token = response_data['uploadLocation']['sessionToken']
        upload_complete_url = response_data['onComplete']['url']

        new_doc = {
            "name": name,
            "id": id,
            "url": url,
            "bucket_name": bucket_name,
            "prefix": prefix,
            "access_key": access_key,
            "secret_key": secret_key,
            "session_token": session_token,
            "upload_complete_url": upload_complete_url
        }

        with open(os.path.join(CONFIGS_DIR, ASSETS_JSON)) as f:
            json_content = json.load(f)

        json_content.append(new_doc)

        with open(os.path.join(CONFIGS_DIR, ASSETS_JSON), 'w') as f:
            json.dump(json_content, f, indent=4)

        return new_doc
    else:
        print(f"Error:{response.status_code}:{response_data}")


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

    cap_dict['bboxes'] = []

    step_x = (maxx - minx) / n_of_quadrants
    step_y = (maxy - miny) / n_of_quadrants

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
        # print("Merging TIFF files...", end='\r', flush=True)
        sys.stdout.flush()

        warp_options = gdal.WarpOptions(
            format='GTiff',
            creationOptions=["COMPRESS=LZW", "TILED=YES", "ALPHA=YES"]
        )

        dest = os.path.join(FILES_DIR, output_file)
        gdal.Warp(destNameOrDestDS=dest, srcDSOrSrcDSTab=files, options=warp_options)

        # print(f"TIFF files merged successfully into {dest}", end='\r', flush=True)
        sys.stdout.flush()

        if DELETE_TEMP_FILES:
            for file in files:
                if os.path.exists(file):
                    os.remove(file)
            subdir = os.path.join(FILES_DIR, f'temp_{output_file.replace('.tiff', '')}')
            if os.listdir(subdir) == []:
                os.removedirs(subdir)

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


class Asset:
    def __init__(self, document):
        self.name = document['Name']
        self.url = document['Url']
        self.id = document['Id']
        self.connection_info = None

    def download_wms_layer(self, quadrants, quadrant_size):
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
            capabilities = get_capabilities(self.url, use_token=True, qs=quadrants)

            width, height = quadrant_size, quadrant_size

            if not self.name.endswith('.tiff'):
                self.name += '.tiff'

            if f'temp_{self.name.replace('.tiff', '')}' not in os.listdir(FILES_DIR):
                os.makedirs(os.path.join(FILES_DIR, f'temp_{self.name.replace('.tiff', '')}'))

            temp_output_tiff = os.path.join(FILES_DIR, f'temp_{self.name.replace('.tiff', '')}', self.name)

            g_token = get_token()

            for idx, bbox in enumerate(capabilities['bboxes']):
                options = [
                    '-co', 'ALPHA=YES',
                    '-co', 'TILED=YES',
                    '-co', 'COMPRESS=LZW'
                ]

                wms_url_with_size = f'{self.url}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&styles=default&LAYERS=0&WIDTH={width}&HEIGHT={height}\
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
                
                tot_quadrants = quadrants * quadrants
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
                    retry_download(to_retry[0], to_retry[1], self.url, g_token, quadrant_size, temp_output_tiff, output_files)  
            
            print('\r' + ' ' * 150, end='\r', flush=True)
            sys.stdout.flush()

            merge_tiffs(output_files, self.name)
        except Exception as e:
            print(f"Error: {str(e)}")
            print('Exiting...')
            sys.stdout.flush()
            time.sleep(2)
            sys.exit(0)

    
    def create_new_asset(self):
        payload = {
            "name": self.name,
            "description": "",
            "type": "IMAGERY",
            "options": {
                "sourceType": "RASTER_IMAGERY"
            }
        }

        response = requests.post(CESIUM_BASE_URL, headers=HEADERS["with_payload"], data=json.dumps(payload))
        response_data = response.json()

        if response.status_code == 201 or response.status_code == 200:
            bucket_name = response_data['uploadLocation']['bucket']
            prefix = response_data['uploadLocation']['prefix']
            id = prefix.split('/')[-2]
            access_key = response_data['uploadLocation']['accessKey']
            secret_key = response_data['uploadLocation']['secretAccessKey']
            session_token = response_data['uploadLocation']['sessionToken']
            upload_complete_url = response_data['onComplete']['url']

            connection_info = {
                'bucket_name': bucket_name,
                'prefix': prefix,
                'id': id,
                'access_key':access_key,
                'secret_key': secret_key,
                'session_token': session_token,
                'upload_complete_url': upload_complete_url
                }

            self.id = id
            self.connection_info = connection_info

        else:
            print(f"Error:{response.status_code}:{response_data}")


    def upload_to_cesium(self):
        file_path = os.path.join(FILES_DIR, self.name)
        try:
            session = boto3.Session(
                aws_access_key_id=self.connection_info['access_key'],
                aws_secret_access_key=self.connection_info['secret_key'],
                aws_session_token=self.connection_info['session_token']
            )
            s3 = session.client('s3')
            with open(file_path, 'rb') as data:
                s3.upload_fileobj(data, self.connection_info['bucket_name'], self.connection_info['prefix'] + self.name)
        except Exception as e:
            print('err:', str(e))
        try:
            requests.post(self.connection_info['upload_complete_url'], headers=HEADERS['no_payload'])
        except:
            pass