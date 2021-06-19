f"""The main script to be run.

This program scrapes the real estate objects information (text and photos) from
the https://www.sreality.cz/ server.

Initial search page:
    https://www.sreality.cz/hledani/prodej/byty/praha?bez-aukce=1
"""
import re
import os
import os.path
import sys
import csv
import time
import json
import glob
import shutil
import logging
from math import ceil
from datetime import datetime
from signal import signal, SIGINT

import requests
from PIL import Image

from scraping_utils import (fix_filename, remove_umlauts, setup_logging,
                            get_response, save_image, get_ip, USE_TOR,
                            FATAL_ERROR_STR)
from tor_proxy import TorProxy

HELP = """Usage:
    s_reality_scraper.py build [options] | update | check | cleanup | vacuum

Commands:
    build - performs all the real estates scraping;

    check - checks accessibility of the real estate items;
        if an item is not accessible, sets the 'removed' mark in database;

    cleanup - removes all the real estate items with the 'removed' mark
         from the CSV database;

    vacuum - deletes all the real estate photos having no links to actual items
        in the CSV database.

Options for build command:
    --restart - resets scraping progress: creates backup and deletes database;

    --use_cache - does not download the real estates images scraped earlier;

    --update - starts scraping process from the first page but doesn't delete
        the database;

    --today - performs the real estates scraping for today.

Use CTRL-C to interrupt the script execution.
"""

# User must input this string in order to execute image folder cleaning
VACUUM_CONFIRM = 'ok'

BASE_URL = 'https://www.sreality.cz/'

ITEM_BASE_URL = BASE_URL + 'detail/prodej/byt/'

JSON_URL = BASE_URL + 'api/cs/v2/estates'

# This is the maximum amount of items per page in API calls
ITEMS_PER_PAGE = 60

# Filename containing scraping progress
LAST_PROCESSED_PAGE_FILENAME = 'last_processed_page.txt'

# Item name example: 'Prodej bytu 2+1 83 m²'
#                    'Prodej bytu 6 pokojů a více 276 m² (Mezonet)'
# Is used for building item link
ESTATE_TYPE_RE = re.compile(r'^Prodej bytu (.+)\s\d+\sm²')

REMOVED_MARK = 'removed'

CSV_DELIMITER = ','

CSV_FILENAME = 'estates.csv'

BACKUP_FILENAME = CSV_FILENAME + '.bak'

IMAGE_DIR = 'img'

# Trimming values for removing "sreality.cz" watermark
CROP_TOP = 43
CROP_LEFT = 187

JSON_DIR = 'json'

COLUMNS = [
    'Ссылка',
    'Заголовок',
    'Улица',
    'Район',
    'Часть района',
    'Цена',
    'Описание',

    # Table section begin
    'Celková cena',
    'ID zakázky',
    'Aktualizace',
    'Stavba',
    'Stav objektu',
    'Vlastnictví',
    'Podlaží',
    'Užitná plocha',
    'Balkón',
    'Sklep',
    'Parkování',
    'Garáž',
    'Energetická náročnost budovy',
    'Bezbariérový',
    'Vybavení',
    'Výtah',
    'Plocha podlahová',
    'Poznámka k ceně',
    'Umístění objektu',
    'Elektřina',
    'Doprava',
    'Rok rekonstrukce',
    'Voda',
    'Topení',
    'Odpad',
    'Telekomunikace',
    'Terasa',
    'Cena',
    'Plyn',
    'Rok kolaudace',
    'Komunikace',
    'Ukazatel energetické náročnosti budovy',
    'Datum ukončení výstavby',
    'Datum zahájení prodeje',
    'Typ bytu',
    'Stav',
    'Průkaz energetické náročnosti budovy',
    'Datum nastěhování',
    'ID',
    'Lodžie',
    'Datum prohlídky',
    'Datum prohlídky do',
    'Náklady na bydlení',
    'Anuita',
    'Převod do OV',
    'Plocha zahrady',
    'Výška stropu',
    'Plocha zastavěná',
    'Počet bytů',
    'Provize',
    'Půdní vestavba',
    'Zlevněno',
    'Původní cena',
    'Bazén',
    'Minimální kupní cena',
    # Table section end

    'Геопозиция широта',
    'Геопозиция долгота',
    'Контакт Имя',
    'Контакт телефон 1',
    'Контакт телефон 2',
    'Добавлено',
    'Удалено',
]

# Saves last processed page
def save_last_page(page: int) -> bool:
    try:
        with open(LAST_PROCESSED_PAGE_FILENAME, 'w') as f:
            f.write(str(page))
    except OSError:
        logging.warning('Can\'t save last processed page to a file.')
        return False
    return True

# Loads previously saved last processed page
def load_last_page() -> int:
    page = 0
    if os.path.exists(LAST_PROCESSED_PAGE_FILENAME):
        try:
            with open(LAST_PROCESSED_PAGE_FILENAME, 'r') as f:
                page = int(f.read())
        except OSError:
            logging.warning('Can\'t load last processed page from file.')
        except ValueError:
            logging.warning(f'File {LAST_PROCESSED_PAGE_FILENAME} '
                            'is currupted.')
    return page

# Returns UNIX timestamp
def get_tms():
    return int(time.time() * 1000)

# Getting all the estates for a category via API GET request as JSON dictionary
# If today parameter is set to True, then returns only new items
def get_category_json(page: int=1, today: bool=False) -> dict:
    params = {
        'category_main_cb': 1,
        'category_type_cb': 1,
        'locality_region_id': 10,
        'no_auction': 1,
        'page': page, # Numeration starts from 1
        'per_page': ITEMS_PER_PAGE,
        'sort': 0,
        'tms': get_tms(),
    }
    if today:
        params['estate_age'] = 2
    r = get_response(JSON_URL, params=params)

    if not r:
        return None

    try:
        json = r.json()
    except Exception as e:
        logging.error('Failure while getting category JSON: ' + str(e))
        return None

    return json

# Getting item JSON dictionary for specified item hash_id via API GET request
def get_item_json(hash_id: int) -> dict:
    params = {
        'tms': get_tms(),
    }
    r = get_response(f'{JSON_URL}/{hash_id}', params=params)

    if not r:
        return None

    try:
        json = r.json()
    except Exception as e:
        logging.error('Failure while getting item JSON: ' + str(e))
        return None

    return json

# Extracting item address parts from item data JSON dictionary
def get_item_address(item_json: dict) -> dict:
    # Full address example: 'Karla Engliše, Praha 5 - Smíchov'
    addr_str = item_json['locality']['value']
    address = {
        'Улица': '',
        'Район': '',
        'Часть района': '',
    }

    if ',' in addr_str:
        address['Улица'] = addr_str.split(',')[0]
    if '-' in addr_str:
        address['Часть района'] = addr_str.split('-')[1]
    address['Район'] = addr_str[len(address['Улица']):].split('-')[0]
    address['Район'] = address['Район'].replace(',', ' ')

    for addr_key, addr_value in address.items():
        address[addr_key] = addr_value.strip()

    return address

# Building item link from item data JSON dictionary and item hash_id
def get_item_link(item_json: dict, hash_id: int) -> str:
    address = get_item_address(item_json)
    # CEO keywords examples:
    #   'praha-liben-nad-rokoskou'
    #   'praha-karlin-'
    #   'praha-praha-4-'
    if address['Часть района'] or address['Улица']:
        link_ceo = f'praha-{address["Часть района"]}-{address["Улица"]}'
    else:
        link_ceo = f'praha-{address["Район"]}-'

    # Examples: '1+kk', '2+1', 'atypické', '6 pokojů a více'
    estate_type = re.findall(ESTATE_TYPE_RE, item_json['name']['value'])[0]
    if estate_type == '6 pokojů a více':
        estate_type = '6-a-vice'

    item_link = '/'.join([estate_type, link_ceo, str(hash_id)])
    item_link = (remove_umlauts(item_link)
                 .lower().replace(' ', '-').replace('.', '-'))
    item_link = ITEM_BASE_URL + item_link

    return item_link

# Returns a dict for a given item data JSON and item hash_id with all nessesary
# fields for immediate insertion to the CVS database
def get_item(item_json: dict, hash_id: int) -> dict:
    item = {}
    for key in COLUMNS:
        item[key] = ''

    try:
        for field in item_json['items']:
            value = None

            if field['type'] in ('string', 'edited', 'count',
                                 'energy_efficiency_rating', 'date'):
                value = field['value']

            elif field['type'] == 'price_czk':
                value = ' '.join([str(field['value']), field['currency'],
                                  field['unit']])
                value = ', '.join([str(value), ', '.join(field['notes'])])
                if field.get('negotiation') != None:
                    value += ' (k jednání)'

            elif field['type'] == 'area':
                value = ' '.join([str(field['value']), field['unit']])

            elif field['type'] == 'boolean':
                value = str(field['value']).lower()

            elif field['type'] == 'set':
                value = ', '.join(
                    [str(element['value']) for element in field['value']])

            elif field['type'] == 'integer':
                value = str(field['value'])

            elif field['type'] == 'price_info':
                value = field['value']
                if field.get('negotiation') != None:
                    value += ' (k jednání)'

            elif field['type'] == 'energy_performance':
                value = ' '.join([str(field['value']), field['unit'],
                                  field['unit2']])

            elif field['type'] == 'energy_performance_attachment':
                value = field['url']

            elif field['type'] == 'length':
                value = ' '.join([str(field['value']), field['unit']])

            elif field['type'] in ('price', 'price_czk_old'):
                value = ' '.join([str(field['value']), field['currency']])
                if field.get('unit') != None:
                    value += ' ' + field['unit']

            if value == None:
                logging.warning(f'Unknown data type "{field["type"]}". ' +
                                f'Item hash_id: {hash_id}.')
            else:
                item[field['name']] = value

        item['Ссылка'] = get_item_link(item_json, hash_id)
        item['Заголовок'] = item_json['name']['value']

        # 'Улица', 'Район', 'Часть района'
        for addr_key, addr_value in get_item_address(item_json).items():
            item[addr_key] = addr_value

        if item_json['price_czk']:
            item['Цена'] = item_json['price_czk']['value'] + ' Kč'
        else:
            item['Цена'] = 'Info o ceně u RK'

        item['Описание'] = item_json['text']['value'].replace('\r\n', '<br />')

        item['Геопозиция широта'] = str(item_json['map']['lat'])
        item['Геопозиция долгота'] = str(item_json['map']['lon'])

        phones = []
        if item_json['_embedded'].get('seller') != None:
            item['Контакт Имя'] = item_json['_embedded']['seller']['user_name']
            phones = item_json['_embedded']['seller']['phones']

        if item_json.get('contact') != None:
            item['Контакт Имя'] = item_json['contact']['name']
            phones = item_json['contact']['phones']

        if len(phones) > 0:
            item['Контакт телефон 1'] = ('+' + phones[0]['code']
                                         + phones[0]['number'])
        if len(phones) > 1:
            item['Контакт телефон 2'] = ('+' + phones[1]['code']
                                         + phones[1]['number'])
        else:
            item['Контакт телефон 2'] = ''

        item['Добавлено'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        item['Удалено'] = ''
    except Exception as e:
        logging.error(f'JSON parsing failed. Item hash_id: {hash_id}.'
                      + str(e))
        return None

    return item

# Saving prepared item data to a CSV file
# If first_item is set to True, then recreates the CSV database
# If first_item is set to False, then just appends a new row
def save_item(item: dict, filename: str, first_item=False) -> bool:
    try:
        with open(filename, 'w' if first_item else 'a',
                  newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=CSV_DELIMITER)
            if first_item:
                writer.writerow(COLUMNS)
            writer.writerow([item[key] for key in COLUMNS])
    except OSError:
        logging.error(f'Can\'t write to CSV file {filename}.')
        return False
    except Exception as e:
        logging.error('Scraped data saving fault. ' + str(e))
        return False

    return True

# Saves prepared items list to a CSV file
def save_items(items: list, filename: str) -> bool:
    for index, item in enumerate(items):
        if not save_item(item, filename, first_item = (index == 0)):
            return False

    return True

# Loads real estate items list from a CVS file
def load_items(filename: str) -> list:
    if not os.path.exists(filename):
        return []

    items = []

    try:
        with open(filename, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=CSV_DELIMITER)
            next(reader)
            for row in reader:
                item = {}
                for index, key in enumerate(COLUMNS):
                    item[key] = row[index]
                items.append(item)
    except OSError:
        logging.error(f'Can\'t read CSV file {filename}.')
    except Exception as e:
        logging.error('CVS file reading fault. ' + str(e))

    return items

# Returns total page count for the real estate item search via site API
def get_page_count(today: bool=False) -> int:
    search_result = get_category_json(today=today)
    if search_result:
        return ceil(search_result['result_size'] / ITEMS_PER_PAGE)
    else:
        return None

# Returns the hash_id list for all the real estate items from the site
def scrape_hash_ids() -> list:
    hash_ids = []

    page_count = get_page_count()
    if page_count == None:
        return None

    logging.info(f'Total page count to iterate: {page_count}')
    for page in range(1, page_count + 1):
        logging.info(f'Iterating through page {page} of {page_count}.')
        estates = get_category_json(page)['_embedded']['estates']
        if estates == None:
            return None

        hash_ids.extend([estate['hash_id'] for estate in estates
                         if estate['hash_id'] not in hash_ids])

    return hash_ids

# Checks whether a real estate item with hash_id is available on the site
# The hash_ids list contains all the available item identifiers from the site
def check_item(hash_id: int, hash_ids: list) -> bool:
    if hash_id in hash_ids:
        return True

    # Additional check just to be sure
    if get_item_json(hash_id) == None:
        return False

    return True

# Checks site availability for all the real estate items in the CSV database
def check_items() -> bool:
    logging.info('Rertieving hash_ids for all actual items.')
    hash_ids = scrape_hash_ids()
    if hash_ids == None:
        return False

    logging.info('Iterating through all scraped items.')
    marked_item_count = 0
    items = load_items(CSV_FILENAME)
    for index, item in enumerate(items):
        hash_id = hash_id_from_link(item['Ссылка'])
        if not check_item(hash_id, hash_ids):
            logging.info(f'Setting "{REMOVED_MARK}" mark, '
                         + f'item hash_id: {hash_id}.')
            items[index]['Удалено'] = REMOVED_MARK
            marked_item_count += 1

    if not save_items(items, CSV_FILENAME):
        return False

    logging.info(f'File {CSV_FILENAME} was successfully updated. '
                 f'Outdated item count: {marked_item_count}.')

    return True

# Deletes marked as 'removed' rows in the CSV database
def clean_csv() -> bool:
    deleted_item_count = 0
    items = load_items(CSV_FILENAME)
    for i in range(len(items) - 1, -1, -1):
        if items[i]['Удалено'] == REMOVED_MARK:
            hash_id = hash_id_from_link(items[i]['Ссылка'])
            logging.info(f'Removing item from {CSV_FILENAME}, '
                         + f'hash_id: {hash_id}.')
            del items[i]
            deleted_item_count += 1

    if not save_items(items, CSV_FILENAME):
        return False

    logging.info(f'File {CSV_FILENAME} was successfully updated. '
                 f'Items removed: {deleted_item_count}.')

    return True

# Removes all the images and json files having no actual link to a real estate
# item in the CSV database
def clean_files():
    items = load_items(CSV_FILENAME)
    hash_ids = get_hash_ids(items)

    logging.info('Cleaning JSON files.')
    json_filelist = glob.glob(os.path.join(JSON_DIR, '*.json'))
    deleted_json_files = 0
    for filename in json_filelist:
        if hash_id_from_json_name(filename) not in hash_ids:
            logging.info(f'Deleting JSON file {filename}')
            try:
                os.remove(filename)
            except OSError:
                logging.error(f'File {filename} deleting failure.')
            else:
                deleted_json_files += 1

    logging.info(f'Total JSON files deleted: {deleted_json_files}.')

    logging.info('Cleaning image folder.')
    valid_dirlist = get_image_folders(items)
    images_dirlist = [os.path.join(IMAGE_DIR, image_folder)
                      for image_folder in os.listdir(IMAGE_DIR)]
    deleted_image_folders = 0
    # Deleting images with 'broken links' as well as duplicates
    for image_folder in images_dirlist:
        if image_folder not in valid_dirlist:
            logging.info(f'Deleting image folder {image_folder}')
            try:
                shutil.rmtree(image_folder)
            except OSError:
                logging.error(f'Folder {image_folder} deleting failure.')
            else:
                deleted_image_folders += 1

    logging.info(f'Total image folders deleted: {deleted_image_folders}.')

# Trims the given image in order to remove "sreality.cz" watermark
def crop_image(filename: str) -> bool:
    image = Image.open(filename)
    image_width, image_height = image.size

    crop_left_area = CROP_LEFT * image_height
    crop_top_area = CROP_TOP * image_width
    if crop_left_area < crop_top_area:
        image = image.crop((CROP_LEFT, 0, image_width, image_height))
    else:
        image = image.crop((0, CROP_TOP, image_width, image_height))

    try:
        image.save(filename)
    except OSError:
        logging.error('Can\'t save cropped image to the disk.')
        return False

    return True

# Retrieves from the site and saves all the real estates photos for a given
# item data JSON dict and hash_id
# If use_cache is set to True, then doesn't download the image file from the
# site in the case it has been already downloaded and saved earlier
def save_item_images(item_json: dict, hash_id: int,
                     use_cache: bool=False) -> bool:
    image_folder_path = get_image_folder(get_item_link(item_json, hash_id))
    if not os.path.exists(image_folder_path):
        try:
            os.mkdir(image_folder_path)
        except OSError:
            logging.error(f'Can\'t create images folder {image_folder_path}')
            return False

    result = True
    for img_ind, image in enumerate(item_json['_embedded']['images']):
        # Old version: for preview (without watermark)
        # href = image['_links']['view']['href']

        # New version: for full-sized image (with watermark)
        href = image['_links']['self']['href']

        logging.info(f'Saving image from {href}')
        img_ind_str = str(img_ind)
        img_ind_str = '0' * (3 - len(img_ind_str)) + img_ind_str
        image_filename = f'{hash_id}_{img_ind_str}.jpg'
        image_full_path = os.path.join(image_folder_path, image_filename)

        # Checking if the image has already downloaded
        if use_cache and os.path.exists(image_full_path):
            logging.info(f'Image cache found: {image_filename}')
        else:
            if save_image(href, image_full_path):
                if not crop_image(image_full_path):
                    result = False
            else:
                result = False

    return result

# Parse real estate item hash_id from json filename
def hash_id_from_json_name(json_filename: str) -> str:
    return int(os.path.basename(json_filename).split('.')[0])

# Parse real estate item hash_id from the particular image folder name
# (Currently not in use)
def hash_id_from_image_folder(image_folder: str) -> str:
    return int(image_folder.split('_')[-1])

# Parse real estate item hash_id from the item URL link
def hash_id_from_link(item_link: str) -> int:
    return int(item_link.split('/')[-1])

# Generates item hash_id list from a list of prepared item dictionaries
def get_hash_ids(items: list) -> list:
    return [hash_id_from_link(item['Ссылка']) for item in items]

# Converts a real estate item URL link to a corresponding image folder name
def get_image_folder(item_link: str) -> str:
    return os.path.join(IMAGE_DIR, item_link[len(BASE_URL):].replace('/', '_'))

# Returns complete image folders list from a list of prepared item dictionaries
def get_image_folders(items: list) -> list:
    return [get_image_folder(item_link=item['Ссылка']) for item in items]

# For testing and debugging: scrapes all the JSON from API requests for each
# real estate item in the search results
def _scrape_raw_json():
    tor = TorProxy()
    logging.info('Starting TOR.')
    tor.restart(wait=True)
    logging.info('New IP is: ' + get_ip())

    page_count = get_page_count()
    logging.info(f'Total page count: {page_count}')
    for page in range(1, page_count + 1):
        if page % 10 == 0:
            logging.info('Re-starting TOR.')
            tor.restart(wait=True)
            logging.info('New IP is: ' + get_ip())

        logging.info(f'Scraping page {page} of {page_count}.')
        estates = get_category_json(page)['_embedded']['estates']
        for estate in estates:
            logging.info(f'{estate["name"]}\t{estate["hash_id"]}')
            item_data = get_item_json(estate['hash_id'])
            try:
                filename = os.path.join(JSON_DIR, f'{estate["hash_id"]}.json')
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(item_data, f, ensure_ascii=False, indent=4)
            except OSError:
                logging.error(f"Can't write to a file {filename}.")

    tor.terminate()

# For testing and debugging: creates the CSV database from previously scraped
# JSON data
def _json_to_csv():
    filelist = glob.glob(os.path.join(JSON_DIR, '*.json'))

    for index, filename in enumerate(filelist):
        with open(filename, encoding='utf-8') as f:
            print(f'Processing file {filename}.')
            json_data = json.load(f)
            item = get_item(json_data, hash_id_from_json_name(filename))
            save_item(item, CSV_FILENAME, first_item = (index == 0))

# Saves "raw" JSON item data with given item hash_id
# Filename is generated automatically
def save_item_json(item_json: dict, hash_id: int) -> bool:
    try:
        filename = os.path.join(JSON_DIR, f'{hash_id}.json')
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(item_json, f, ensure_ascii=False, indent=4)
    except OSError:
        logging.error(f"Can't write to a file {filename}.")
        return False

    return True

# Restarts TOR proxy in order to get new IP
def restart_tor(tor: TorProxy) -> bool:
    logging.info('Re-starting TOR.')

    try:
        tor.restart(wait=True)
    except Exception as e:
        logging.error(f'Can\'t restart TOR. ' + str(e))
        return False

    new_ip = get_ip()
    if new_ip == None:
        logging.error("Can't get new IP.")
        return False
    logging.info(f'New IP is: {new_ip}')

    return True

# Saves all the real estate item components: JSON, images and a record in CSV
def save_item_comprehensive(hash_id: int, first_item: bool,
                            use_cache: bool=False) -> bool:
    item_json = get_item_json(hash_id)
    if item_json == None:
        return False

    if not save_item_json(item_json, hash_id):
        return False

    if not save_item_images(item_json, hash_id, use_cache=use_cache):
        return False

    item = get_item(item_json, hash_id)
    if item == None:
        return False

    if not save_item(item, CSV_FILENAME, first_item=first_item):
        return False

    return True

# Main scraping function: scrapes all the real estates items from the site and
# saves the retrieved data as the CVS database, JSON files for debugging and
# photo images
def scrape_items(today: bool=False, use_cache: bool=False,
                 from_page: int=None) -> bool:
    if USE_TOR:
        tor = TorProxy()
        if not restart_tor(tor):
            return False

    added_item_count = 0
    hash_ids = get_hash_ids(load_items(CSV_FILENAME))
    logging.info(f'Number of items already fetched: {len(hash_ids)}.')

    page_count = get_page_count(today)
    if page_count == None:
        return False
    logging.info(f'Total page count: {page_count}.')

    first_page = from_page if (from_page != None) else (load_last_page() + 1)
    if first_page == 1:
        logging.info('Starting scraping from the beginning.')
    else:
        logging.info(f'Resuming scraping from page {first_page}.')

    for page in range(first_page, page_count + 1):
        if USE_TOR and page != first_page:
            if not restart_tor(tor):
                tor.terminate()
                return False

        logging.info(f'Scraping page {page} of {page_count}.')
        estates = get_category_json(page, today)['_embedded']['estates']
        if estates == None:
            return False
        for estate in estates:
            hash_id = estate['hash_id']
            if hash_id in hash_ids:
                logging.info(f'Item "{estate["name"]}" '
                             + f'hash_id {hash_id}, already fetched.')
                continue
            else:
                logging.info(f'Getting "{estate["name"]}" hash_id {hash_id}.')

            first_item = (page == 1 and estate == estates[0])
            if save_item_comprehensive(hash_id, first_item=first_item,
                                       use_cache=use_cache):
                added_item_count += 1
                hash_ids.append(hash_id)
            else:
                logging.warning(f'Item "{estate["name"]}" '
                                + f'hash_id {hash_id}, has not saved.')

        save_last_page(page)

    if USE_TOR:
        tor.terminate()

    logging.info(f'Total added item count: {added_item_count}.')
    return True

# System handler for correct CTRL-C processing
def sigint_handler(signal_received, frame):
    logging.info('SIGINT or CTRL-C detected. Program execution halted.')
    sys.exit(0)

# Script entry point
def main():
    setup_logging()
    signal(SIGINT, sigint_handler)

    if 'build' in sys.argv:
        if '--restart' in sys.argv:
            # Clearing scraping progress
            if os.path.exists(LAST_PROCESSED_PAGE_FILENAME):
                try:
                    os.remove(LAST_PROCESSED_PAGE_FILENAME)
                except OSError:
                    logging.error(f'File {LAST_PROCESSED_PAGE_FILENAME} '
                                  'deleting failure.')
                    return

            # Creating CSV file backup
            if os.path.exists(CSV_FILENAME):
                logging.info(f'Creating {CSV_FILENAME} backup.')
                if os.path.exists(BACKUP_FILENAME):
                    try:
                        os.remove(BACKUP_FILENAME)
                    except OSError:
                        logging.error(f'File {BACKUP_FILENAME} '
                                      'deleting failure.')
                        return
                try:
                    os.rename(CSV_FILENAME, BACKUP_FILENAME)
                except OSError:
                    logging.error(f'Creating {CSV_FILENAME} backup failure.')
                    return

        logging.info('Scraping process initialization.')

        if not os.path.exists(IMAGE_DIR):
            try:
                os.mkdir(IMAGE_DIR)
            except OSError:
                logging.error('Can\'t create directory for images.\n'
                              + FATAL_ERROR_STR)
                return

        if not os.path.exists(JSON_DIR):
            try:
                os.mkdir(JSON_DIR)
            except OSError:
                logging.error('Can\'t create directory for JSON data.\n'
                              + FATAL_ERROR_STR)
                return

        if '--update' in sys.argv:
            logging.info('Updating (if already exists) the database.')
            from_page = 1
        else:
            from_page = None

        if '--today' in sys.argv:
            logging.info('Scraping items submitted today.')
            today = True
        else:
            today = False

        if '--use_cache' in sys.argv:
            logging.info('Using image cache if possible.')
            use_cache = True
        else:
            use_cache = False

################################# FOR DEBUG ###################################
        if not scrape_items(today=today, use_cache=use_cache,
                            from_page=from_page):
            logging.error(FATAL_ERROR_STR)
            return
############################## FOR DEPLOYMENT #################################
        # try:
        #     if not scrape_items(today=today, use_cache=use_cache,
        #                         from_page=from_page):
        #         logging.error(FATAL_ERROR_STR)
        #         return
        # except Exception as e:
        #     logging.error('Error while scraping. ' + str(e) + '\n'
        #                   + FATAL_ERROR_STR)
        #     return
###############################################################################

        logging.info('Scraping process complete.')

    elif 'check' in sys.argv:
        logging.info('Checking the real estate items accessibility.')
        if not check_items():
            logging.error(FATAL_ERROR_STR)
            return

    elif 'cleanup' in sys.argv:
        logging.info('Removing all the items with the "removed" mark.')
        if not clean_csv():
            logging.error(FATAL_ERROR_STR)
            return

    elif 'vacuum' in sys.argv:
        print('Deleting outdated files. '
              'WARNING! This operation may remove important data!')
        if input('Please type "ok" to proceed:') == VACUUM_CONFIRM:
            logging.info('Deleting all the outdated files.')
            clean_files()
        else:
            print('Operation cancelled.')

    else:
        print(HELP)

if __name__ == '__main__':
    main()
