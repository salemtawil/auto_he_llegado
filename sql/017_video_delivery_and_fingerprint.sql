-- Video delivery and perceptual duplicate detection metadata.
-- Keeps full videos outside Supabase Storage while preserving audit records.

alter table public.photo_ingest_batches
add column if not exists video_sha256 text,
add column if not exists video_size_bytes bigint,
add column if not exists video_duration_seconds numeric,
add column if not exists video_width integer,
add column if not exists video_height integer,
add column if not exists video_fingerprint jsonb,
add column if not exists duplicate_score numeric,
add column if not exists duplicate_of_batch_id uuid references public.photo_ingest_batches(id),
add column if not exists delivery_provider text,
add column if not exists delivery_file_id text,
add column if not exists delivery_url text;

create index if not exists idx_photo_batches_video_sha256
on public.photo_ingest_batches (video_sha256)
where video_sha256 is not null;

create index if not exists idx_photo_batches_video_fingerprint
on public.photo_ingest_batches using gin (video_fingerprint)
where video_fingerprint is not null;
