from osgeo import gdal
from xml.etree import ElementTree as ET
import requests
import numpy as np
import os

USERNAME = os.getenv('USERNAME')
PASSWORD = os.getenv('PASSWORD')

gdal.SetConfigOption('GDAL_CACHEMAX', '2048')
os.environ['GDAL_HTTP_TIMEOUT'] = '600'

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

    capabilities = ET.fromstring(response.content)

    cap_dict = {}

    namespace = {'ns0': 'http://www.opengis.net/wms'}

    cap_dict['max_width'] = capabilities.find('.//ns0:MaxWidth', namespace).text
    cap_dict['max_height'] = capabilities.find('.//ns0:MaxHeight', namespace).text

    time_dimension = capabilities.find('.//ns0:Dimension[@name="time"]', namespace)
    cap_dict['time'] = time_dimension.attrib['default'] if time_dimension is not None else None

    minx = capabilities.find('.//ns0:BoundingBox', namespace).attrib.get('minx')
    maxx = capabilities.find('.//ns0:BoundingBox', namespace).attrib.get('maxx')
    miny = capabilities.find('.//ns0:BoundingBox', namespace).attrib.get('miny')
    maxy = capabilities.find('.//ns0:BoundingBox', namespace).attrib.get('maxy')
    cap_dict['bbox']= f'{miny},{minx},{maxy},{maxx}'

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


def download_wms_layer(wms_url, output_tiff):
    try:
        capabilities = get_capabilities(wms_url, use_token=True)

        max_width = capabilities['max_width']
        max_height = capabilities['max_height']

        width = max_width
        height = max_height

        width, height = 5000, 5000 
        # working up until 50000, 50000. with higher values server goes into timeout
        # splitting requests into chunks and merging the output 

        bbox = capabilities['bbox']
        
        if capabilities['time']:
            time = capabilities['time']

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
        
        # print_dataset_info(wms_dataset)
        print('gdal.Translate...')
        gdal.Translate(output_tiff, wms_dataset, format='GTiff', width=width, height=height, options=options)
        print('Elaborating tiff file...')
        set_transparency(output_tiff, output_tiff.replace('.tiff', '_transp.tiff'), transparency=0.5)

        print(f"Downloaded WMS layer and saved as {output_tiff}")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    
    base_wms_url = 'https://webgis.abdac.it/server/services/ETT_PERIC_FRANA_DISTR/MapServer/WMSServer'
    # base_wms_url = 'https://webgis.abdac.it/server/services/Pericolosit%C3%A0_idraulica_Progetto_PAI_distr___solo_fluviale___bozza_/MapServer/WMSServer'

    output_path = input('Please write a name for the output .tiff file:\n')
    if not output_path.endswith('.tiff'):
        output_path += '.tiff'

    download_wms_layer(base_wms_url, output_path)
