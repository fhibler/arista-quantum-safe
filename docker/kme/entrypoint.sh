#!/bin/sh
set -eu

PORT="${PORT:-8010}"
export OTHER_KMES="${OTHER_KMES:-}"

_allow_sae_client() {
    client="$1"
    if [ -n "$client" ]; then
        iptables -I INPUT -p tcp --dport "${PORT}" -s "${client}" -j ACCEPT
        echo "KME SAE API (tcp/${PORT}) allowed from SAE client at ${client}"
    fi
}

if iptables -A INPUT -p tcp --dport "${PORT}" -j DROP 2>/dev/null; then
    if [ -n "${SAE_CLIENT_IPS:-}" ]; then
        for client in $(echo "${SAE_CLIENT_IPS}" | tr ',' '\n'); do
            _allow_sae_client "$client"
        done
    elif [ -n "${SAE_CLIENT_IP:-}" ]; then
        _allow_sae_client "${SAE_CLIENT_IP}"
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
