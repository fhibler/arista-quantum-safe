#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
	exec "$@"
fi

SYSLOG_NG=/opt/syslog-ng/sbin/syslog-ng
CONF=/etc/syslog-ng/syslog-ng.conf
CERT_DIR=/etc/syslog-ng/certs
HEALTHCHECK=/usr/local/bin/syslog-healthcheck.sh
CERT_WAIT_SEC="${SYSLOG_CERT_WAIT_SEC:-60}"
NET_WAIT_SEC="${SYSLOG_NET_WAIT_SEC:-60}"
READY_WAIT_SEC="${SYSLOG_READY_WAIT_SEC:-60}"
READY_STREAK="${SYSLOG_READY_STREAK:-3}"
MAX_ATTEMPTS="${SYSLOG_START_ATTEMPTS:-3}"
WATCH_INTERVAL="${SYSLOG_WATCH_INTERVAL:-10}"

wait_for_nonempty_file() {
	path=$1
	deadline=$(( $(date +%s) + CERT_WAIT_SEC ))
	while [ ! -s "$path" ]; do
		if [ "$(date +%s)" -ge "$deadline" ]; then
			echo "syslog: timed out waiting for ${path}" >&2
			return 1
		fi
		sleep 1
	done
}

wait_for_network() {
	deadline=$(( $(date +%s) + NET_WAIT_SEC ))
	while [ "$(date +%s)" -lt "$deadline" ]; do
		if ip link show eth0 2>/dev/null | grep -q 'state UP' \
			&& ip -4 addr show eth0 2>/dev/null | grep -q 'inet '; then
			# containerlab may still be reconfiguring the iface after the first address.
			sleep 2
			return 0
		fi
		sleep 1
	done
	echo "syslog: timed out waiting for eth0 management address" >&2
	return 1
}

wait_for_tls_streak() {
	pid=$1
	streak=0
	deadline=$(( $(date +%s) + READY_WAIT_SEC ))
	while [ "$(date +%s)" -lt "$deadline" ]; do
		if ! kill -0 "$pid" 2>/dev/null; then
			echo "syslog: syslog-ng exited before TLS became ready" >&2
			wait "$pid" 2>/dev/null || true
			return 1
		fi
		if "$HEALTHCHECK"; then
			streak=$((streak + 1))
			if [ "$streak" -ge "$READY_STREAK" ]; then
				return 0
			fi
		else
			streak=0
		fi
		sleep 1
	done
	echo "syslog: TLS readiness probe timed out after ${READY_WAIT_SEC}s" >&2
	return 1
}

start_syslog() {
	wait_for_network
	"$SYSLOG_NG" -F -f "$CONF" &
	echo $!
}

for name in server.pem server.key ca.pem; do
	wait_for_nonempty_file "${CERT_DIR}/${name}"
done

"$SYSLOG_NG" -s -f "$CONF"

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
	pid=$(start_syslog)
	if wait_for_tls_streak "$pid"; then
		echo "syslog: TLS listener ready on :${SYSLOG_TLS_PORT:-6514} (${SYSLOG_PQC_GROUP:-X25519MLKEM768})"
		trap 'kill -TERM "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; exit 143' TERM INT
		while kill -0 "$pid" 2>/dev/null; do
			sleep "$WATCH_INTERVAL"
			if "$HEALTHCHECK"; then
				continue
			fi
			echo "syslog: TLS probe failed, restarting syslog-ng" >&2
			kill -TERM "$pid" 2>/dev/null || true
			wait "$pid" 2>/dev/null || true
			pid=$(start_syslog)
			if ! wait_for_tls_streak "$pid"; then
				break
			fi
			echo "syslog: TLS listener recovered on :${SYSLOG_TLS_PORT:-6514}"
		done
		wait "$pid" 2>/dev/null || true
		exit 0
	fi
	kill -TERM "$pid" 2>/dev/null || true
	wait "$pid" 2>/dev/null || true
	echo "syslog: startup attempt ${attempt}/${MAX_ATTEMPTS} failed" >&2
	attempt=$((attempt + 1))
	sleep 2
done

echo "syslog: TLS listener failed readiness checks" >&2
exit 1
