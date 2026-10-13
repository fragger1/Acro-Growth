-- Maps lists commercial roofers under the plain "Roofing contractor" category, so a
-- "commercial roofing" search would otherwise have every result skipped as off-target.
insert into public.keyword_categories (keyword, pattern) values
  ('commercial roofing', 'Roofing contractor')
on conflict do nothing;
