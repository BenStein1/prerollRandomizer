# --Plex Pre-roll Randomizer Toolkit--
# Written by Kaitlyn Hofmann and Ben Conner
# Assisted by ChatGPT 3.5 and ChatGPT 4
# dev@connertechnical.com
# 04/23/2023

import os
import subprocess
import sys
import random
import shutil
import datetime
import re
import configparser
import textwrap
import secrets
import string
import glob
from urllib.parse import quote_plus, urlencode

try:
    from plexapi.server import PlexServer
    import yaml
except:
    print('\033[91mERROR:\033[0m PlexAPI or PyYAML is not installed.')
    x = input("Do you want to install them? y/n:")
    if x == 'y':
        subprocess.check_call([sys.executable, "-m", "pip", "install", 'PlexAPI', 'PyYAML'])
        from plexapi.server import PlexServer
        import yaml
    elif x == 'n':
        sys.exit()

script_dir = os.path.dirname(os.path.abspath(__file__))
config_folder = os.path.join(script_dir, 'config')

if not os.path.exists(config_folder):
    os.makedirs(config_folder)

config_file = os.path.join(config_folder, 'prerollConfig.yaml')
print(f"Config file: {config_file}")

today = datetime.datetime.now().date()

#Get the width of the user's terminal
terminal_width = shutil.get_terminal_size((80, 20)).columns

# Load the YAML configuration file
def load_yaml(config_file):
    config = {}
    likely_folders = []
    today = datetime.datetime.now().date()
    with open(config_file, "r") as f:
        config_data = yaml.safe_load(f)
        settings = config_data["root"]["settings"]
        config["plex_url"] = settings["plex_url"]
        config["plex_token"] = settings["plex_token"]
        config["source_folder"] = settings["source_folder"]
        config["destination_folder"] = settings["destination_folder"]
        config["log_file"] = settings["log_file"]
        config["state_file"] = settings["state_file"]
        config["allowed_extensions"] = set(settings["allowed_extensions"])

        for folder_config in config_data["root"]["config"]:
            folder = folder_config["folder"]
            name = folder["name"]
            enabled = folder.get("enabled", False)
            exclusive = folder.get("exclusive", False)
            likely = folder.get("likely", False)
            if likely:
                likely_folders.append(name)
            start_date = folder.get("start_date")
            end_date = folder.get("end_date")
            if start_date:
                start_month, start_day = map(int, start_date.split("-"))
                start_date = datetime.date(today.year, start_month, start_day)
            if end_date:
                end_month, end_day = map(int, end_date.split("-"))
                end_date = datetime.date(today.year, end_month, end_day)
                if end_date < start_date:
                    end_date = datetime.date(today.year+1, end_month, end_day)
            config[name] = [(start_date, end_date), enabled, exclusive, likely]

    return config, config_data, likely_folders


def load_state_data(state_file):
    if os.path.isfile(state_file):
        with open(state_file, 'r') as f:
            root = yaml.safe_load(f)
    else:
        root = {"preroll": []}
    return root


def update_and_load_state_data(state_file, root):
    with open(state_file, 'w') as f:
        yaml.dump(root, f)

    with open(state_file, 'r') as f:
        state_data = yaml.safe_load(f)
    return state_data


def log_to_file(message, log_file):
    # Get the current date and time
    now = datetime.datetime.now()

    # Calculate the date one month ago
    one_month_ago = now - datetime.timedelta(days=30)

    # Read the existing log entries, if the log file exists
    if os.path.isfile(log_file):
        with open(log_file, 'r') as f:
            log_lines = f.readlines()
    else:
        log_lines = []

    # Remove log entries older than one month
    updated_log_lines = []
    for line in log_lines:
        try:
            log_entry_time = datetime.datetime.fromisoformat(line.split(' - ')[0])
            if log_entry_time >= one_month_ago:
                updated_log_lines.append(line)
        except ValueError:
            continue

    # Add the new log entry
    updated_log_lines.append(f"{now} - {message}\n")

    # Write the updated log entries to the log file
    with open(log_file, 'w') as f:
        f.writelines(updated_log_lines)

def generate_guid(length):
    #Generate a random GUID with the specified length and character set.
    #Parameters:
    #   length (int): The length of the GUID to generate.
    #   alphabet (str): The set of characters to use for the GUID.

    #Returns:
    #    str: The generated GUID.

    alphabet = string.ascii_letters + string.digits
    guid = ''.join(secrets.choice(alphabet) for i in range(length))
    return guid


def check_and_reset_eligible_folders(root, eligible_sub_folders):
    all_used = True
    for folder in eligible_sub_folders:
        folder_files = [file_elem for file_elem in root["preroll"] if file_elem["sub_folder"] == folder]

        if not folder_files:
            continue
        for file_elem in folder_files:
            if file_elem["status"] == "unused":
                all_used = False
                break
        if not all_used:
            break

    if all_used:
        for folder in eligible_sub_folders:
            folder_files = [file_elem for file_elem in root["preroll"] if file_elem["sub_folder"] == folder]
            for file_elem in folder_files:
                file_elem["status"] = "unused"

def check_and_reset_likely_folders(root, likely_sub_folders):
    for folder in likely_sub_folders:
        folder_files = [file_elem for file_elem in root["preroll"] if file_elem["sub_folder"] == folder]
        unused_files = [file_elem for file_elem in folder_files if file_elem["status"] == "unused"]
        if not unused_files:  # If there are no unused files in this folder
            for file_elem in folder_files:
                file_elem["status"] = "unused"  # Reset all files in the folder



def output_available_media(root, eligible_sub_folders, log_file):
    print(f"Eligible sub_folders: {eligible_sub_folders}")
    log_to_file(f"  Eligible sub_folders: {eligible_sub_folders}", log_file)
    for folder in eligible_sub_folders:
        folder_files = [file_elem for file_elem in root["preroll"] if file_elem["sub_folder"] == folder]
        unused_files_count = len([file_elem for file_elem in folder_files if file_elem["status"] == "unused"])
        print(f"Available media in {folder}: {unused_files_count}")
        log_to_file(f"  Available media in {folder}: {unused_files_count}", log_file)


def reset_all_files(root):
    for file_elem in root["preroll"]:
        file_elem["status"] = "unused"


def add_new_files(root, folder_path, allowed_extensions, sub_folder="", config=None):
    current_files = {file_elem["name"] for file_elem in root["preroll"]}
    folder_items = set(os.listdir(folder_path))

    for item in folder_items:
        item_path = os.path.join(folder_path, item)
        #print(f"Checking item: {item_path}")  # Add this print statement

        if os.path.isfile(item_path):
            _, file_ext = os.path.splitext(item)

            if file_ext.lower() in allowed_extensions:
                item_key = os.path.join(sub_folder, item)

                if item_key not in current_files:
                    new_entry = {"name": item_key, "status": "unused", "sub_folder": sub_folder}
                    root["preroll"].append(new_entry)
        elif os.path.isdir(item_path):
            new_sub_folder = os.path.join(sub_folder, item)
            add_new_files(root, item_path, allowed_extensions, new_sub_folder)


# Function to clear the destination folder
def clear_destination_folder(destination_folder, allowed_extensions):
    for ext in allowed_extensions:
        for file in glob.glob(os.path.join(destination_folder, f"*{ext}")):
            os.remove(file)


def filter_unused_files(root, eligible_sub_folders):
    if eligible_sub_folders:
        unused_files = [
            file_elem["name"]
            for file_elem in root["preroll"]
            if file_elem["status"] == "unused" and file_elem["sub_folder"] in eligible_sub_folders
        ]
    else:
        unused_files = [file_elem["name"] for file_elem in root["preroll"] if file_elem["status"] == "unused"]
    return unused_files


def process_unused_files(root, source_folder, destination_folder, unused_files, log_file):
    num_files_to_pick = min(3, len(unused_files))

    random_files = random.sample(unused_files, num_files_to_pick)

    destination_files = []

    for i, random_file in enumerate(random_files):
        file_name, file_ext = os.path.splitext(random_file)

        guid = generate_guid(10)
        destination_file = os.path.join(destination_folder, f"Preroll_{guid}{file_ext}")

        print(f"Selection{i+1}: {random_file}  --  Preroll_{guid}{file_ext}")
        log_to_file(f"Selection{i+1}: {random_file}  --  Preroll_{guid}{file_ext}", log_file)
        print(f"      {destination_file}")

        destination_files.append(destination_file)

        file_elem = next(file for file in root["preroll"] if file["name"] == random_file)
        sub_folder = file_elem["sub_folder"]

        source_file = os.path.join(source_folder, random_file)
        shutil.copy2(source_file, destination_file)

        file_elem["status"] = "used"

    return destination_files


def remove_missing_files(root, source_folder):
    file_elements = root["preroll"]
    indices_to_remove = []

    for i, file_elem in enumerate(file_elements):
        file_name = file_elem["name"]
        file_path = os.path.join(source_folder, file_name)

        if not os.path.exists(file_path):
            print(f"Removing missing file: {file_name}")
            indices_to_remove.append(i)

    # Remove the files in reverse order to avoid index errors
    for index in sorted(indices_to_remove, reverse=True):
        del root["preroll"][index]


def update_plex_settings(plex_url, plex_token, destination_files):
    # Connect to the Plex server
    plex = PlexServer(plex_url, plex_token)

    # Get the settings object for the server
    settings = plex.settings

    # Get the current value of the cinemaTrailersPrerollID setting
    pre_roll_id = settings.get('cinemaTrailersPrerollID')

    # Print the current value of the setting
    if pre_roll_id.value:
        print(f"Current cinemaTrailersPrerollID setting:\n      {textwrap.fill(pre_roll_id.value, width=terminal_width)}")
    else:
        print("Current cinemaTrailersPrerollID setting:\n      -None Set-")

    # Set 'new_pre_roll_id' equal to 'destination_file;destination_file;destination_file'
    new_pre_roll_id = ";".join(destination_files)
    print(f"New cinemaTrailersPrerollID setting:\n      {textwrap.fill(new_pre_roll_id, width=terminal_width)}")

    # Fetch the 'cinemaTrailersPrerollID' setting
    cinema_trailers_preroll_id_setting = settings.get('cinemaTrailersPrerollID')

    # Set the new value for the 'cinemaTrailersPrerollID' setting
    cinema_trailers_preroll_id_setting.set(new_pre_roll_id)

    # Save the updated settings
    settings.save()


def get_eligible_sub_folders(config_data, log_file, today):
    eligible_sub_folders = []
    exclusive_sub_folders = []
    likely_sub_folders = []

    for folder_config in config_data["root"]["config"]:
        folder = folder_config["folder"]
        name = folder["name"]
        enabled = folder.get("enabled", False)
        exclusive = folder.get("exclusive", False)
        likely = folder.get("likely", False)
        start_date = folder.get("start_date")
        end_date = folder.get("end_date")

        # If the folder is not enabled, skip it
        if not enabled:
            continue

        if start_date is not None and end_date is not None:
            try:
                start_month, start_day = start_date.split("-")
                end_month, end_day = end_date.split("-")
                start = datetime.date(year=today.year, month=int(start_month), day=int(start_day))
                end = datetime.date(year=today.year, month=int(end_month), day=int(end_day))
            except ValueError:
                log_to_file(f"Invalid date format for folder {name}: start_date={start_date}, end_date={end_date}.", log_file)
                continue

            if start <= today <= end:
                if exclusive:
                    exclusive_sub_folders.append(name)
                elif likely:
                    likely_sub_folders.extend([name]*4)
                else:
                    eligible_sub_folders.append(name)
        else:
            # Handle the case where start_date or end_date is not specified
            if exclusive:
                exclusive_sub_folders.append(name)
            elif likely:
                likely_sub_folders.extend([name]*4)
            else:
                eligible_sub_folders.append(name)

    # If there are exclusive sub_folders, return only the exclusive ones
    if exclusive_sub_folders:
        return exclusive_sub_folders
    else:
        return eligible_sub_folders + likely_sub_folders


def main():
    # Parse configuration file and load state data
    config, config_data, likely_folders = load_yaml(config_file)
    root = load_state_data(config["state_file"])

    # Define variables from config dictionary
    plex_url = config["plex_url"]
    plex_token = config["plex_token"]
    source_folder = config["source_folder"]
    allowed_extensions = config["allowed_extensions"]
    destination_folder = config["destination_folder"]
    log_file = config["log_file"]

    add_new_files(root, source_folder, allowed_extensions)
    remove_missing_files(root, source_folder)

    state_data = update_and_load_state_data(config["state_file"], root)

    clear_destination_folder(destination_folder, allowed_extensions)
    eligible_sub_folders = get_eligible_sub_folders(config_data, log_file, today)
    #reset_all_files(root)
    check_and_reset_likely_folders(root, likely_folders)
    output_available_media(root, eligible_sub_folders, log_file)
    check_and_reset_eligible_folders(root, eligible_sub_folders)

    unused_files = filter_unused_files(root, eligible_sub_folders)

    if not unused_files:
        print(f"No files left, reset used file state.")
        reset_state_file(root, config["state_file"])
        unused_files = filter_unused_files(root, eligible_sub_folders)

    if len(unused_files) < 3:
        print(f"Less than 3 files left, reset used file state.")
        check_and_reset_eligible_folders(root, eligible_sub_folders)
        unused_files = filter_unused_files(root, eligible_sub_folders)

    destination_files = process_unused_files(root, source_folder, destination_folder, unused_files, log_file)

    with open(config["state_file"], 'w') as f:
        yaml.dump(root, f)

    update_plex_settings(plex_url, plex_token, destination_files)

if __name__ == "__main__":
    main()
