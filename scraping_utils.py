import re
import os
import os.path
import time
import logging
import logging.handlers
import unicodedata

import requests

from tor_proxy import TOR_SOCKS_PROXIES

# Directory name for saving log files
LOG_FOLDER = 'logs'

# Log file name
LOG_NAME = 'scraper.log'

# Full path to the log file
LOG_PATH = os.path.join(LOG_FOLDER, LOG_NAME)

# Maximum log file size
LOG_SIZE = 2 * 1024 * 1024

# Log files count for cyclic rotation
LOG_BACKUPS = 2

# Timeout for web server response (seconds)
TIMEOUT = 5

# Maximum retries count for executing request if an error occurred
MAX_RETRIES = 3

# The delay after executing an HTTP request (seconds)
# SLEEP_TIME = 1
SLEEP_TIME = 0.5

# HTTP headers for making the scraper more "human-like"
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 6.1; rv:88.0)'
                   ' Gecko/20100101 Firefox/88.0'),
    'Accept': '*/*',
}

USE_TOR = False

# PROXIES = None
# PROXIES = TOR_SOCKS_PROXIES
PROXIES = TOR_SOCKS_PROXIES if USE_TOR else None

# Common text for displaying while script is shutting down
FATAL_ERROR_STR = 'Fatal error. Shutting down.'

# Characters not allowed in filenames
FORBIDDEN_CHAR_RE = r'[<>:"\/\\\|\?\*]'

ICANHAZIP_URL = 'http://icanhazip.com'

def fix_filename(filename: str, subst_char: str='_') -> str:
    return re.sub(FORBIDDEN_CHAR_RE, subst_char, filename)

def remove_umlauts(text: str) -> str:
    return (unicodedata.normalize('NFKD', text)
            .encode('ASCII', 'ignore')
            .decode('utf-8'))

# Setting up configuration for logging
def setup_logging():
    logFormatter = logging.Formatter(
        fmt='[%(asctime)s] %(filename)s:%(lineno)d %(levelname)s - %(message)s',
        datefmt='%d.%m.%Y %H:%M:%S')
    rootLogger = logging.getLogger()
    rootLogger.setLevel(logging.INFO)

    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)

    if not os.path.exists(LOG_FOLDER):
        try:
            os.mkdir(LOG_FOLDER)
        except OSError:
            logging.warning('Не удалось создать папку для журнала ошибок.')

    if os.path.exists(LOG_FOLDER):
        fileHandler = logging.handlers.RotatingFileHandler(
            LOG_PATH, mode='a', encoding='utf-8', maxBytes=LOG_SIZE,
            backupCount=LOG_BACKUPS)
        fileHandler.setFormatter(logFormatter)
        rootLogger.addHandler(fileHandler)

# Retrieving HTTP GET response implying TIMEOUT and HEADERS
def get_response(url: str, params: dict=None) -> requests.Response:
    """Input and output parameters are the same as for requests.get() function.
    Also retries, timeouts, headers and error handling are ensured.
    """
    for attempt in range(0, MAX_RETRIES):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                             params=params, proxies=PROXIES)
        except requests.exceptions.RequestException:
            time.sleep(SLEEP_TIME)
        else:
            time.sleep(SLEEP_TIME)
            if r.status_code != requests.codes.ok:
                logging.error(f'Error {r.status_code} while accessing {url}.')
                return None
            return r

    logging.error(f'Error: can\'t execute HTTP request while accessing {url}.')
    return None

# Retrieve an image from URL and save it to a file
def save_image(url: str, filename: str) -> bool:
    r = get_response(url)

    try:
        with open(filename, 'wb') as f:
            f.write(r.content)
    except OSError:
        logging.error('Error: can\'t save an image to the disk.')
        return False
    except Exception as e:
        logging.error('Error while retrieving an image from URL: ' + str(e))
        return False

    return True

def get_ip() -> str:
    ip = get_response(ICANHAZIP_URL)
    if ip == None:
        return None

    return ip.text.strip()
