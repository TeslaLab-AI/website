-- Migration 010 — Add user_type to profiles for user onboarding

ALTER TABLE public.profiles 
    ADD COLUMN IF NOT EXISTS user_type text;

COMMENT ON COLUMN public.profiles.user_type IS 'Stored onboarding selection: startup, agency, freelancer, others';
