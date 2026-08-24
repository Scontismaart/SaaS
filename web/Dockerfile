# syntax=docker/dockerfile:1

# Frontend statico (restyle): nginx serve landing su "/" e dashboard su "/app/"
# in un unico container. In produzione il backend è raggiunto same-origin
# su "/api/*" (proxy Traefik): MELPIS_API_BASE resta vuota -> niente CORS,
# cookie same-site.
#
# Build context: web/   -> docker build -f web/Dockerfile web/
# Per l'envsubst serve gettext; l'entrypoint ufficiale nginx esegue gli
# script in /docker-entrypoint.d/ prima di avviare il daemon.

FROM nginx:1.27-alpine AS runtime

# ── Landing (root del docroot) ──────────────────────────────
COPY landing/index.html landing/style.css landing/app.js /usr/share/nginx/html/
COPY landing/privacy.html landing/termini.html landing/cookie.html landing/404.html /usr/share/nginx/html/
COPY landing/robots.txt landing/sitemap.xml landing/og-image.jpg /usr/share/nginx/html/
COPY landing/*.webp /usr/share/nginx/html/
COPY landing/fonts/ /usr/share/nginx/html/fonts/

# ── Pagine di accesso e registrazione dedicate (/accedi/, /registrati/) ──
COPY login.html login.js register.html register.js auth.js auth.css /usr/share/nginx/html/

# ── Dashboard (sotto /app/) ─────────────────────────────────
COPY index.html style.css app.js /usr/share/nginx/html/app/
COPY fonts/ /usr/share/nginx/html/app/fonts/
COPY vendor/ /usr/share/nginx/html/app/vendor/
COPY config.template.js /usr/share/nginx/html/app/config.template.js

# Genera config.js dal template con envsubst. MELPIS_API_BASE vuota (default)
# = same-origin. Non usiamo l'envsubst_template di default perché serve una
# variabile nostra su un file custom.
RUN apk add --no-cache gettext && \
    envsubst '${MELPIS_API_BASE}' < /usr/share/nginx/html/app/config.template.js \
        > /usr/share/nginx/html/app/config.js && \
    rm /usr/share/nginx/html/app/config.template.js && \
    chown -R nginx:nginx /usr/share/nginx/html

# Sostituisce il default.conf dell'immagine base.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/conf.d/security-headers.conf

EXPOSE 80
