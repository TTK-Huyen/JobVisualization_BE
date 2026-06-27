from pathlib import Path
import sys, json
root = Path('.').resolve()
script_dir = root / 'pipeline' / 'crawl' / '1_crawl_data' / 'crawl_data' / 'crawl-careerviet-jobs' / 'scripts'
sys.path.insert(0, str(script_dir))
try:
    from scrape_careerviet import build_session, parse_search_page
    s = build_session()
    url = 'https://careerviet.vn/viec-lam/ai-kc1-vi.html'
    jobs = parse_search_page(s, url)
    print('Found jobs:', len(jobs))
    if jobs:
        print(json.dumps(jobs[0], ensure_ascii=False, indent=2))
except Exception as e:
    import traceback
    traceback.print_exc()
