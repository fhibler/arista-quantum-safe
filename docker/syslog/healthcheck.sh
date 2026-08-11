#!/bin/sh
# Verify the syslog-ng TLS listener negotiates PQC-hybrid on localhost and mgmt IP.
set -eu

PORT="${SYSLOG_TLS_PORT:-6514}"
PQC_GROUP="${SYSLOG_PQC_GROUP:-X25519MLKEM768}"
OPENSSL_CNF="${OPENSSL_CONF:-/etc/syslog-ng/openssl-pqc.cnf}"

probe_host() {
	host=$1
	output=$(
		OPENSSL_CONF="$OPENSSL_CNF" \
			openssl s_client -connect "${host}:${PORT}" -servername syslog -tls1_3 \
			-groups "$PQC_GROUP" </dev/null 2>&1
	) || true
	echo "$output" | grep -q "Negotiated TLS1.3 group: ${PQC_GROUP}"
}

hosts="127.0.0.1"
mgmt_ip=$(ip -4 -o addr show eth0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
if [ -n "$mgmt_ip" ] && [ "$mgmt_ip" != "127.0.0.1" ]; then
	hosts="$hosts $mgmt_ip"
fi

for host in $hosts; do
	probe_host "$host" || exit 1
done
