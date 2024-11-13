from utils import (
    delete_local_layer,
    clear_previous_lines,
    delete_cesium_asset,
    delete_dir,
)
from asset import Asset
from config import *
import platform
import ftplib
import json
import os
import time
import sys
import warnings


warnings.filterwarnings("ignore")


CHANGEABLE_FIELDS = [
    "ArcgisHierarchyId",
    "Url",
    "ParentUrl",
    "ParentName",
    "ArcgisParentUrl",
    "ArcgisWmsUrl"
]
MULTIPLE_FIELDS = ["ParentName", "ParentUrl"]


"""
In this function we make the call to a server in order to obtain the json files we need
to proceed with the main scope of the app, to be able to modify and update the layer data 
and generate a TIFF file
"""
def download_ftp():
    try:
        current_dir = os.getcwd()
        ftp = ftplib.FTP()
        ftp.connect(HOSTNAME_FTP, PORT_FTP)
        ftp.login(USERNAME_FTP, PASSWORD_FTP)
        cwd = ftp.cwd("Layers") # Specify the dir where the files are
        files = ftp.nlst()
        json_files = []
        for file in files:
            if file.endswith(".json"):
                save_path = os.path.join(current_dir, file)
                with open(save_path, "wb") as f:
                    ftp.retrbinary("RETR " + file, f.write)
                json_files.append(save_path)
        ftp.quit()
        return json_files
    except ftplib.all_errors as e:
        print(f"FTP error: {e}")
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []


"""
Once we have obtained the files and we have done the modifications,
we upload on the server the files modified. 
After that, we remove the files from the local
"""
def upload_ftp():
    try:
        session = ftplib.FTP()
        session.connect(HOSTNAME_FTP, PORT_FTP)
        session.login(USERNAME_FTP, PASSWORD_FTP)
        session.cwd("Layers")
        changed_files = [f for f in os.listdir(os.getcwd()) if f.endswith(".json")]
        for file in changed_files:
            with open(file, "rb") as local_file:
                session.storbinary(f"STOR {file}", local_file)
            os.remove(file)
        session.quit()
    except ftplib.all_errors as e:
        print(f"FTP error: {e}")
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []


"""
This function is only applied when we execute the code from the .exe, 
modifying the dimensions of the window of the console
"""
def maximize_terminal():
    if platform.system() == "Windows":
        os.system("mode con cols=150 lines=50")
    elif platform.system() in ("Linux", "Darwin"):
        rows, cols = os.popen("stty size", "r").read().split()
        os.system(f"resize -s {rows} {cols}")


"""
With this function we allow the user to interact with the console in order to let them to 
choose the layer they want, or to do other different actions, like change the values of 
specific fields inside the layer selected by the user.
"""
def main():
    print("""--- XR LAYERS UPDATER ---""")
    # opening files downloaded via FTP
    try:
        with open(ARCGIS_JSON, "r", encoding="utf-8") as f:
            arcgis_layers_json = json.load(f)
    except Exception as e:
        print(f"Error opening {ARCGIS_JSON}: {str(e)}")
        print("Exiting...")
        time.sleep(5)
        return
    try:
        with open(ASSETS_JSON, "r", encoding="utf-8") as f:
            cesium_layers_json = json.load(f)
    except Exception as e:
        print(f"Error opening {ASSETS_JSON}: {str(e)}")
        print("Exiting...")
        time.sleep(5)
        return
    # First interaction between the app and the user
    # "y" -> proceed with the display of the list of layers
    # "n" -> closing the app
    while True:
        change = input("Do you want to change a layer? [y/n]\n")
        if change.lower() == "y":
            change = True
            clear_previous_lines(n=2)
            break
        if change.lower() == "n":
            clear_previous_lines(n=1)
            print("Exiting...")
            time.sleep(2)
            return
        else:
            print("Please write y for yes or n for no")
            time.sleep(2)
            clear_previous_lines(n=3)
    # Displaying the list of layers downloaded via FTP and opened in the beginning of the function
    layers = arcgis_layers_json + cesium_layers_json
    print("Available layers from the JSON files:")
    for index, layer in enumerate(layers):
        str_index = str(index + 1).ljust(2)
        layer_name = layer["Name"]
        print(f"{str_index}: {layer_name}")
    message_str = "Select a layer by entering its index or enter 0 to exit:"
    # Second interaction between the app and the user. 
    # Index between 1 and 32 -> Select a layer
    # Index equal to 0 -> Closing the app
    # Index above 32 -> Wrong value
    while True:
        try:
            print(message_str)
            chosen = input()
            if chosen == "0":
                print("Exiting...")
                time.sleep(2)
                return
            chosen = int(chosen) - 1
            if chosen < 0 or chosen > len(layers) - 1:
                raise
            if 0 <= chosen < len(layers):
                clear_previous_lines(n=len(layers) + 3)
                break
        except:
            clear_previous_lines(n=2)
            message_str = "Please enter a valid index or enter 0 to exit:"
    found_layer = layers[chosen]
    layer_to_print = {k: v for k, v in found_layer.items() if k in CHANGEABLE_FIELDS}
    dict_lines = 2
    # Displaying the fields of the layer the user chose in the format of a dictionary
    print("You selected:\n{")
    for k, v in layer_to_print.items():
        if isinstance(v, int):
            print(f'"{k}": {v}')
        else:
            print(f'"{k}": "{v}"')
        dict_lines += 1
    print("}")
    print("Modifiable fields in the JSON document:")
    # Displaying the modifiable fields inside the layer we chose
    modifiable_items = [k for k in found_layer.keys() if k in CHANGEABLE_FIELDS]
    for i, k in enumerate(modifiable_items):
        print(f"{i + 1}: {k}")
    message_str = (
        "What do you want to change? Please enter the index or enter 0 to exit:"
    )
    # Third interaction between the user and the app. Selecting the field by index
    # Index equal to 0 -> Closing the app
    while True:
        try:
            print(message_str)
            to_change = input()
            if to_change == "0":
                print("Exiting...")
                time.sleep(2)
                return
            to_change = int(to_change) - 1
            if to_change < 0 or to_change > len(modifiable_items) - 1:
                raise
            if list(layer_to_print.keys())[to_change]:
                selected_key = list(layer_to_print.keys())[to_change]
                print(f"You selected {selected_key}")
                time.sleep(2)
                clear_previous_lines(n=4 + len(layer_to_print.keys()))
            break
        except:
            clear_previous_lines(n=2)
            message_str = "Please select a valid index or enter or enter 0 to exit:"
    print(f"Old {selected_key}: {found_layer[selected_key]}")
    old_value = found_layer[selected_key]
    multiple = False
    if selected_key in MULTIPLE_FIELDS:
        # Fourth interaction between the user and the app
        # In the case the user selected a field that is stored in a specific list called MULTIPLE_FIELDS,
        # they will have to decide if they apply the changes not only to the layer we chose,
        # but also to the same field in the rest of the layers
        while True:
            print(
                f"Do you want to apply the change to all the documents with the same value of {selected_key}? [y/n]"
            )
            multiple_inp = input()
            if multiple_inp.lower() == "y":
                multiple = True
                clear_previous_lines(n=2)
                break
            if multiple_inp.lower() == "n":
                clear_previous_lines(n=2)
                multiple = False
                break
            else:
                print("Please write y for yes or n for no")
                time.sleep(2)
                clear_previous_lines(n=3)
    # Fifth interaction
    # The user will have the capacity of changing the value stored in a determined field in the layer
    # If the input is 0 -> Closing the app
    print(f"Write the new {selected_key} or enter 0 to exit:")
    new_value = input()
    if new_value == "0":
        print("Exiting...")
        time.sleep(2)
        return
    while True:
        # Sixth interaction
        # The user has to decide if proceed or not to proceed with the changes made
        # "y" -> proceed with the changes and update the field
        # "n" -> Closing the app 
        print("Do you want to proceed and update? [y/n]")
        proceed = input()
        if proceed.lower() == "y":
            clear_previous_lines(n=5 + dict_lines + 1)
            break
        if proceed.lower() == "n":
            print("Exiting...")
            time.sleep(2)
            return
        else:
            print("Please write y for yes or n for no")
            time.sleep(2)
            clear_previous_lines(n=3)
    print(f"Updating {selected_key} as {new_value}")
    found = False
    for layer in arcgis_layers_json:
        if not multiple and found_layer == layer:
            found = True
            layer[selected_key] = new_value
        elif multiple and layer[selected_key] == old_value:
            found = True
            layer[selected_key] = new_value
    if found:
        # Opening again the files downloaded via FTP in order to write the changes made
        with open(ARCGIS_JSON, "w") as f:
            json.dump(arcgis_layers_json, f, indent=4)
        print("Json document updated")
        print("Exiting...")
        time.sleep(2)
        return

    for layer in cesium_layers_json:
        if found_layer == layer:
            layer[selected_key] = new_value
            with open(ASSETS_JSON, "w", encoding="utf-8") as f:
                json.dump(cesium_layers_json, f, indent=4)
            print("Json document updated")
            clear_previous_lines(n=2)
            # In the case the selected field has the name "ArcgisWmsUrl",
            # the process to create a tiff file is about to start
            if selected_key == "ArcgisWmsUrl":
                update = False
                while True:
                    # Last interaction
                    # "y" -> proceed with the creation of the TIFF file
                    # "n" -> closing the app
                    print(
                        "Do you want to regenerate the Layer with the updated Url? [y/n]"
                    )
                    print("The process might take some time")
                    proceed_updating = input()
                    if proceed_updating.lower() == "y":
                        clear_previous_lines(n=3)
                        update = True
                        break
                    if proceed_updating.lower() == "n":
                        update = False
                        break
                    else:
                        print("Please write y for yes or n for no")
                        time.sleep(2)
                        clear_previous_lines(n=4)
                if not update:
                    break
                asset = Asset(found_layer)
                try:
                    print("Downloading layer from updated Url...")
                    asset.download_wms_layer(
                        quadrants=N_QUADRANTS, quadrant_size=QUADRANT_SIZE
                    )
                except Exception as e:
                    print(f"Something went wrong when downloading the layer: {str(e)}")
                    print("Exiting...")
                    delete_dir("temp_" + asset.name)
                    time.sleep(2)
                    return
                asset.create_new_asset()
                clear_previous_lines(n=2)
                print("Uploading downloaded layer to Cesium...")
                try:
                    pass
                    asset.upload_to_cesium()
                except Exception as e:
                    print(
                        f"Something went wrong when uploading the layer to Cesium: {str(e)}"
                    )
                    print("Exiting...")
                    time.sleep(2)
                    return
                clear_previous_lines(n=1)
                try:
                    pass
                    delete_cesium_asset(found_layer["CesiumId"])
                except Exception as e:
                    print(
                        f"Something went wrong when deleting the old layer on Cesium: {str(e)}"
                    )
                    print("Exiting...")
                    time.sleep(2)
                    return
                delete_local_layer(asset.name)# + ".tiff")
                for layer in cesium_layers_json:
                    if found_layer == layer:
                        layer["Id"] = int(asset.id)
                        with open(ASSETS_JSON, "w", encoding="utf-8") as f:
                            json.dump(cesium_layers_json, f, indent=4)
                break
    print("Process completed")
    print("Exiting...")
    time.sleep(2)
    clear_previous_lines(n=2)
    return


if __name__ == "__main__":
    download_ftp()
    maximize_terminal()
    main()
    upload_ftp()
    sys.exit(0)
