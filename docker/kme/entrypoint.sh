#!/bin/sh
set -eu

PORT="${PORT:-8010}"
export OTHER_KMES="${OTHER_KMES:-}"

_is_ipv6() {
    case "$1" in
        *:*) return 0 ;;
        *) return 1 ;;
    esac
}

_firewall_table() {
    if _is_ipv6 "$1"; then
        echo ip6tables
    else
        echo iptables
    fi
}

_allow_source() {
    source="$1"
    role="$2"
    table=$(_firewall_table "$source")
    if [ -n "$source" ]; then
        "$table" -I INPUT -p tcp --dport "${PORT}" -s "${source}" -j ACCEPT
        echo "KME ${role} (tcp/${PORT}) allowed from ${source}"
    fi
}

_wants_v4=false
_wants_v6=false

_note_source() {
    source="$1"
    [ -n "$source" ] || return 0
    if _is_ipv6 "$source"; then
        _wants_v6=true
    else
        _wants_v4=true
    fi
}

if [ -n "${SAE_CLIENT_IPS:-}" ]; then
    for client in $(echo "${SAE_CLIENT_IPS}" | tr ',' '\n'); do
        _note_source "$(echo "$client" | tr -d ' ')"
    done
elif [ -n "${SAE_CLIENT_IP:-}" ]; then
    _note_source "${SAE_CLIENT_IP}"
fi

if [ -n "${OTHER_KMES}" ]; then
    for peer in $(echo "${OTHER_KMES}" | tr ',' '\n'); do
        peer_host=$(echo "$peer" | sed -E 's|https?://([^:/]+).*|\1|')
        _note_source "$peer_host"
    done
fi

_restrict_family() {
    table="$1"
    if ! "$table" -A INPUT -p tcp --dport "${PORT}" -j DROP 2>/dev/null; then
        echo "warning: ${table} restriction skipped (grant NET_ADMIN or run as root with ${table})"
        return 1
    fi
    echo "KME API (tcp/${PORT}) restricted to explicit allowlist (${table})"
    return 0
}

if [ "$_wants_v4" = true ]; then
    _restrict_family iptables || _wants_v4=false
fi
if [ "$_wants_v6" = true ]; then
    _restrict_family ip6tables || _wants_v6=false
fi

if [ -n "${SAE_CLIENT_IPS:-}" ]; then
    for client in $(echo "${SAE_CLIENT_IPS}" | tr ',' '\n'); do
        client=$(echo "$client" | tr -d ' ')
        if _is_ipv6 "$client"; then
            [ "$_wants_v6" = true ] && _allow_source "$client" "SAE API"
        else
            [ "$_wants_v4" = true ] && _allow_source "$client" "SAE API"
        fi
    done
elif [ -n "${SAE_CLIENT_IP:-}" ]; then
    if _is_ipv6 "${SAE_CLIENT_IP}"; then
        [ "$_wants_v6" = true ] && _allow_source "${SAE_CLIENT_IP}" "SAE API"
    else
        [ "$_wants_v4" = true ] && _allow_source "${SAE_CLIENT_IP}" "SAE API"
    fi
fi

if [ -n "${OTHER_KMES}" ]; then
    for peer in $(echo "${OTHER_KMES}" | tr ',' '\n'); do
        peer_host=$(echo "$peer" | sed -E 's|https?://([^:/]+).*|\1|')
        if [ -n "$peer_host" ]; then
            if _is_ipv6 "$peer_host"; then
                [ "$_wants_v6" = true ] && _allow_source "$peer_host" "peer API"
            else
                [ "$_wants_v4" = true ] && _allow_source "$peer_host" "peer API"
            fi
        fi
    done
fi

exec python3 /opt/next-door-key-simulator/app.py
