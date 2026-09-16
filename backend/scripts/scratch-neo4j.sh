#!/usr/bin/env bash
# A throwaway Neo4j for the test suite, for anyone running Neo4j from a
# tarball rather than Docker.
#
#   ./scripts/scratch-neo4j.sh start
#   NEO4J_TEST_URI=bolt://localhost:7688 pytest
#   ./scripts/scratch-neo4j.sh stop
#
# Why this exists: Neo4j Community serves exactly one database per instance,
# so isolating the tests means a second *instance*, not a second database
# name. Without one, pytest wipes the graph the application is using - which
# is what the guard in tests/conftest.py now refuses to let happen.
#
# The instance reuses the lib and plugins of an existing install and keeps its
# own data directory under /tmp, so it costs no disk beyond what a run puts in
# it and disappears on reboot. Auth is off: it listens on loopback only and
# holds nothing but test fixtures.
set -euo pipefail

PORT_BOLT=${SCRATCH_BOLT_PORT:-7688}
PORT_HTTP=${SCRATCH_HTTP_PORT:-7475}
HOME_DIR=${SCRATCH_NEO4J_HOME:-/tmp/omnicient-scratch-neo4j}

# The install to borrow lib/ and plugins/ from.
SOURCE=${NEO4J_INSTALL:-}
if [[ -z "$SOURCE" ]]; then
    SOURCE=$(ls -d "$HOME"/.local/opt/neo4j-community-* 2>/dev/null | sort -V | tail -1 || true)
fi
if [[ -z "$SOURCE" || ! -d "$SOURCE/lib" ]]; then
    echo "No Neo4j install found. Set NEO4J_INSTALL to one, or use Docker:" >&2
    echo "  docker compose --profile test up -d neo4j-test" >&2
    exit 1
fi

start() {
    if [[ ! -d "$HOME_DIR/conf" ]]; then
        mkdir -p "$HOME_DIR"/{conf,data,logs,run,import,licenses}
        for part in lib plugins bin; do
            ln -sfn "$SOURCE/$part" "$HOME_DIR/$part"
        done
        cat > "$HOME_DIR/conf/neo4j.conf" <<CONF
server.default_listen_address=127.0.0.1
server.bolt.listen_address=:$PORT_BOLT
server.http.listen_address=:$PORT_HTTP
server.https.enabled=false
server.memory.heap.max_size=512m
server.memory.pagecache.size=256m
dbms.security.auth_enabled=false
CONF
    fi

    NEO4J_HOME="$HOME_DIR" NEO4J_CONF="$HOME_DIR/conf" "$HOME_DIR/bin/neo4j" start

    echo -n "waiting for bolt on $PORT_BOLT"
    for _ in $(seq 1 45); do
        if (echo > "/dev/tcp/127.0.0.1/$PORT_BOLT") 2>/dev/null; then
            echo " - ready"
            echo
            echo "  cd backend && NEO4J_TEST_URI=bolt://localhost:$PORT_BOLT pytest"
            return 0
        fi
        echo -n .
        sleep 2
    done
    echo " - timed out; see $HOME_DIR/logs/neo4j.log" >&2
    exit 1
}

case "${1:-start}" in
    start) start ;;
    stop)  NEO4J_HOME="$HOME_DIR" NEO4J_CONF="$HOME_DIR/conf" "$HOME_DIR/bin/neo4j" stop ;;
    clean) NEO4J_HOME="$HOME_DIR" NEO4J_CONF="$HOME_DIR/conf" "$HOME_DIR/bin/neo4j" stop 2>/dev/null || true
           rm -rf "$HOME_DIR"; echo "removed $HOME_DIR" ;;
    *)     echo "usage: $0 {start|stop|clean}" >&2; exit 2 ;;
esac
