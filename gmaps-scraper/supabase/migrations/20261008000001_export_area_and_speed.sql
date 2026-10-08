-- Three export changes:
--
-- 1. Speed. category_match ran ~316 ILIKE patterns per lead (12.8k leads for jeff, ~10 s per call,
--    and the export pages through the function), so exports hit the statement timeout. Patterns are
--    now matched once per distinct category.
-- 2. Service area. A Maps search pads results with far-away places (Topeka, St. Louis, Wichita for
--    Kansas City searches), and ~1/5 of places have no address to filter on, only lat/lng. A client
--    with a client_areas row gets in_area = within radius_miles of its centre; clients without one
--    are unrestricted.
-- 3. shared_email_domains: email domains found on several unrelated websites (font foundries, site
--    platforms, placeholders) so the export can drop them as junk.

create table public.client_areas (
  client text primary key,
  lat double precision not null,
  lng double precision not null,
  radius_miles numeric not null check (radius_miles > 0)
);
alter table public.client_areas enable row level security;
grant select, insert, update, delete on table public.client_areas to service_role;

-- Centre of Jeff's 60 service-area cities (Overland Park); the farthest, Ottawa, is 36.4 miles out.
insert into public.client_areas (client, lat, lng, radius_miles) values ('jeff', 38.9116, -94.7103, 40);

create function public.miles_between(lat1 double precision, lng1 double precision,
                                     lat2 double precision, lng2 double precision)
returns double precision
language sql
immutable
set search_path = public
as $$
  select 3958.8 * 2 * asin(sqrt(
    power(sin(radians(lat2 - lat1) / 2), 2)
    + cos(radians(lat1)) * cos(radians(lat2)) * power(sin(radians(lng2 - lng1) / 2), 2)));
$$;

-- The return type gains a column, so the function has to be dropped and recreated.
drop function public.leads_for_export(text, timestamptz, text, boolean, boolean);

create function public.leads_for_export(
  p_client text,
  p_since timestamptz default null,
  p_keyword text default null,
  p_include_no_email boolean default false,
  p_new_only boolean default false
)
returns table (
  place_id text, name text, category text, primary_email text, all_emails text, phone text,
  website text, address text, city text, state text, postal_code text, rating numeric,
  review_count int, maps_url text, category_match boolean, in_area boolean
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
  ), leads as (
    select p.*, pc.first_seen_at as client_first_seen_at
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
  ), cats as (
    select c.category, exists (select 1 from pats where c.category ilike pats.pattern) as hit
    from (select distinct l.category from leads l where l.category is not null) c
  ), area as (
    select * from client_areas a where a.client = p_client
  )
  select l.place_id, l.name, l.category, l.primary_email, array_to_string(l.emails, '; '),
         l.phone, l.website, l.address, l.city, l.state, l.postal_code, l.rating,
         l.review_count, l.maps_url,
         coalesce(cats.hit, false),
         not exists (select 1 from area)
           or exists (select 1 from area a
                      where l.lat is not null
                        and miles_between(a.lat, a.lng, l.lat, l.lng) <= a.radius_miles)
  from leads l
  left join cats on cats.category = l.category
  order by l.client_first_seen_at, l.place_id;
$$;

revoke all on function public.leads_for_export(text, timestamptz, text, boolean, boolean)
  from public, anon, authenticated;
grant execute on function public.leads_for_export(text, timestamptz, text, boolean, boolean)
  to service_role;

create function public.shared_email_domains(p_min_sites int default 3)
returns table (domain text, sites int)
language sql
stable
set search_path = public
as $$
  select split_part(e, '@', 2), count(distinct p.domain)::int
  from places p, unnest(p.emails) as e
  where p.domain is not null and split_part(e, '@', 2) <> p.domain
  group by 1
  having count(distinct p.domain) >= p_min_sites;
$$;

revoke all on function public.shared_email_domains(int) from public, anon, authenticated;
grant execute on function public.shared_email_domains(int) to service_role;
