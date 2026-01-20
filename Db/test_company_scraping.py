import requests
from bs4 import BeautifulSoup
import json

# Test URLs từ test_5_jobs.json
test_urls = [
    "https://careerviet.vn/vi/nha-tuyen-dung/cong-ty-co-phan-canifa.35A66CA5.html",
    "https://careerviet.vn/vi/nha-tuyen-dung/yes4all-trading-services-company-limited.35A89D9E.html",
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
}

def extract_company_info(url):
    """Extract company info từ trang công ty"""
    print(f"\n{'='*80}")
    print(f"Analyzing: {url}")
    print('='*80)
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. Lấy tên công ty
        title = soup.find('title')
        h1 = soup.find('h1')
        print(f"\n[Title Tag]: {title.get_text(strip=True) if title else 'Not found'}")
        print(f"[H1 Tag]: {h1.get_text(strip=True) if h1 else 'Not found'}")
        
        # 2. Tìm các thẻ LI - thường chứa info
        print(f"\n[LI Elements - có thể chứa thông tin công ty]:")
        lis = soup.select('li')
        for i, li in enumerate(lis[:20]):
            text = li.get_text(' ', strip=True)
            if len(text) > 10:
                print(f"  {i}: {text[:150]}")
        
        # 3. Tìm các DL/DT/DD elements (definition list)
        print(f"\n[Definition Lists (DL/DT/DD)]:")
        dls = soup.select('dl')
        for i, dl in enumerate(dls[:3]):
            dts = dl.select('dt')
            dds = dl.select('dd')
            print(f"  Block {i}:")
            for dt, dd in zip(dts, dds):
                dt_text = dt.get_text(strip=True)
                dd_text = dd.get_text(' ', strip=True)[:100]
                print(f"    {dt_text}: {dd_text}")
        
        # 4. Tìm các section/div chứa "company", "info"
        print(f"\n[Divs/Sections với class chứa 'info', 'company', 'about']:")
        important_divs = soup.select('div[class*="info"], div[class*="company"], div[class*="about"], section[class*="info"]')
        for i, div in enumerate(important_divs[:5]):
            class_name = ' '.join(div.get('class', []))
            text = div.get_text(' ', strip=True)[:200]
            print(f"  {i} (class: {class_name}): {text}")
        
        # 5. Tìm table
        print(f"\n[Tables]:")
        tables = soup.select('table')
        for i, table in enumerate(tables[:2]):
            print(f"  Table {i}:")
            rows = table.select('tr')
            for row in rows[:5]:
                cols = row.select('td, th')
                row_text = ' | '.join([col.get_text(strip=True)[:50] for col in cols])
                print(f"    {row_text}")
        
        # 6. Tìm text chứa từ khóa
        print(f"\n[Text tìm từ khóa như 'website', 'quy mô', 'lĩnh vực', 'địa chỉ']:")
        full_text = soup.get_text()
        keywords = ['website', 'quy mô', 'lĩnh vực', 'địa chỉ', 'trụ sở', 'số điện thoại', 'email']
        for keyword in keywords:
            if keyword.lower() in full_text.lower():
                # Tìm dòng chứa keyword
                for line in full_text.split('\n'):
                    if keyword.lower() in line.lower():
                        cleaned = ' '.join(line.split())
                        if len(cleaned) > 10 and len(cleaned) < 200:
                            print(f"  '{keyword}': {cleaned[:150]}")
                            break
        
        print("\n" + "="*80)
        
    except Exception as e:
        print(f"ERROR: {e}")

# Run test
if __name__ == "__main__":
    for url in test_urls:
        extract_company_info(url)
    
    print("\n✓ Test hoàn tất. Gửi output này cho Copilot để phân tích HTML structure")
