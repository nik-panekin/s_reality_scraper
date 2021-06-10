import os
import os.path
import sys
import time

import requests
import xlsxwriter
from PIL import Image

# Timeout for web server response (seconds)
TIMEOUT = 5

# Maximum retries count for executing request if an error occurred
MAX_RETRIES = 3

# The delay after executing an HTTP request (seconds)
SLEEP_TIME = 2

BASE_URL = 'https://www.sreality.cz'

JSON_URL = BASE_URL + '/api/cs/v2/estates'

# HTTP headers for making the scraper more "human-like"
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 6.1; rv:88.0)'
                   ' Gecko/20100101 Firefox/88.0'),
    'Accept': '*/*',
}

# Retrieving HTTP GET response implying TIMEOUT and HEADERS
def get_response(url: str, params: dict=None) -> requests.Response:
    """Input and output parameters are the same as for requests.get() function.
    Also retries, timeouts, headers and error handling are ensured.
    """
    for attempt in range(0, MAX_RETRIES):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                             params=params)
        except requests.exceptions.RequestException:
            time.sleep(SLEEP_TIME)
        else:
            time.sleep(SLEEP_TIME)
            if r.status_code != requests.codes.ok:
                print(f'Error {r.status_code} while accessing {url}.')
                return None
            return r

    print(f'Error: can\'t execute HTTP request while accessing {url}.')
    return None

# Retrieve an image from URL and save it to a file
def save_image(url: str, filename: str) -> bool:
    r = get_response(url)

    try:
        with open(filename, 'wb') as f:
            f.write(r.content)
    except OSError:
        print('Error: can\'t save an image to the disk.')
        return False
    except Exception as e:
        print('Error while retrieving an image from URL: ' + str(e))
        return False

    return True

def _resize_image(filename):
    img = Image.open(filename)
    width, height = img.size
    scale = width / 200
    img.resize((int(width / scale), int(height / scale))).save(filename)

# Getting all the estates for a category via API GET request as JSON dictionary
def get_category_json() -> dict:
    params = {
        'category_main_cb': 1,
        'category_type_cb': 1,
        'locality_region_id': 10,
        'no_auction': 1,
        'per_page': 60,
        # 'tms': 1623175307128,
    }
    r = get_response(JSON_URL, params=params)

    if not r:
        return False

    try:
        json = r.json()
    except Exception as e:
        print('Error while getting category JSON: ' + str(e))
        return False

    return json

def get_item_json(hash_id) -> dict:
    r = get_response(f'{JSON_URL}/{hash_id}')

    if not r:
        return False

    try:
        json = r.json()
    except Exception as e:
        print('Error while getting item JSON: ' + str(e))
        return False

    return json

workbook = xlsxwriter.Workbook('Estates.xlsx')
worksheet = workbook.add_worksheet()
title_fmt = workbook.add_format({'bold': True, 'underline': True, 'font_color': 'blue'})

estates = get_category_json()['_embedded']['estates']
for est_ind, estate in enumerate(estates):
    print(estate['name'], '\t', estate['hash_id'])
    worksheet.write_url(est_ind * 2, 0,
        BASE_URL + '/detail/prodej/byt/alpha/beta/' + str(estate['hash_id']),
        string=estate['name'], cell_format=title_fmt)

    images = get_item_json(estate['hash_id'])['_embedded']['images']
    for img_ind, image in enumerate(images):
        print(image['_links']['view']['href'])
        filename = f'img/img_{est_ind}_{img_ind}.jpeg'
        save_image(image['_links']['view']['href'], filename)
        _resize_image(filename)

        worksheet.write(est_ind * 2, 0, estate['name'])
        worksheet.set_row_pixels(est_ind * 2 + 1, 200)
        worksheet.set_column_pixels(img_ind, img_ind, 220)
        worksheet.insert_image(est_ind * 2 + 1, img_ind, filename)
    print()

workbook.close()
