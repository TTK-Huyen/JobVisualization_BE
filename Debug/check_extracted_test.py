import json

# Check extracted test file
with open('Db/data/crawl_20260506_114403/clean/extracted_test.json', encoding='utf-8') as f:
    data = json.load(f)

print(f"Extracted jobs: {len(data)}")
if data:
    print(f"First job title: {data[0].get('title', 'N/A')}")
    print(f"First job source: {data[0].get('source_name', 'N/A')}")
