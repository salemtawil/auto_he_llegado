-- Unifica la app en un solo bucket de Storage: photo-pool.
-- Importante: este SQL NO mueve archivos entre buckets. Primero ejecuta el
-- script scripts/migrate_photos_bucket_to_photo_pool.py con --apply, o copia
-- manualmente los objetos de Storage desde photos hacia photo-pool.

alter table public.photos
add column if not exists storage_bucket text;

update public.photos
set storage_bucket = 'photo-pool'
where (storage_bucket = 'photos' or storage_bucket is null)
  and storage_deleted_at is null;

create index if not exists idx_photos_available_storage_bucket
on public.photos (status, storage_bucket)
where storage_deleted_at is null;

drop policy if exists "photo_candidate_storage_insert" on storage.objects;
create policy "photo_candidate_storage_insert"
on storage.objects for insert
to authenticated
with check (
    bucket_id = 'photo-pool'
    and (storage.foldername(name))[1] = 'candidates'
    and (storage.foldername(name))[2] = auth.uid()::text
    and public.can_submit_weekly_video(auth.uid())
);

drop policy if exists "photo_candidate_storage_select" on storage.objects;
create policy "photo_candidate_storage_select"
on storage.objects for select
to authenticated
using (
    bucket_id = 'photo-pool'
    and (
        public.is_profile_admin(auth.uid())
        or (storage.foldername(name))[1] = 'available'
        or (
            (storage.foldername(name))[1] = 'candidates'
            and (storage.foldername(name))[2] = auth.uid()::text
        )
    )
);

drop policy if exists "photo_admin_storage_write" on storage.objects;
create policy "photo_admin_storage_write"
on storage.objects for all
to authenticated
using (bucket_id = 'photo-pool' and public.is_profile_admin(auth.uid()))
with check (bucket_id = 'photo-pool' and public.is_profile_admin(auth.uid()));
