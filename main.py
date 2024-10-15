from utils import  delete_local_layer, clear_previous_lines, delete_cesium_asset
from asset import Asset
from config import *
import json
import time
import sys
import warnings

warnings.filterwarnings("ignore")

CHANGEABLE_FIELDS = ['Name', 'Url', 'ParentUrl']

def main():
    try:
        with open(ARCGIS_JSON, 'r', encoding='utf-8') as f:
            arcgis_layers_json = json.load(f)
    except Exception as e:
        print(f'Error opening {ARCGIS_JSON}: {str(e)}')
    try:
        with open(ASSETS_JSON, 'r', encoding='utf-8') as f:
            cesium_layers_json = json.load(f)
    except Exception as e:
        print(f'Error opening {ASSETS_JSON}: {str(e)}')
    while True:
        change = input('Do you want to change a layer? [y/n]\n')
        if change.lower() == 'y':
            change = True
            clear_previous_lines(n=3)
            break
        if change.lower() == 'n':
            clear_previous_lines(n=1)
            print('Exiting...')
            time.sleep(2)
            return
        else:
            clear_previous_lines(n=2)
    layers = arcgis_layers_json + cesium_layers_json
    for index, layer in enumerate(layers):
        str_index = str(index + 1).ljust(2)
        print(f'{str_index}: {layer['Name']}')
    while True:
        try:
            print('Select a layer by entering its index or enter 0 to exit:')
            chosen = input()
            if chosen == '0':
                print('Exiting...')
                time.sleep(2)
                return
            chosen = int(chosen) - 1
            if chosen < 0 or chosen > len(layers) -1: raise
            if 0 <= chosen < len(layers):
                clear_previous_lines(n=len(layers) + 2)
                break
        except:
            clear_previous_lines(n=2)
            print('Please enter a valid index')
            time.sleep(1)
            clear_previous_lines(n=1)  
            continue
    found_layer = layers[chosen]
    layer_to_print = {k:v for k, v in found_layer.items() if k in CHANGEABLE_FIELDS}
    dict_lines = 2
    print('You selected:\n{')
    for k, v in layer_to_print.items():
        if isinstance(v, int):
            print(f'"{k}": {v}')
        else:
            print(f'"{k}": "{v}"')
        dict_lines += 1
    print('}')
    modifiable_items = [k for k in found_layer.keys() if k in CHANGEABLE_FIELDS]
    for i, k in enumerate(modifiable_items):
            print(f'{i + 1}: {k}')
    while True:
        try:
            print('What do you want to change? Please enter the index or enter 0 to exit:')
            to_change = input()
            if to_change == '0':
                print('Exiting...')
                time.sleep(2)
                return
            to_change = int(to_change) - 1
            if to_change < 0 or to_change > len(modifiable_items) -1: raise
            if list(layer_to_print.keys())[to_change]:
                selected_key = list(layer_to_print.keys())[to_change]
                print(f'You selected {selected_key}')
                time.sleep(2)
                clear_previous_lines(n=3 + len(layer_to_print.keys()))
            break
        except:
            clear_previous_lines(n=2)
            chosen = input('Please select a valid index:\n')
    print(f'Old {selected_key}: {found_layer[selected_key]}')
    print(f'Write the new {selected_key}:')
    while True:
        new_value = input()
        print('Do you want to proceed and update? [y/n] To exit enter 0')
        proceed = input()
        if proceed == '0':
            print('Exiing...')
            time.sleep(2)
            return
        if proceed.lower() == 'y':
            clear_previous_lines(n=5 + dict_lines + 1)
            break
        if proceed.lower() == 'n':
            clear_previous_lines(n=3)
        else:
            clear_previous_lines(n=3)
    print(f'Updating {selected_key} as {new_value}')
    for layer in arcgis_layers_json:
        if found_layer == layer:
            layer[selected_key] = new_value
            with open(ARCGIS_JSON, 'w') as f:
                json.dump(arcgis_layers_json, f, indent=4)
            print('Json document updated')
            print('Exiting...')
            time.sleep(2)
            return
    for layer in cesium_layers_json:
        if found_layer == layer:
            layer[selected_key] = new_value
            with open(ASSETS_JSON, 'w', encoding='utf-8') as f:
                json.dump(cesium_layers_json, f, indent=4)
            print('Json document updated')
            clear_previous_lines(n=2)
            if selected_key == 'Url':
                print('Downloading layer from updated Url...')
                asset = Asset(found_layer)
                asset.download_wms_layer(quadrants=N_QUADRANTS, quadrant_size=QUADRANT_SIZE)
                asset.create_new_asset()
                clear_previous_lines(n=2)
                print('Uploading downloaded layer to Cesium...')
                asset.upload_to_cesium()
                clear_previous_lines(n=1)
                delete_cesium_asset(found_layer['Id'])
                delete_local_layer(asset.name)
                for layer in cesium_layers_json:
                    if found_layer == layer:
                        layer['Id'] = int(asset.id)
                        with open(ASSETS_JSON, 'w', encoding='utf-8') as f:
                            json.dump(cesium_layers_json, f, indent=4)
                break
    print('Process completed')
    print('Exiting...')
    time.sleep(2)
    clear_previous_lines(n=2)
    return


if __name__ == '__main__':
    main()
    sys.exit(0)













