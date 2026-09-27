-- New Supabase projects do not auto-grant table privileges; the local script uses the secret (service_role) key.
grant select on table public.settings to service_role;
grant select, insert, update on table public.runs to service_role;
grant select, insert, update on table public.search_queue to service_role;
grant select, insert, update on table public.places to service_role;
grant select, insert on table public.place_clients to service_role;
grant select, insert on table public.exports to service_role;
grant select, insert on table public.export_items to service_role;
grant select on public.leads_export to service_role;
