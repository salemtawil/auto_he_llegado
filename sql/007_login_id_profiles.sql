alter table public.profiles
add column if not exists login_id text;

create unique index if not exists idx_profiles_login_id_unique
on public.profiles (lower(login_id))
where login_id is not null and login_id <> '';

create or replace function public.handle_new_auth_user_profile()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, email, login_id, display_name)
    values (
        new.id,
        coalesce(nullif(new.email, ''), new.id::text),
        nullif(lower(new.raw_user_meta_data->>'login_id'), ''),
        coalesce(new.raw_user_meta_data->>'display_name', '')
    )
    on conflict (id) do update
    set
        email = excluded.email,
        login_id = coalesce(public.profiles.login_id, excluded.login_id),
        updated_at = timezone('utc', now());
    return new;
end;
$$;

create or replace function public.resolve_login_identifier(p_identifier text)
returns table(email text)
language sql
stable
security definer
set search_path = public
as $$
    select p.email
    from public.profiles p
    where lower(p.login_id) = lower(trim(p_identifier))
       or lower(p.email) = lower(trim(p_identifier))
    limit 1;
$$;

grant execute on function public.resolve_login_identifier(text) to anon, authenticated;
