-- outbound_dedup is written and read by the trusted backend for idempotency.
-- Migration 045 installed a deny-client policy but omitted ENABLE ROW LEVEL
-- SECURITY, leaving that policy inactive. Keep the table owner / BYPASSRLS
-- backend path working; do not FORCE RLS on the owner.
ALTER TABLE public.outbound_dedup ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS outbound_dedup_deny_all ON public.outbound_dedup;
CREATE POLICY outbound_dedup_deny_all ON public.outbound_dedup
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

-- The table is server-only. Remove client ACLs as a second fail-closed layer.
REVOKE ALL ON public.outbound_dedup FROM PUBLIC, anon, authenticated;
