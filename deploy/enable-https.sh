#!/bin/sh
# Run only after the dedicated subdomain points to this ECS. Never edits default.
set -eu
domain=researchtrace.sluna.xyz
python3 - <<'PY'
import socket,sys
try:
    addresses={row[4][0] for row in socket.getaddrinfo('researchtrace.sluna.xyz',80)}
except OSError:
    print('BLOCKED: create DNS A researchtrace -> 118.31.50.2 first')
    sys.exit(2)
if '118.31.50.2' not in addresses:
    print('BLOCKED: the dedicated domain does not point to this ECS')
    sys.exit(2)
PY
certbot certonly --webroot -w /opt/researchtrace/acme -d "$domain" \
    --agree-tos --non-interactive --register-unsafely-without-email \
    --deploy-hook 'systemctl reload nginx'
test -s /etc/letsencrypt/live/researchtrace.sluna.xyz/fullchain.pem
test -s /etc/letsencrypt/live/researchtrace.sluna.xyz/privkey.pem
source_file=/opt/researchtrace/current/deploy/nginx-researchtrace.conf
target=/etc/nginx/sites-available/researchtrace
test -L /etc/nginx/sites-enabled/researchtrace
test "$(readlink -f /etc/nginx/sites-enabled/researchtrace)" = "$target"
cp "$target" /opt/researchtrace/private/nginx-before-https.conf
python3 - "$source_file" "$target" <<'PY'
from pathlib import Path
import sys
source=Path(sys.argv[1]).read_text()
source=source.replace('listen 80;', 'listen 443 ssl;').replace('listen [::]:80;', 'listen [::]:443 ssl;')
source=source.replace('    client_max_body_size', '''    ssl_certificate /etc/letsencrypt/live/researchtrace.sluna.xyz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/researchtrace.sluna.xyz/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size''')
redirect='''server {
    listen 80;
    listen [::]:80;
    server_name researchtrace.sluna.xyz;
    location ^~ /.well-known/acme-challenge/ { root /opt/researchtrace/acme; }
    location / { return 301 https://$host$request_uri; }
}
'''
Path(sys.argv[2]).write_text(redirect+source)
PY
if nginx -t; then
    systemctl reload nginx
else
    cp /opt/researchtrace/private/nginx-before-https.conf "$target"
    exit 1
fi
curl --fail --silent "https://$domain/healthz"
printf '\nTLS health verified from ECS; an external browser check is still required.\n'
