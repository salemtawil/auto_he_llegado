-- Quien esta usando la app.
--
-- Hasta ahora `process_logs` no guardaba quien habia iniciado sesion: solo
-- `agent_name`, que es el nombre que la persona ESCRIBE en el formulario. Dos
-- agentes que escriban lo mismo eran la misma persona para cualquier informe,
-- y quien escribiera cualquier cosa desaparecia. Por eso se ata cada corrida
-- al usuario de verdad.
--
-- Se guarda el id, no el correo. El correo puede cambiar; el id no. El panel
-- muestra el correo buscandolo en `profiles` al pintar, asi el historial
-- aguanta aunque alguien cambie de correo o de nombre.

-- 1. La columna. El valor por defecto es quien hace la peticion, asi que se
--    rellena sola y el agente no puede firmar como otro: `auth.uid()` sale de
--    su token, no de nada que el escriba.
alter table public.process_logs
add column if not exists user_id uuid references auth.users(id) on delete set null;

alter table public.process_logs
alter column user_id set default auth.uid();

create index if not exists idx_process_logs_user_id_started
on public.process_logs (user_id, started_at desc);

-- Las corridas anteriores a esta migracion se quedan sin usuario. No se puede
-- reconstruir lo que nunca se guardo: el panel las cuenta aparte, como
-- "sin identificar", en vez de repartirlas a ojo entre los agentes.


-- 2. La actividad, por agente. Solo admins.
--    Sale de `profiles`, no de `process_logs`, para que tambien aparezca
--    quien NO ha trabajado: saber quien lleva una semana sin abrir la app es
--    la mitad de la pregunta.
create or replace function public.actividad_de_agentes(
    p_dias int default 7,
    p_minutos_en_curso int default 120
)
returns table(
    user_id uuid,
    email text,
    display_name text,
    login_id text,
    role text,
    disabled boolean,
    corriendo boolean,
    corriendo_desde timestamptz,
    ultima_corrida timestamptz,
    ultimo_sitio text,
    ultimo_estado text,
    nombre_escrito text,
    corridas_hoy bigint,
    corridas_periodo bigint
)
language plpgsql
stable
security definer
set search_path = public
as $$
declare
    v_desde timestamptz := timezone('utc', now()) - make_interval(days => greatest(coalesce(p_dias, 7), 1));
    v_en_curso timestamptz := timezone('utc', now()) - make_interval(mins => greatest(coalesce(p_minutos_en_curso, 120), 1));
begin
    if not public.is_profile_admin(auth.uid()) then
        raise exception 'Solo un administrador puede consultar la actividad.';
    end if;

    return query
    with corridas as (
        select l.user_id, l.started_at, l.finished_at, l.site, l.final_status, l.agent_name
        from public.process_logs l
        where l.user_id is not null
          and l.started_at >= v_desde
    ),
    ultimas as (
        select distinct on (c.user_id)
            c.user_id, c.started_at, c.site, c.final_status, c.agent_name
        from corridas c
        order by c.user_id, c.started_at desc
    ),
    conteos as (
        select
            c.user_id,
            count(*) filter (
                where c.started_at >= date_trunc('day', timezone('utc', now()))
            )::bigint as hoy,
            count(*)::bigint as periodo
        from corridas c
        group by c.user_id
    ),
    -- Una corrida que reviento deja `finished_at` en null para siempre, asi
    -- que "en curso" no puede ser solo eso: tiene que haber empezado hace
    -- poco. Si no, un cuelgue de hace un mes saldria como agente trabajando.
    abiertas as (
        select distinct on (c.user_id) c.user_id, c.started_at
        from corridas c
        where c.finished_at is null
          and c.started_at >= v_en_curso
        order by c.user_id, c.started_at desc
    )
    select
        p.id,
        coalesce(p.email, '')::text,
        coalesce(p.display_name, '')::text,
        coalesce(p.login_id, '')::text,
        coalesce(p.role, 'member')::text,
        coalesce(p.disabled, false),
        (a.user_id is not null),
        a.started_at,
        u.started_at,
        coalesce(u.site, '')::text,
        coalesce(u.final_status, '')::text,
        coalesce(u.agent_name, '')::text,
        coalesce(n.hoy, 0)::bigint,
        coalesce(n.periodo, 0)::bigint
    from public.profiles p
    left join ultimas u on u.user_id = p.id
    left join conteos n on n.user_id = p.id
    left join abiertas a on a.user_id = p.id
    order by a.user_id is null, u.started_at desc nulls last, p.email;
end;
$$;

grant execute on function public.actividad_de_agentes(int, int) to authenticated;


-- 3. Las corridas que no se pueden atribuir a nadie.
--    Son las anteriores a la columna, mas cualquiera que llegue sin usuario.
--    Si este numero no baja a cero con el tiempo, algo escribe sin sesion.
create or replace function public.corridas_sin_identificar(p_dias int default 7)
returns bigint
language plpgsql
stable
security definer
set search_path = public
as $$
declare
    v_desde timestamptz := timezone('utc', now()) - make_interval(days => greatest(coalesce(p_dias, 7), 1));
begin
    if not public.is_profile_admin(auth.uid()) then
        raise exception 'Solo un administrador puede consultar la actividad.';
    end if;
    return (
        select count(*)::bigint
        from public.process_logs l
        where l.user_id is null
          and l.started_at >= v_desde
    );
end;
$$;

grant execute on function public.corridas_sin_identificar(int) to authenticated;

notify pgrst, 'reload schema';
