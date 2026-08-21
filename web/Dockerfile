# syntax=docker/dockerfile:1

# Frontend statico (task18 Fase 4): nginx serve i file su un dominio dedicato.
# Build context: web/  (es. docker build -f web/Dockerfile web/)
# In produzione il backend è raggiunto same-origin su "/api/*" (via Traefik):
# MELPIS_API_BASE resta vuota -> niente CORS, cookie same-site.
# Per l'envsubst serve gettext nel builder; l'entrypoint ufficiale nginx
# esegue gli script in /docker-entrypoint.d/ prima di avviare il daemon.

FROM nginx:1.27-alpine AS runtime

# Copia SOLO i file statici serviti. Mai COPY . : nginx.conf, Dockerfile e
# eventuali asset "landing" non devono finire nel docroot scaricabile.
COPY index.html style.css app.js /usr/share/nginx/html/
COPY config.template.js /usr/share/nginx/html/config.template.js

# Genera config.js dal template con envsubst. MELPIS_API_BASE vuota (default)
# = same-origin. Non usiamo l'envsubst_template di default perché serve una
# variabile nostra su un file custom.
RUN apk add --no-cache gettext && \
    envsubst '${MELPIS_API_BASE}' < /usr/share/nginx/html/config.template.js \
        > /usr/share/nginx/html/config.js && \
    rm /usr/share/nginx/html/config.template.js && \
    chown -R nginx:nginx /usr/share/nginx/html

# Sostituisce il default.conf dell'immagine base (che servirebbe
# server_name localhost e maschererebbe la nostra config per il dominio reale).
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/conf.d/security-headers.conf

EXPOSE 80