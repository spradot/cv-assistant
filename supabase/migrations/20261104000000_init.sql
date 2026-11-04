-- Esquema de la web de postulaciones. Aplicar con `supabase db push` (o pegar en el SQL Editor).
-- Una base por entorno: proyecto Supabase "dev" para la rama dev / Preview, "prod" para main.

create table if not exists usuarios (
    id bigint generated always as identity primary key,
    username text not null,
    email text,
    nombre text not null,
    password_hash text not null,
    es_admin boolean not null default false,
    onboarding_completo boolean not null default false,
    config jsonb not null default '{}'::jsonb,
    creado_en timestamptz not null default now()
);
create unique index if not exists usuarios_username_uq on usuarios (lower(username));
create index if not exists usuarios_email_idx on usuarios (lower(email));

create table if not exists sesiones (
    token_hash text primary key,
    user_id bigint not null references usuarios(id) on delete cascade,
    expira timestamptz not null
);
create index if not exists sesiones_user_idx on sesiones (user_id);

create table if not exists resets_password (
    token_hash text primary key,
    user_id bigint not null references usuarios(id) on delete cascade,
    expira timestamptz not null,
    usado boolean not null default false
);

create table if not exists web_postulaciones (
    id bigint generated always as identity primary key,
    user_id bigint not null references usuarios(id) on delete cascade,
    empresa text not null,
    estado text not null,  -- analizado, descartado, generado, aprobado, descartado_tras_revision
    datos jsonb not null,  -- todo el estado de la postulación (oferta, clasificación, CV, ATS, versiones)
    creado_en timestamptz not null default now(),
    actualizado_en timestamptz not null default now()
);
create index if not exists web_postulaciones_user_idx on web_postulaciones (user_id, id desc);

create table if not exists llm_uso (
    id bigint generated always as identity primary key,
    user_id bigint references usuarios(id) on delete set null,
    operacion text not null,
    proveedor text not null,
    modelo text,
    prompt_tokens integer default 0,
    cache_hit_tokens integer default 0,
    completion_tokens integer default 0,
    reasoning_tokens integer default 0,
    ms integer default 0,
    creado_en timestamptz not null default now()
);
create index if not exists llm_uso_user_idx on llm_uso (user_id, creado_en desc);

-- Límite de intentos por IP (login, registro, recuperación): en Postgres porque en serverless
-- la memoria no se comparte entre instancias.
create table if not exists intentos_limite (
    id bigint generated always as identity primary key,
    accion text not null,
    ip text not null,
    creado_en timestamptz not null default now()
);
create index if not exists intentos_limite_idx on intentos_limite (accion, ip, creado_en desc);

-- La API entra con el rol dueño de la base (cadena DATABASE_URL), que ignora RLS. Se activa RLS
-- sin políticas para que las claves publicables (anon/authenticated) no puedan leer NADA.
alter table usuarios enable row level security;
alter table sesiones enable row level security;
alter table resets_password enable row level security;
alter table web_postulaciones enable row level security;
alter table llm_uso enable row level security;
alter table intentos_limite enable row level security;

-- Bucket privado para perfiles, respaldos, YAML y PDFs (sin políticas: solo la clave de servicio).
insert into storage.buckets (id, name, public) values ('cvs', 'cvs', false) on conflict (id) do nothing;
