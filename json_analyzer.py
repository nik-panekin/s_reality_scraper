import glob
import json

from scraping_utils import remove_umlauts

TABLE_DATA_FILENAME = 'table_data.json'
ADDRESSES_FILENAME = 'addresses.txt'
NAMES_FILENAME = 'names.txt'

def create_table_data():
    filelist = glob.glob('json/*.json')
    table_data = {}

    for filename in filelist:
        with open(filename, encoding='utf-8') as f:
            print(f'Processing file {filename}.')
            json_data = json.load(f)
            for item in json_data['items']:
                key_name = remove_umlauts(
                    item['name']).lower().replace(' ', '_')
                if key_name not in table_data:
                    table_data[key_name] = item

    with open(TABLE_DATA_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(table_data, f, ensure_ascii=False, indent=4)

def get_unique_types():
    with open(TABLE_DATA_FILENAME, encoding='utf-8') as f:
        json_data = json.load(f)

    types = []
    for item in json_data.values():
        if item['type'] not in types:
            types.append(item['type'])
    return types

def get_all_names():
    with open(TABLE_DATA_FILENAME, encoding='utf-8') as f:
        json_data = json.load(f)

    return [item['name'] for item in json_data.values()]

def create_address_list():
    filelist = glob.glob('json/*.json')
    addresses = []

    for filename in filelist:
        with open(filename, encoding='utf-8') as f:
            print(f'Processing file {filename}.')
            json_data = json.load(f)
            address = json_data['locality']['value']
            addresses.append(f'{address}:\t\t{filename}\n')

    with open(ADDRESSES_FILENAME, 'w', encoding='utf-8') as f:
        f.writelines(addresses)

def create_names_list():
    filelist = glob.glob('json/*.json')
    names = []

    for filename in filelist:
        with open(filename, encoding='utf-8') as f:
            print(f'Processing file {filename}.')
            json_data = json.load(f)
            name = json_data['name']['value']
            names.append(f'{name}:\t\t{filename}\n')

    with open(NAMES_FILENAME, 'w', encoding='utf-8') as f:
        f.writelines(names)

# print('Unique types:')
# for unique_type in get_unique_types():
#     print('\t' + unique_type)

# print('All item names:')
# for item_name in get_all_names():
#     print(f"    '{item_name}',")
create_address_list()
create_names_list()
# 'price_czk'
# 'string'
# 'edited'
# 'area'
# 'count'
# 'energy_efficiency_rating'
# 'boolean'
# 'set'
# 'integer'
# 'price_info'
# 'energy_performance'
# 'date'
# 'energy_performance_attachment'
# 'length'
# 'price'
# 'price_czk_old'
