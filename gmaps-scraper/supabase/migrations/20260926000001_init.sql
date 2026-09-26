-- Google Maps lead scraper schema

create table public.runs (
  id bigint generated always as identity primary key,
  trigger text not null check (trigger in ('scheduled', 'manual')),
  place_limit int check (place_limit > 0),
  status text not null default 'running' check (status in ('running', 'done', 'failed')),
  searches_done int not null default 0,
  places_scraped int not null default 0,
  places_new int not null default 0,
  places_with_email int not null default 0,
  failed_searches int not null default 0,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  notes text
);

create table public.search_queue (
  id bigint generated always as identity primary key,
  keyword text not null,
  location text not null,
  query text not null,
  client text not null,
  place_limit int check (place_limit > 0),
  status text not null default 'pending' check (status in ('pending', 'running', 'done', 'failed')),
  run_id bigint references public.runs(id),
  found_count int,
  new_count int,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create unique index search_queue_active_uniq on public.search_queue (query, client)
  where status in ('pending', 'running');
create index search_queue_status_idx on public.search_queue (status, id);
create index search_queue_client_query_idx on public.search_queue (client, query);

create table public.places (
  place_id text primary key,
  name text,
  category text,
  categories text[] not null default '{}',
  address text,
  city text,
  state text,
  postal_code text,
  country text,
  phone text,
  website text,
  domain text,
  rating numeric(2,1),
  review_count int not null default 0,
  lat double precision,
  lng double precision,
  maps_url text,
  hours jsonb,
  emails text[] not null default '{}',
  primary_email text,
  raw jsonb,
  first_seen_at timestamptz not null default now(),
  last_scraped_at timestamptz not null default now()
);

create table public.place_clients (
  place_id text not null references public.places(place_id) on delete cascade,
  client text not null,
  search_id bigint references public.search_queue(id) on delete set null,
  first_seen_at timestamptz not null default now(),
  primary key (place_id, client)
);
create index place_clients_client_idx on public.place_clients (client, first_seen_at);
create index place_clients_search_idx on public.place_clients (search_id);

create table public.settings (
  key text primary key,
  value jsonb
);
insert into public.settings (key, value) values
  ('nightly_limit', '1000'),
  ('concurrency', '3'),
  ('depth', '12');

create table public.exports (
  id bigint generated always as identity primary key,
  client text not null,
  filters jsonb not null default '{}',
  row_count int not null,
  file_name text not null,
  created_at timestamptz not null default now()
);

create table public.export_items (
  export_id bigint not null references public.exports(id) on delete cascade,
  place_id text not null references public.places(place_id) on delete cascade,
  primary key (export_id, place_id)
);
create index export_items_place_idx on public.export_items (place_id);

create view public.leads_export with (security_invoker = true) as
select pc.client, p.name, p.category, p.primary_email,
       array_to_string(p.emails, '; ') as all_emails, p.phone, p.website, p.address,
       p.city, p.state, p.postal_code, p.rating, p.review_count, p.maps_url,
       pc.first_seen_at, s.keyword, s.location
from public.place_clients pc
join public.places p on p.place_id = pc.place_id
left join public.search_queue s on s.id = pc.search_id;

-- Upsert a batch of places, merge emails, link to client. Returns which were new to the client.
create or replace function public.upsert_places(p_places jsonb, p_client text, p_search_id bigint)
returns table (out_place_id text, out_is_new boolean)
language plpgsql
set search_path = public
as $$
begin
  insert into places as p (
    place_id, name, category, categories, address, city, state, postal_code, country, phone,
    website, domain, rating, review_count, lat, lng, maps_url, hours, emails, primary_email, raw
  )
  select x.place_id, x.name, x.category, coalesce(x.categories, '{}'), x.address, x.city, x.state,
         x.postal_code, x.country, x.phone, x.website, x.domain, x.rating, coalesce(x.review_count, 0),
         x.lat, x.lng, x.maps_url, x.hours, coalesce(x.emails, '{}'), x.primary_email, x.raw
  from jsonb_to_recordset(p_places) as x(
    place_id text, name text, category text, categories text[], address text, city text,
    state text, postal_code text, country text, phone text, website text, domain text,
    rating numeric, review_count int, lat double precision, lng double precision,
    maps_url text, hours jsonb, emails text[], primary_email text, raw jsonb
  )
  on conflict (place_id) do update set
    name = excluded.name,
    category = excluded.category,
    categories = excluded.categories,
    address = excluded.address,
    city = excluded.city,
    state = excluded.state,
    postal_code = excluded.postal_code,
    country = excluded.country,
    phone = coalesce(excluded.phone, p.phone),
    website = coalesce(excluded.website, p.website),
    domain = coalesce(excluded.domain, p.domain),
    rating = excluded.rating,
    review_count = excluded.review_count,
    lat = excluded.lat,
    lng = excluded.lng,
    maps_url = coalesce(excluded.maps_url, p.maps_url),
    hours = coalesce(excluded.hours, p.hours),
    emails = (select coalesce(array_agg(distinct e order by e), '{}')
              from unnest(p.emails || excluded.emails) as e),
    primary_email = coalesce(excluded.primary_email, p.primary_email),
    raw = excluded.raw,
    last_scraped_at = now();

  return query
  with ids as (
    select x.place_id from jsonb_to_recordset(p_places) as x(place_id text)
  ), ins as (
    insert into place_clients (place_id, client, search_id)
    select ids.place_id, p_client, p_search_id from ids
    on conflict (place_id, client) do nothing
    returning place_clients.place_id
  )
  select ids.place_id, exists (select 1 from ins where ins.place_id = ids.place_id)
  from ids;
end;
$$;

-- Atomically claim the oldest pending search for a run.
create or replace function public.claim_next_search(p_run_id bigint)
returns setof public.search_queue
language sql
set search_path = public
as $$
  update search_queue
     set status = 'running', run_id = p_run_id, started_at = now(), error = null
   where id = (
     select id from search_queue where status = 'pending' order by id limit 1 for update skip locked
   )
  returning *;
$$;

-- Rows for a client CSV export.
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
  review_count int, maps_url text
)
language sql
stable
set search_path = public
as $$
  select p.place_id, p.name, p.category, p.primary_email, array_to_string(p.emails, '; '),
         p.phone, p.website, p.address, p.city, p.state, p.postal_code, p.rating,
         p.review_count, p.maps_url
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

-- Lock down: RLS on, no policies; only service_role executes functions.
alter table public.runs enable row level security;
alter table public.search_queue enable row level security;
alter table public.places enable row level security;
alter table public.place_clients enable row level security;
alter table public.settings enable row level security;
alter table public.exports enable row level security;
alter table public.export_items enable row level security;

revoke all on function public.upsert_places(jsonb, text, bigint) from public, anon, authenticated;
revoke all on function public.claim_next_search(bigint) from public, anon, authenticated;
revoke all on function public.leads_for_export(text, timestamptz, text, boolean, boolean) from public, anon, authenticated;
grant execute on function public.upsert_places(jsonb, text, bigint) to service_role;
grant execute on function public.claim_next_search(bigint) to service_role;
grant execute on function public.leads_for_export(text, timestamptz, text, boolean, boolean) to service_role;
revoke all on public.leads_export from anon, authenticated;

-- Grant service_role direct table access for the data access layer
grant select on table public.settings to service_role;
grant select, insert, update on table public.runs to service_role;
grant select, insert, update on table public.search_queue to service_role;
grant select, insert, update on table public.places to service_role;
grant select, insert on table public.place_clients to service_role;
grant select, insert on table public.exports to service_role;
grant select, insert on table public.export_items to service_role;
