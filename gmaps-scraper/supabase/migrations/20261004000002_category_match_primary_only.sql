-- Match on a place's primary category only. Secondary categories let through mostly off-target
-- places: of Jeff's leads, ~600 matched only via a secondary category, led by UPS-store-style
-- "Shipping and mailing service" (secondary "Print shop"), paint stores, insurance agencies.
create or replace function public.leads_for_export(
  p_client text,
  p_since timestamptz default null,
  p_keyword text default null,
  p_include_no_email boolean default false,
  p_new_only boolean default false
)
returns table (
  place_id text, name text, category text, primary_email text, all_emails text, phone text,
  website text, address text, city text, state text, postal_code text, rating numeric,
  review_count int, maps_url text, category_match boolean
)
language sql
stable
set search_path = public
as $$
  with kw as (
    select distinct lower(q.keyword) as keyword from search_queue q where q.client = p_client
  ), pats as (
    select '%' || kw.keyword || '%' as pattern from kw
    union
    select kc.pattern from keyword_categories kc join kw on kw.keyword = lower(kc.keyword)
  )
  select p.place_id, p.name, p.category, p.primary_email, array_to_string(p.emails, '; '),
         p.phone, p.website, p.address, p.city, p.state, p.postal_code, p.rating,
         p.review_count, p.maps_url,
         exists (select 1 from pats where p.category ilike pats.pattern)
  from place_clients pc
  join places p on p.place_id = pc.place_id
  left join search_queue s on s.id = pc.search_id
  where pc.client = p_client
    and (p_since is null or pc.first_seen_at >= p_since)
    and (p_keyword is null or s.keyword ilike p_keyword)
    and (p_include_no_email or p.primary_email is not null)
    and (not p_new_only or not exists (
      select 1 from export_items ei join exports e on e.id = ei.export_id
      where e.client = p_client and ei.place_id = p.place_id))
  order by pc.first_seen_at, p.place_id;
$$;
