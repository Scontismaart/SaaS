-- Durable principal access policy. Never infer first-time signup from missing
-- memberships, and never store this policy in a client-editable profile/JWT.
CREATE TABLE IF NOT EXISTS public.auth_access_lifecycle (
    auth_user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    provisioned_at TIMESTAMPTZ,
    disabled_at TIMESTAMPTZ
);
ALTER TABLE public.auth_access_lifecycle ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.auth_access_lifecycle FROM PUBLIC, anon, authenticated;
DROP POLICY IF EXISTS auth_access_lifecycle_deny_clients ON public.auth_access_lifecycle;
CREATE POLICY auth_access_lifecycle_deny_clients ON public.auth_access_lifecycle
    TO anon, authenticated USING (false) WITH CHECK (false);

-- Existing tenant RLS policies all resolve membership through user_profiles.
-- A restrictive gate also denies direct PostgREST access with an old user JWT,
-- without deleting profiles, memberships or tenant data. No arbitrary subject
-- input and no mutation RPC: this helper can only report the caller's access.
CREATE OR REPLACE FUNCTION public.current_auth_access_allowed()
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.auth_access_lifecycle
        WHERE auth_user_id = (SELECT auth.uid()) AND disabled_at IS NULL
          AND (provisioned_at IS NULL OR EXISTS (
              SELECT 1 FROM public.organization_memberships om
              JOIN public.user_profiles up ON up.id = om.user_id
              WHERE up.auth_user_id = (SELECT auth.uid())
          ))
    );
$$;
REVOKE ALL ON FUNCTION public.current_auth_access_allowed() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.current_auth_access_allowed() TO authenticated;
DROP POLICY IF EXISTS user_profiles_active_access ON public.user_profiles;
CREATE POLICY user_profiles_active_access ON public.user_profiles AS RESTRICTIVE
    FOR ALL TO authenticated
    USING ((SELECT public.current_auth_access_allowed()))
    WITH CHECK ((SELECT public.current_auth_access_allowed()));

-- Historical users lack reliable first-provisioning history: conservatively
-- deny JIT if their memberships are gone. Replays must NOT change new-user or
-- disabled state created since the first application of this migration.
INSERT INTO public.auth_access_lifecycle (auth_user_id, provisioned_at)
SELECT id, NOW() FROM auth.users
ON CONFLICT (auth_user_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.initialize_auth_access_lifecycle()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    INSERT INTO public.auth_access_lifecycle (auth_user_id)
    VALUES (NEW.id) ON CONFLICT (auth_user_id) DO NOTHING;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.initialize_auth_access_lifecycle() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS trg_initialize_auth_access_lifecycle ON auth.users;
CREATE TRIGGER trg_initialize_auth_access_lifecycle AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.initialize_auth_access_lifecycle();

-- Covers every grant path, including invitation acceptance. Share the same
-- row lock with JIT and disable; failed writes roll back the lifecycle change.
CREATE OR REPLACE FUNCTION public.mark_auth_access_provisioned()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    subject UUID;
    access_disabled TIMESTAMPTZ;
BEGIN
    SELECT auth_user_id INTO subject FROM public.user_profiles WHERE id = NEW.user_id;
    SELECT disabled_at INTO access_disabled FROM public.auth_access_lifecycle
        WHERE auth_user_id = subject FOR UPDATE;
    IF NOT FOUND OR access_disabled IS NOT NULL THEN
        RAISE EXCEPTION 'Account access denied' USING ERRCODE = '42501';
    END IF;
    UPDATE public.auth_access_lifecycle
        SET provisioned_at = COALESCE(provisioned_at, NOW()) WHERE auth_user_id = subject;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.mark_auth_access_provisioned() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS trg_mark_auth_access_provisioned ON public.organization_memberships;
CREATE TRIGGER trg_mark_auth_access_provisioned
    BEFORE INSERT OR UPDATE OF user_id ON public.organization_memberships
    FOR EACH ROW EXECUTE FUNCTION public.mark_auth_access_provisioned();
