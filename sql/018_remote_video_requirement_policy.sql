create table if not exists public.app_settings (
    key text primary key,
    value jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default timezone('utc', now())
);

insert into public.app_settings (key, value)
values (
    'video_requirement',
    '{"enabled": true, "days": 7, "duration_based": true, "long_video_days": 14, "long_video_min_duration_seconds": 25}'::jsonb
)
on conflict (key) do nothing;

update public.app_settings
set value = jsonb_strip_nulls(
    value
    || jsonb_build_object(
        'duration_based',
        coalesce(value->'duration_based', 'true'::jsonb),
        'long_video_days',
        coalesce(value->'long_video_days', value->'days', '14'::jsonb),
        'long_video_min_duration_seconds',
        coalesce(value->'long_video_min_duration_seconds', '25'::jsonb)
    )
)
where key = 'video_requirement';

alter table public.app_settings enable row level security;

drop policy if exists "app_settings_admin_select" on public.app_settings;
create policy "app_settings_admin_select"
on public.app_settings for select
to authenticated
using (public.is_profile_admin(auth.uid()));

drop policy if exists "app_settings_admin_update" on public.app_settings;
create policy "app_settings_admin_update"
on public.app_settings for update
to authenticated
using (public.is_profile_admin(auth.uid()))
with check (public.is_profile_admin(auth.uid()));

drop policy if exists "app_settings_admin_insert" on public.app_settings;
create policy "app_settings_admin_insert"
on public.app_settings for insert
to authenticated
with check (public.is_profile_admin(auth.uid()));

drop function if exists public.get_video_requirement_policy();

create function public.get_video_requirement_policy()
returns table(
    enabled boolean,
    days integer,
    duration_based boolean,
    long_video_days integer,
    long_video_min_duration_seconds numeric
)
language sql
stable
security definer
set search_path = public
as $$
    select
        coalesce((s.value->>'enabled')::boolean, true) as enabled,
        least(
            greatest(
                case
                    when coalesce(s.value->>'days', '') ~ '^[0-9]+$'
                        then (s.value->>'days')::integer
                    else 7
                end,
                1
            ),
            365
        ) as days,
        coalesce((s.value->>'duration_based')::boolean, true) as duration_based,
        least(
            greatest(
                case
                    when coalesce(s.value->>'long_video_days', '') ~ '^[0-9]+$'
                        then (s.value->>'long_video_days')::integer
                    when coalesce(s.value->>'days', '') ~ '^[0-9]+$'
                        then (s.value->>'days')::integer
                    else 14
                end,
                1
            ),
            365
        ) as long_video_days,
        least(
            greatest(
                case
                    when coalesce(s.value->>'long_video_min_duration_seconds', '') ~ '^[0-9]+(\.[0-9]+)?$'
                        then (s.value->>'long_video_min_duration_seconds')::numeric
                    else 25
                end,
                0
            ),
            3600
        ) as long_video_min_duration_seconds
    from public.app_settings s
    where s.key = 'video_requirement'
    union all
    select true, 7, true, 14, 25
    where not exists (
        select 1
        from public.app_settings s
        where s.key = 'video_requirement'
    )
    limit 1;
$$;

grant execute on function public.get_video_requirement_policy() to anon, authenticated;

create or replace function public.has_current_week_contribution(
    p_user_id uuid default auth.uid(),
    p_week_start date default date_trunc('week', timezone('utc', now()))::date
)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    with policy as (
        select enabled, days, duration_based, long_video_days, long_video_min_duration_seconds
        from public.get_video_requirement_policy()
    ), latest_batch as (
        select
            b.status,
            b.created_at,
            coalesce(b.video_duration_seconds, 0) as video_duration_seconds,
            case
                when p.duration_based = true
                 and coalesce(b.video_duration_seconds, 0) >= p.long_video_min_duration_seconds
                    then p.long_video_days
                else p.days
            end as effective_days
        from public.photo_ingest_batches b, policy p
        where p.enabled = true
          and b.user_id = p_user_id
          and b.created_at >= timezone('utc', now()) - make_interval(
              days => case when p.duration_based = true then greatest(p.days, p.long_video_days) else p.days end
          )
        order by b.created_at desc
        limit 1
    )
    select exists (
        select 1
        from latest_batch b
        where b.status in ('processing', 'pending_review', 'accepted', 'reviewed')
          and b.created_at >= timezone('utc', now()) - make_interval(days => b.effective_days)
    );
$$;

create or replace function public.is_active_member(
    p_user_id uuid default auth.uid(),
    p_week_start date default date_trunc('week', timezone('utc', now()))::date
)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    with policy as (
        select enabled
        from public.get_video_requirement_policy()
    )
    select exists (
        select 1
        from public.profiles p, policy v
        where p.id = p_user_id
          and p.approved = true
          and p.disabled = false
          and (
            p.role = 'admin'
            or v.enabled = false
            or public.has_current_week_contribution(p_user_id, p_week_start)
          )
    );
$$;
