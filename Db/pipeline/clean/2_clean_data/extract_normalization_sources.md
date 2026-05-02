# Normalization Standard v1.0

Purpose
-------
This document defines canonical values, authoritative references, Vietnam-specific adaptations, and fallback policies for STEP 2 normalization fields used by the pipeline. Each canonical value lists a clear source so it is defensible in a thesis defense.

Conventions
-----------
- Enum token style: lower_snake_case (examples: `full_time`, `part_time`, `unknown`).
- For numeric ranges use integers (min, max). When only a band is available, map to the nearest integers.
- Dates: ISO-8601 (`YYYY-MM-DDTHH:MM:SS` when time known, otherwise `YYYY-MM-DDT00:00:00`).
- Null vs enum-unknown: Free-text unknowns should be `null`. Enum fields must use the explicit token `unknown` when the source cannot be mapped.

Fields
------

1) work_type
   - Canonical values:
     - `full_time`, `part_time`, `internship`, `contract`, `temporary`, `freelance`, `other`, `unknown`
   - Original source:
     - LinkedIn Jobs filters (job type options seen in LinkedIn job-post UI)
     - Indeed job-type filters (part-time, full-time, contract, temporary, internship)
   - Reference (examples):
     - LinkedIn Jobs — job type selector (LinkedIn Jobs UI documentation / recruiter help)
     - Indeed — job type filters (Indeed employer/job-posting docs)
   - Adaptation for Vietnam:
     - Map local wording to canonical tokens (e.g., "Toàn thời gian" → `full_time`, "Bán thời gian" → `part_time`).
     - Prefer `full_time` as default when contract type is unspecified for permanent hires in Vietnam.
   - Fallback policy:
     - If an explicit type cannot be mapped, set `work_type: unknown`.

2) company_size
   - Canonical values (LinkedIn company-size buckets expressed as ranges):
     - `1-10` (micro)
     - `11-50` (small)
     - `51-200` (small-medium)
     - `201-500` (medium)
     - `501-1000` (large)
     - `1001-5000` (enterprise)
     - `5001-10000`
     - `10001+`
     - `unknown`
   - Original source:
     - LinkedIn Company Size taxonomy (company size buckets used in LinkedIn filters and company pages)
   - Reference (examples):
     - LinkedIn company size filter / company profile fields (LinkedIn Help and Recruiter UI)
   - Adaptation for Vietnam:
     - Many Vietnamese SMEs self-report ranges; map numeric `company_size_min`/`company_size_max` where available and then bucket to the canonical range above.
     - If only text such as "hundreds" or ">500" is present, parse to nearest integer then bucket.
   - Fallback policy:
     - If no size info or parsing fails, set `company_size: unknown` and preserve any raw text in `raw.company_size_raw`.

3) currency
   - Canonical values:
     - ISO 4217 three-letter currency codes, e.g., `VND`, `USD`, `EUR`, `JPY`, `KRW`, `SGD`, `GBP`, `AUD`, ...
   - Original source:
     - ISO 4217 Currency Codes (international standard)
   - Reference:
     - ISO 4217 — https://www.iso.org/iso-4217-currency-codes.html
   - Adaptation for Vietnam:
     - Primary currency for Vietnam postings should be `VND` (Vietnamese đồng). If posting shows salaries in USD or other currencies, keep the ISO code as-is and record the pay_period appropriately.
   - Fallback policy:
     - If currency cannot be mapped to an ISO code, set `currency: unknown` and keep raw string in `raw.salary_raw`.

4) pay_period
   - Canonical values:
     - `hourly`, `daily`, `weekly`, `monthly`, `yearly`, `negotiable`, `unknown`
   - Original source:
     - Indeed salary period semantics and LinkedIn salary/posting fields
   - Adaptation for Vietnam:
     - Vietnamese job postings commonly use `monthly` (e.g., "VND / month") or `yearly`. Convert local terms such as "tháng" to `monthly`, "năm" to `yearly`.
   - Fallback policy:
     - If unit cannot be disambiguated, set `pay_period: unknown` and preserve raw in `raw.salary_raw`.

5) location
   - Canonical representation:
     - Hierarchical: `{ country: <ISO-3166-1 alpha-2>, administrative_area: <province/state>, city: <city/town>, raw: <original_text> }`
     - For Vietnam use official province names (canonical English names) and normalized city names.
   - Original source(s):
     - Vietnam official administrative lists (Ministry / government publications)
     - ISO 3166 country codes for country-level normalization
   - References:
     - List of provinces of Vietnam — https://en.wikipedia.org/wiki/Provinces_of_Vietnam (use only as convenient reference; primary source should be an official government list when available)
     - ISO 3166 — https://www.iso.org/iso-3166-country-codes.html
   - Adaptation for Vietnam:
     - Map Vietnamese diacritics and local spellings to canonical English province/city names; prefer province-level canonicalization for ambiguous inputs.
     - When only "Hồ Chí Minh" or "HCM" found, normalize to `administrative_area: Ho Chi Minh` and canonical `country: VN`.
   - Fallback policy:
     - If mapping to an administrative area fails, set `administrative_area: null` but keep `raw` and `city` when available. Always include `country` if determinable; otherwise `country: unknown`.

6) experience_level
   - Canonical values (derived from LinkedIn/Indeed combined):
     - `internship`, `entry_level`, `associate`, `mid_senior`, `director`, `executive`, `unknown`
   - Original source:
     - LinkedIn experience level filter (Internship, Entry level, Associate, Mid-Senior level, Director, Executive)
     - Indeed job-posting experience tags
   - Adaptation for Vietnam:
     - Map local labels to canonical tokens. For Vietnamese postings using "Junior / Senior" semantics: map `junior`→`entry_level` (or `associate` depending on responsibilities), `senior`→`mid_senior`.
     - Provide a mapping table in code that documents examples from Vietnamese job text to canonical token (kept in `extract_normalization_constants.py`).
   - Fallback policy:
     - If level not found, set `experience_level: unknown` and preserve raw in `raw.experience_raw`.

7) industry
   - Canonical values:
     - Use LinkedIn industry taxonomy tokens (the canonical label strings from LinkedIn), for example:
       - `information_technology_and_services`, `financial_services`, `banking`, `manufacturing`, `healthcare`, `education`, `retail`, `consumer_goods`, `construction`, `transportation`, `telecommunications`, `government`, `non_profit`, `other`, `unknown`
   - Original source(s):
     - LinkedIn industry taxonomy (industry categories used on company pages and filters)
     - Public industry lists (NAICS/ISIC) can be used as authoritative cross-walk where needed
   - References:
     - LinkedIn industry categories (LinkedIn company profile/industry selection)
     - NAICS / ISIC documentation for academic crosswalks
   - Adaptation for Vietnam:
     - Map local industry wording (Vietnamese translations, local sector names like "F&B", "Fintech") to canonical tokens. When a posting references a sub-sector, map to the parent canonical industry.
     - Maintain a local crosswalk table: local term -> canonical industry token (store in `extract_normalization_constants.py`).
   - Fallback policy:
     - If no reasonable mapping, set `industry: unknown` and store original text in `raw.company_industry_raw`.

Appendix: Representation & Example
---------------------------------
Example normalized snippet (illustrative):

```
{
  "source_name": "example_job_board",
  "job_url": "https://...",
  "job": {
    "title": "Backend Engineer",
    "work_type": "full_time",
    "listed_time": "2026-04-01T00:00:00"
  },
  "company": {
    "name": "Example Co",
    "company_size": "51-200"
  },
  "salary": {
    "min_salary": 15000000,
    "max_salary": 30000000,
    "currency": "VND",
    "pay_period": "monthly"
  },
  "location": {
    "country": "VN",
    "administrative_area": "Ho Chi Minh",
    "city": "Ho Chi Minh",
    "raw": "Hồ Chí Minh City"
  },
  "experience_level": "mid_senior",
  "industry": "information_technology_and_services",
  "validation": { ... }
}
```

Document maintenance
--------------------
- Source links and mapping tables must be versioned alongside the code (store crosswalks in `extract_normalization_constants.py`).
- Any modification to canonical buckets (e.g., splitting `1001-5000`) must be recorded with rationale and dated.

Notes on defensibility for thesis
--------------------------------
- Each canonical token above is mapped to a public, authoritative source: LinkedIn/Indeed UI for job-type and experience filters; LinkedIn company-size buckets; ISO 4217 for currency; official Vietnam administrative lists for location; LinkedIn/NAICS/ISIC for industry classification.
- Adaptation choices (e.g., preferring `monthly` for Vietnam salaries) are grounded in observed market conventions and should be defended with empirical samples from the scraped corpus (include aggregated statistics of salary unit mentions when presenting).

End of Normalization Standard v1.0
