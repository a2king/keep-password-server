#!/bin/sh
# 根据 deploy/domains.env 生成 Caddy 配置。官网和 API 分站点，列表里的主机同时生效。
set -eu

csv_list() {
  printf '%s' "$1" | awk -F',' '{
    out = ""
    for (i = 1; i <= NF; i++) {
      gsub(/^[ \t]+|[ \t]+$/, "", $i)
      if ($i == "") continue
      if (out != "") out = out ", "
      out = out $i
    }
    printf "%s", out
  }'
}

csv_spaces() {
  printf '%s' "$1" | awk -F',' '{
    out = ""
    for (i = 1; i <= NF; i++) {
      gsub(/^[ \t]+|[ \t]+$/, "", $i)
      if ($i == "") continue
      if (out != "") out = out " "
      out = out $i
    }
    printf "%s", out
  }'
}

SITE=$(csv_list "${SITE_HOSTS:-localhost}")
API=$(csv_list "${API_HOSTS:-}")
CANONICAL=$(printf '%s' "${CANONICAL_HOST:-}" | awk '{gsub(/^[ \t]+|[ \t]+$/, "", $0); print}')
APEX=$(csv_spaces "${APEX_HOSTS:-}")
REDIRECT=$(printf '%s' "${REDIRECT_TO_CANONICAL:-false}" | tr '[:upper:]' '[:lower:]')

if [ -z "$SITE" ]; then
  echo "SITE_HOSTS 为空" >&2
  exit 1
fi

OUT=/tmp/Caddyfile
{
  echo "$SITE {"
  echo "	encode gzip"
  if [ "$REDIRECT" = "true" ] || [ "$REDIRECT" = "1" ] || [ "$REDIRECT" = "yes" ] || [ "$REDIRECT" = "on" ]; then
    if [ -z "$CANONICAL" ]; then
      echo "REDIRECT_TO_CANONICAL 需要同时设置 CANONICAL_HOST" >&2
      exit 1
    fi
    echo "	@elsewhere not host $CANONICAL"
    echo "	redir @elsewhere https://$CANONICAL{uri} permanent"
  elif [ -n "$APEX" ]; then
    echo "	@apex host $APEX"
    echo "	redir @apex https://www.{http.request.host}{uri} permanent"
  fi
  echo "	handle /api/* {"
  echo "		reverse_proxy api:8000"
  echo "	}"
  echo "	handle /downloads/* {"
  echo "		reverse_proxy api:8000"
  echo "	}"
  echo "	handle {"
  echo "		root * /srv/www"
  echo "		try_files {path} /index.html"
  echo "		file_server"
  echo "	}"
  echo "}"
  if [ -n "$API" ]; then
    echo ""
    echo "$API {"
    echo "	encode gzip"
    echo "	reverse_proxy api:8000"
    echo "}"
  fi
} > "$OUT"

exec caddy run --config "$OUT" --adapter caddyfile
