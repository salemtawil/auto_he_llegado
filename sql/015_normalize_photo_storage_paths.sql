-- Normalize existing Storage paths saved with Windows backslashes.

update public.photos
set file_path = replace(file_path, chr(92), '/')
where strpos(file_path, chr(92)) > 0;

update public.photo_candidates
set storage_path = replace(storage_path, chr(92), '/')
where strpos(storage_path, chr(92)) > 0;
