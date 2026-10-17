create table if not exists public.user_profiles (
    user_id bigint primary key,
    profile_data text not null default '',
    updated_at timestamptz not null default now()
);

alter table public.user_profiles enable row level security;

create or replace function public.set_user_profiles_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists user_profiles_updated_at on public.user_profiles;
create trigger user_profiles_updated_at
before update on public.user_profiles
for each row execute function public.set_user_profiles_updated_at();
