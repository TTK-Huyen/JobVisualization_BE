import json

# Check raw jobs_combined
with open('Db/data/crawl_20260506_114403/raw/jobs_combined.json', encoding='utf-8') as f:
    raw_data = json.load(f)

# Check clean pending_llm
with open('Db/data/crawl_20260506_114403/clean/pending_llm.json', encoding='utf-8') as f:
    clean_data = json.load(f)

print("=" * 80)
print("RAW JOBS_COMBINED.JSON")
print("=" * 80)
print(f"Total jobs: {len(raw_data)}\n")
for i, job in enumerate(raw_data, 1):
    print(f"{i}. Title: {job.get('title', 'N/A')}")
    print(f"   Source: {job.get('source_name', 'N/A')}")
    print(f"   Job URL: {job.get('job_url', 'N/A')}")
    print(f"   Has requirements_text: {bool(job.get('requirements_text'))}")
    print(f"   Has description_html: {bool(job.get('description_html'))}")
    print()

print("\n" + "=" * 80)
print("CLEAN PENDING_LLM.JSON")
print("=" * 80)
print(f"Total jobs: {len(clean_data)}\n")
for i, job in enumerate(clean_data, 1):
    print(f"{i}. Title: {job.get('title', 'N/A')}")
    print(f"   Source: {job.get('source_name', 'N/A')}")
    print(f"   Job URL: {job.get('job_url', 'N/A')}")
    print(f"   Has requirements_text: {bool(job.get('requirements_text'))}")
    print()

print("\n" + "=" * 80)
print("ANALYSIS")
print("=" * 80)
print(f"Jobs lost in clean step: {len(raw_data) - len(clean_data)}")

# Get job URLs from raw
raw_urls = {job.get('job_url', ''): job for job in raw_data if job.get('job_url')}
clean_urls = {job.get('job_url', ''): job for job in clean_data if job.get('job_url')}

lost_urls = set(raw_urls.keys()) - set(clean_urls.keys())
print(f"Jobs that disappeared: {len(lost_urls)}")
if lost_urls:
    print("\nLost jobs:")
    for url in lost_urls:
        job = raw_urls[url]
        print(f"  - {job.get('title', 'N/A')} ({job.get('source_name', 'N/A')})")
        print(f"    URL: {url}")
        rt = job.get('requirements_text') or ''
        print(f"    requirements_text length: {len(rt)}")
