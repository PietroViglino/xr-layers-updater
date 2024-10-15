from config import *
from colorama import Cursor
import requests
import sys

def clear_previous_lines(n=2):
    """This function clears the n previously written lines in the terminal
    """
    for _ in range(n):
        sys.stdout.write(Cursor.UP(1))
        sys.stdout.write('\033[K')
        sys.stdout.flush()

def clean_empty_assets():
    ids_to_delete = []
    url = "https://api.cesium.com/v1/assets"
    headers = {
        "Authorization": f"Bearer {CESIUM_TOKEN}"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        assets = response.json()["items"]
        for asset in assets:
            if asset['bytes'] == 0 and asset['status'] == 'AWAITING_FILES':
                ids_to_delete.append((asset['name'], asset['id']))
    if ids_to_delete:
        for name, id in ids_to_delete:
            try:
                resp = requests.delete(f'{url}/{id}', headers=headers)
                if 200 <= resp.status_code < 300:
                    print(f'{resp.status_code}: Asset {name} with id {id} deleted')
                else:
                    print(f'{resp.status_code}: Couldn\'t delete asset {name} with id {id}')
            except Exception as e:
                print(f'Error deleting asset {name} with {id}: {str(e)}')
    else:
        print('No empty assets to delete')


def delete_cesium_asset(id):
    url = "https://api.cesium.com/v1/assets"
    headers = {
        "Authorization": f"Bearer {CESIUM_TOKEN}"
    }
    try:
        resp = requests.delete(f'{url}/{id}', headers=headers)
        if 200 <= resp.status_code < 300:
            pass
        else:
            print(f'{resp.status_code}: Couldn\'t delete asset with id {id}')
    except Exception as e:
        print(f'Error deleting asset with {id}: {str(e)}')

def delete_local_layer(name):
    for file in os.listdir(FILES_DIR):
        if file == name:
            try:
                os.remove(file)
            except:
                pass


def get_existing_assets():
    url = "https://api.cesium.com/v1/assets"
    headers = {
        "Authorization": f"Bearer {CESIUM_TOKEN}"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        assets = response.json()["items"]
        return assets
    else:
        print(f"Failed to get the assets list: {response.status_code} | {response.text}")
        return None