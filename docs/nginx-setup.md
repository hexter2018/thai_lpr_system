# Nginx reverse proxy for Vite + API (10.32.70.136)

This guide configures nginx on port 80 to proxy:

- `/` → `http://127.0.0.1:5173` (Vite dev server + HMR websocket)
- `/api/` → `http://127.0.0.1:8000` (backend API, keeps `/api` prefix)

## Install nginx (if missing)

```bash
sudo apt-get update
sudo apt-get install -y nginx
```

## Create the site config

```bash
sudo tee /etc/nginx/sites-available/app > /dev/null <<'EOF'
map $http_upgrade $connection_upgrade {
  default upgrade;
  ''      close;
}

server {
  listen 80;
  server_name 10.32.70.136 _;

  client_max_body_size 50m;

  # API - keep /api prefix (no trailing slash in proxy_pass)
  location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    proxy_connect_timeout 60s;
    proxy_buffering off;
  }

  # Frontend + Vite HMR websocket
  location / {
    proxy_pass http://127.0.0.1:5173;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    proxy_connect_timeout 60s;
    proxy_buffering off;
  }
}
EOF
```

## Enable the site and disable default if needed

```bash
sudo ln -sfn /etc/nginx/sites-available/app /etc/nginx/sites-enabled/app
sudo rm -f /etc/nginx/sites-enabled/default
```

## Validate and reload

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## Verification

```bash
curl -i http://10.32.70.136/
curl -i http://10.32.70.136/api/dashboard/kpi
```

### Logs and common pitfalls

- Logs:
  - Access log: `/var/log/nginx/access.log`
  - Error log: `/var/log/nginx/error.log`
- If `/api` drops the prefix, ensure the `proxy_pass` for `/api/` has **no trailing slash**.
- If HMR fails:
  - Confirm websocket headers are set and `proxy_http_version 1.1` is present.
  - Ensure `map $http_upgrade $connection_upgrade` exists at http context.

## Vite HMR settings behind nginx

When the browser loads from `http://10.32.70.136` (port 80), set Vite HMR to use
port 80 and the external host:

```ts
// vite.config.ts
export default defineConfig({
  server: {
    hmr: {
      host: "10.32.70.136",
      clientPort: 80,
    },
  },
});
```
