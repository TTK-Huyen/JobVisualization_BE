#!/usr/bin/env python3
import os
import json
# ensure we point to our test keywords file before importing run_etl_pipeline
os.environ['KEYWORDS_DAILY_PATH'] = 'input/test_keywords_daily.json'
# small helper: import select_daily_keywords and print the selection
from Db.run_etl_pipeline import select_daily_keywords
sel = select_daily_keywords()
print(json.dumps(sel, ensure_ascii=False, indent=2))
