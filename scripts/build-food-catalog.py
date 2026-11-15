"""Build a compact CC0 catalogue from the public USDA SR Legacy JSON archive."""
import json
import sys
import zipfile
from pathlib import Path

with zipfile.ZipFile(sys.argv[1]) as archive:
    name = next(n for n in archive.namelist() if n.endswith('.json'))
    foods = json.loads(archive.read(name))['SRLegacyFoods']
mapping = {1008: 'calories', 1003: 'protein', 1004: 'fat', 1005: 'carbohydrates', 1079: 'fiber',
           2000: 'sugar', 1093: 'sodium', 1258: 'saturatedFat'}
catalog = []
for food in foods:
    nutrients = {mapping[n['nutrient']['id']]: n['amount'] for n in food.get('foodNutrients', [])
                 if n['nutrient']['id'] in mapping and 'amount' in n}
    if 'calories' in nutrients:
        catalog.append({'id': 'usda-sr-' + str(food['fdcId']), 'name': food['description'], 'nutrients': nutrients,
                        'source': 'USDA FoodData Central, SR Legacy April 2018, FDC ' + str(food['fdcId'])})
Path(sys.argv[2]).write_text(json.dumps(catalog, separators=(',', ':')))
print(f'Built {len(catalog)} public-domain USDA food records.')
