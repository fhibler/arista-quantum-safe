#!/bin/sh
set -eu

PORT="${PORT:-8010}"
export OTHER_KMES="${OTHER_KMES:-}"

if iptables -A INPUT -p tcp --dport "${PORT}" -j DROP 2>/dev/null; then
    if [ -n "${RADIUS_IP:-}" ]; then
        iptables -I INPUT -p tcp --dport "${PORT}" -s "${RADIUS_IP}" -j ACCEPT
        echo "KME SAE API (tcp/${PORT}) allowed from RADIUS at ${RADIUS_IP}"
    fi

    if [ -n "${OTHER_KMES}" ]; then
        for peer in $(echo "${OTHER_KMES}" | tr ',' '\n'); do
            peer_host=$(echo "$peer" | sed -E 's|https?://([^:/]+).*|\1|')
            if [ -n "$peer_host" ]; then
                iptables -I INPUT -p tcp --dport "${PORT}" -s "$peer_host" -j ACCEPT
                echo "KME peer API (tcp/${PORT}) allowed from ${peer_host}"
            fi
        done
    fi

    echo "KME API (tcp/${PORT}) restricted to explicit allowlist"
else
    echo "warning: iptables restriction skipped (grant NET_ADMIN or run as root with iptables)"
fi

exec python3 /opt/next-door-key-simulator/app.py
