-- Durable page cursor for bounded Google Business Profile review syncs.
-- Cursor is stored on the existing organization-scoped credential row and is
-- tied to the exact account/location so credential changes cannot cross scopes.
-- This table is server-owned: browser clients use the authorized FastAPI API,
-- and must not read or mutate OAuth credentials or synchronization state.
ALTER TABLE google_business_credentials
    ADD COLUMN IF NOT EXISTS review_page_token TEXT,
    ADD COLUMN IF NOT EXISTS review_page_account_name TEXT,
    ADD COLUMN IF NOT EXISTS review_page_location_name TEXT;

-- Migration 026's tenant-member FOR ALL policy exposed every column to direct
-- PostgREST access. Drop it, keep RLS enabled, and use a restrictive deny as a
-- fail-closed guard if a future permissive client policy is added accidentally.
DROP POLICY IF EXISTS google_business_credentials_org_member
    ON public.google_business_credentials;
DROP POLICY IF EXISTS google_business_credentials_server_only
    ON public.google_business_credentials;
CREATE POLICY google_business_credentials_server_only
    ON public.google_business_credentials
    AS RESTRICTIVE
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

ALTER TABLE public.google_business_credentials ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public.google_business_credentials
    FROM PUBLIC, anon, authenticated;
REVOKE SELECT (review_page_token, review_page_account_name, review_page_location_name),
        INSERT (review_page_token, review_page_account_name, review_page_location_name),
        UPDATE (review_page_token, review_page_account_name, review_page_location_name),
        REFERENCES (review_page_token, review_page_account_name, review_page_location_name)
    ON TABLE public.google_business_credentials
    FROM PUBLIC, anon, authenticated;
