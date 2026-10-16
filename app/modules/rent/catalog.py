"""Reviewed mapping: RVD Data_Dic.pdf tables 1.1 and 1.3, monthly CSVs (2026-10-16)."""
PARSER_VERSION = 'rvd-monthly-v1'
SOURCE_PAGE = 'https://data.gov.hk/en-data/dataset/hk-rvd-tsinfo_rvd-property-market-statistics'
DICTIONARY_URL = 'https://www.rvd.gov.hk/datagovhk/Data_Dic.pdf'
TERMS_URL = 'https://data.gov.hk/en/terms-and-conditions'
SOURCES = {
    'rental_index': {'url': 'https://www.rvd.gov.hk/datagovhk/1.3M.csv',
                     'start': '1993-01', 'default': 'index_all',
                     'title': 'PRIVATE DOMESTIC - RENTAL INDICES BY CLASS ( TERRITORY-WIDE ) [MONTHLY]'},
    'average_rent': {'url': 'https://www.rvd.gov.hk/datagovhk/1.1M.csv',
                     'start': '1999-01', 'default': 'rent_A_hk',
                     'title': 'PRIVATE DOMESTIC - AVERAGE RENTS BY CLASS [MONTHLY]'},
}
CLASSES = {'A': '<40', 'B': '40-69.9', 'C': '70-99.9', 'D': '100-159.9',
           'E': '>=160', 'ABC': '<100', 'DE': '>=100', 'all': 'all'}
INDEX_COLUMNS = {'all': 'All Classes', 'A': 'Class A', 'B': 'Class B', 'C': 'Class C',
                 'D': 'Class D', 'E': 'Class E', 'ABC': 'Classes A, B & C', 'DE': 'Classes D & E'}
REGIONS = {'hk': 'Hong Kong', 'kowloon': 'Kowloon', 'nt': 'New Territories'}


def catalog(source_id: str) -> list[dict]:
    if source_id == 'rental_index':
        combinations = [(f'index_{code}', code, 'territory', column)
                        for code, column in INDEX_COLUMNS.items()]
    else:
        combinations = [(f'rent_{code}_{region}', code, region, f'Class {code} {name}')
                        for code in 'ABCDE' for region, name in REGIONS.items()]
    return [{
        'series_id': identity, 'metric': source_id, 'class_code': code,
        'region_code': region, 'source_column': column, 'area_band': CLASSES[code],
        'area_basis': 'saleable', 'unit': 'index' if source_id == 'rental_index' else 'hkd_per_m2',
        'base_period': '1999=100' if source_id == 'rental_index' else None,
        'frequency': 'monthly', 'methodology_version': PARSER_VERSION,
        # Average rent compositions vary: compare regions only within the same class.
        'comparison_group': 'rvd_index_1999' if source_id == 'rental_index' else f'rvd_rent_{code}',
    } for identity, code, region, column in combinations]


def notes(source_id: str) -> list[str]:
    common = ['private_domestic_only', 'saleable_area', 'provisional_and_small_sample',
              'not_property_valuation', 'government_attribution']
    return common + (['index_not_currency', 'index_base_1999'] if source_id == 'rental_index'
                     else ['average_composition_varies', 'rent_per_square_metre'])
