alter table public.photos
add column if not exists storage_bucket text;

update public.photos p
set storage_bucket = 'photos'
where p.storage_bucket is null
  and exists (
      select 1
      from public.photo_candidates c
      where c.approved_photo_id = p.id
  );

update public.photos
set storage_bucket = 'photo-pool'
where storage_bucket is null;

create index if not exists idx_photos_available_storage_bucket
on public.photos (status, storage_bucket)
where storage_deleted_at is null;
