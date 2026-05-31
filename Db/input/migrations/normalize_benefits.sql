-- Normalize benefits: insert canonical list, dedupe, and remove non-canonical
BEGIN;

-- 1) Insert canonical benefits if missing
WITH canonical(benefit_name, category) AS (
  VALUES
    ('Remote work','Work Style / Flexibility'),
    ('Hybrid work','Work Style / Flexibility'),
    ('Work from home (wfh)','Work Style / Flexibility'),
    ('Flexible working hours','Work Style / Flexibility'),
    ('Flexible schedule','Work Style / Flexibility'),
    ('Compressed workweek','Work Style / Flexibility'),
    ('No overtime / Limited overtime','Work Style / Flexibility'),

    ('Competitive salary','Compensation & Financial'),
    ('Performance bonus','Compensation & Financial'),
    ('Annual bonus / Year-end bonus','Compensation & Financial'),
    ('Project bonus','Compensation & Financial'),
    ('Stock options','Compensation & Financial'),
    ('Salary review (annual / bi-annual)','Compensation & Financial'),
    ('Sign-on bonus','Compensation & Financial'),
    ('Referral bonus','Compensation & Financial'),
    ('Overtime pay','Compensation & Financial'),

    ('Health insurance','Health & Insurance'),
    ('Private health insurance','Health & Insurance'),
    ('Dental insurance','Health & Insurance'),
    ('Vision insurance','Health & Insurance'),
    ('Mental health support','Health & Insurance'),
    ('Annual health check','Health & Insurance'),
    ('Wellness program','Health & Insurance'),

    ('Training budget','Learning & Career Growth'),
    ('Learning allowance','Learning & Career Growth'),
    ('Certification sponsorship','Learning & Career Growth'),
    ('Paid courses (Udemy, Coursera, Pluralsight)','Learning & Career Growth'),
    ('Conference sponsorship','Learning & Career Growth'),
    ('Career path / career roadmap','Learning & Career Growth'),
    ('Mentorship program','Learning & Career Growth'),
    ('Internal mobility','Learning & Career Growth'),

    ('Paid time off (pto)','Leave & Work–Life Balance'),
    ('Annual leave','Leave & Work–Life Balance'),
    ('Sick leave','Leave & Work–Life Balance'),
    ('Personal leave','Leave & Work–Life Balance'),
    ('Parental leave / maternity leave / paternity leave','Leave & Work–Life Balance'),
    ('Birthday leave','Leave & Work–Life Balance'),
    ('Mental health day','Leave & Work–Life Balance'),

    ('Company laptop','Equipment & Work Setup'),
    ('MacBook provided','Equipment & Work Setup'),
    ('Work-from-home allowance','Equipment & Work Setup'),
    ('Ergonomic equipment','Equipment & Work Setup'),
    ('Software license provided','Equipment & Work Setup'),

    ('International working environment','Culture & Environment'),
    ('Multicultural team','Culture & Environment'),
    ('English-speaking environment','Culture & Environment'),
    ('Flat organization','Culture & Environment'),
    ('Open culture','Culture & Environment'),
    ('Innovation-driven culture','Culture & Environment'),

    ('Full-time contract','Legal / Contract'),
    ('Probation salary 100%','Legal / Contract'),
    ('13th month salary','Legal / Contract'),
    ('Social insurance','Legal / Contract'),
    ('Tax support','Legal / Contract')
)
INSERT INTO public.benefits(benefit_name, category)
SELECT c.benefit_name, c.category
FROM canonical c
LEFT JOIN public.benefits b ON lower(b.benefit_name) = lower(c.benefit_name)
WHERE b.benefit_id IS NULL;

-- 2) Deduplicate benefits by name (keep smallest benefit_id)
WITH ranked AS (
  SELECT benefit_id, benefit_name,
         ROW_NUMBER() OVER (PARTITION BY lower(benefit_name) ORDER BY benefit_id) AS rn
  FROM public.benefits
)
-- update job_benefits to point duplicates to the kept id
UPDATE public.job_benefits jb
SET benefit_id = keeper.benefit_id
FROM ranked dup
JOIN ranked keeper ON lower(dup.benefit_name) = lower(keeper.benefit_name) AND keeper.rn = 1
WHERE jb.benefit_id = dup.benefit_id AND dup.rn <> 1;

-- delete duplicate benefit rows
DELETE FROM public.benefits b
USING ranked r
WHERE b.benefit_id = r.benefit_id AND r.rn <> 1;

-- 3) Remove any job_benefits referencing non-canonical benefit names
-- (canonical list repeated here in lowercase form)
WITH canonical_names AS (
  SELECT lower(unnest(array[
    'Remote work','Hybrid work','Work from home (wfh)','Flexible working hours','Flexible schedule','Compressed workweek','No overtime / Limited overtime',
    'Competitive salary','Performance bonus','Annual bonus / Year-end bonus','Project bonus','Stock options','Salary review (annual / bi-annual)','Sign-on bonus','Referral bonus','Overtime pay',
    'Health insurance','Private health insurance','Dental insurance','Vision insurance','Mental health support','Annual health check','Wellness program',
    'Training budget','Learning allowance','Certification sponsorship','Paid courses (Udemy, Coursera, Pluralsight)','Conference sponsorship','Career path / career roadmap','Mentorship program','Internal mobility',
    'Paid time off (pto)','Annual leave','Sick leave','Personal leave','Parental leave / maternity leave / paternity leave','Birthday leave','Mental health day',
    'Company laptop','MacBook provided','Work-from-home allowance','Ergonomic equipment','Software license provided',
    'International working environment','Multicultural team','English-speaking environment','Flat organization','Open culture','Innovation-driven culture',
    'Full-time contract','Probation salary 100%','13th month salary','Social insurance','Tax support'
  ])) AS name
)

DELETE FROM public.job_benefits jb
WHERE NOT EXISTS (
  SELECT 1 FROM public.benefits b JOIN canonical_names cn ON lower(b.benefit_name) = cn.name
  WHERE b.benefit_id = jb.benefit_id
);

-- 4) Delete any benefit definitions that are not canonical
DELETE FROM public.benefits b
WHERE lower(b.benefit_name) NOT IN (
  SELECT name FROM (
    SELECT lower(unnest(array[
      'Remote work','Hybrid work','Work from home (wfh)','Flexible working hours','Flexible schedule','Compressed workweek','No overtime / Limited overtime',
      'Competitive salary','Performance bonus','Annual bonus / Year-end bonus','Project bonus','Stock options','Salary review (annual / bi-annual)','Sign-on bonus','Referral bonus','Overtime pay',
      'Health insurance','Private health insurance','Dental insurance','Vision insurance','Mental health support','Annual health check','Wellness program',
      'Training budget','Learning allowance','Certification sponsorship','Paid courses (Udemy, Coursera, Pluralsight)','Conference sponsorship','Career path / career roadmap','Mentorship program','Internal mobility',
      'Paid time off (pto)','Annual leave','Sick leave','Personal leave','Parental leave / maternity leave / paternity leave','Birthday leave','Mental health day',
      'Company laptop','MacBook provided','Work-from-home allowance','Ergonomic equipment','Software license provided',
      'International working environment','Multicultural team','English-speaking environment','Flat organization','Open culture','Innovation-driven culture',
      'Full-time contract','Probation salary 100%','13th month salary','Social insurance','Tax support'
    ])) AS name
  ) t
);

COMMIT;
