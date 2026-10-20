create table if not exists public.profiles (
    user_id bigint primary key,
    username text,
    xp bigint not null default 0,
    persona text not null default 'default',
    timezone text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.profiles
    add column if not exists username text,
    add column if not exists xp bigint not null default 0,
    add column if not exists persona text not null default 'default',
    add column if not exists timezone text,
    add column if not exists created_at timestamptz not null default now(),
    add column if not exists updated_at timestamptz not null default now();
