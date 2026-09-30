# Supabase email signup confirmation

Email signup uses Supabase Auth's hosted default **Confirm signup** email and
the BFF callback at `/api/auth/signup/callback`. The signup API creates a
pending Supabase user with a random temporary password, an S256 PKCE challenge,
and `redirect_to` set to that callback. The temporary password is never sent to
the browser. The user chooses a password only after opening the confirmation
link from their mailbox.

The callback GET stages the PKCE code in a short-lived HttpOnly cookie and
redirects to a clean URL. A same-origin form POST exchanges the code with the
verifier from the initiating browser, checks the confirmed user identity,
updates the password, then sets the ordinary HttpOnly BFF session cookies and
creates the personal organization. Repeated provisioning is safe with the
current per-user transaction lock. A browser that already has either BFF
session cookie is rejected without changing that session; use a Guest/Incognito
window for a new signup. The confirmation link must be opened in the same
browser that started signup so its PKCE verifier is present.

## Staging configuration

For the local staging QA app, add this exact callback URL under the staging
Supabase project **Authentication → URL Configuration → Redirect URLs**:

```text
http://localhost:4174/api/auth/signup/callback
```

If staging runs at another origin, add that exact origin plus
`/api/auth/signup/callback`; set backend `PUBLIC_APP_URL` to the same origin.
The Origin check uses this configured value, including when a reverse proxy
terminates TLS.

Keep email confirmation enabled in the staging Auth settings. Leave Supabase's
hosted **Confirm signup** template on its default
`ConfirmationURL`. No custom email template, `.TokenHash`, SMTP setup, Resend,
or provider change is needed. Supabase uses the `redirect_to` supplied by the
signup request after the default confirmation link is verified. The Site URL
can remain the existing staging URL; it is the fallback when no redirect is
provided.

For local HTTP on `localhost`, set `AUTH_COOKIE_SECURE=false` so the short-lived
PKCE cookies can round-trip. Keep it `true` for HTTPS; the cookies then use the
`__Host-` prefix and the Secure attribute. Do not disable Secure on HTTPS.

The verifier cookie lasts one hour and the staged code cookie lasts five
minutes. The POST requires an Origin matching `PUBLIC_APP_URL`; a scanner that
only follows GET requests after the hosted confirmation redirect cannot
exchange the staged code or set a password. This does not prevent an email
scanner from visiting Supabase's hosted `ConfirmationURL` before that redirect.
The end-to-end email-link behavior is not scanner-proof or verified; if a
scanner consumes the hosted confirmation link before the user opens it, the
user may need password recovery to complete sign-in. Recheck this flow in the
pre-Closed-Beta QA.
