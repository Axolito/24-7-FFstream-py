#!/usr/bin/env bash
# ============================================================
#  stream-manager.sh — Gestion du streamer 24/7
#  Usage : ./stream-manager.sh {start|stop|restart|status|logs|tail}
# ============================================================

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
STREAMER_SCRIPT="$SCRIPT_DIR/streamer.py"
PID_FILE="/var/run/streamer.pid"
LOG_FILE="/var/log/streamer/streamer.log"
SERVICE_NAME="streamer"

# Couleurs
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# ─── Helpers ──────────────────────────────────────────────────────────────────
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR]${NC}   $*" >&2; }

is_running() {
    [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

get_pid() {
    cat "$PID_FILE" 2>/dev/null || echo "N/A"
}

# ─── Commandes ────────────────────────────────────────────────────────────────

cmd_start() {
    if is_running; then
        warn "Le streamer tourne déjà (PID $(get_pid))."
        return 0
    fi

    info "Démarrage du streamer..."
    mkdir -p "$(dirname "$LOG_FILE")"
    mkdir -p "$(dirname "$PID_FILE")"

    nohup "$PYTHON_BIN" -u "$STREAMER_SCRIPT" \
        >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    sleep 1
    if is_running; then
        success "Streamer démarré (PID $(get_pid))."
    else
        error "Le streamer n'a pas pu démarrer. Consultez les logs : $LOG_FILE"
        return 1
    fi
}

cmd_stop() {
    if ! is_running; then
        warn "Le streamer n'est pas en cours d'exécution."
        return 0
    fi

    local pid
    pid=$(get_pid)
    info "Arrêt du streamer (PID $pid)..."
    kill -TERM "$pid"

    local timeout=15
    while is_running && (( timeout-- > 0 )); do
        sleep 1
    done

    if is_running; then
        warn "Arrêt forcé (SIGKILL)..."
        kill -KILL "$pid" 2>/dev/null || true
    fi

    rm -f "$PID_FILE"
    success "Streamer arrêté."
}

cmd_restart() {
    info "Redémarrage du streamer..."
    cmd_stop
    sleep 2
    cmd_start
}

cmd_status() {
    echo -e "\n${BOLD}══ Statut du streamer ══${NC}"
    if is_running; then
        local pid
        pid=$(get_pid)
        echo -e "  État  : ${GREEN}● En cours${NC} (PID $pid)"
        echo -e "  Uptime: $(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')"

        # Affiche la vidéo en cours de lecture via le process FFmpeg enfant
        local ffmpeg_pid
        ffmpeg_pid=$(pgrep -P "$pid" ffmpeg 2>/dev/null | head -1 || true)
        if [[ -n "$ffmpeg_pid" ]]; then
            local video
            video=$(ps -p "$ffmpeg_pid" -o args= 2>/dev/null | grep -oP '(?<=-i )\S+' || true)
            echo -e "  Vidéo : ${CYAN}$(basename "${video:-inconnu}")${NC}"
        fi
    else
        echo -e "  État  : ${RED}● Arrêté${NC}"
    fi

    echo -e "  Logs  : $LOG_FILE"
    echo ""
}

cmd_logs() {
    if [[ ! -f "$LOG_FILE" ]]; then
        warn "Aucun fichier de log trouvé : $LOG_FILE"
        return 1
    fi
    less +G "$LOG_FILE"
}

cmd_tail() {
    if [[ ! -f "$LOG_FILE" ]]; then
        warn "Aucun fichier de log trouvé : $LOG_FILE"
        return 1
    fi
    info "Affichage en direct des logs (Ctrl+C pour quitter)..."
    tail -f "$LOG_FILE"
}

cmd_help() {
    echo -e "\n${BOLD}stream-manager.sh${NC} — Gestion du streamer 24/7\n"
    echo -e "  ${CYAN}start${NC}    Démarre le streamer en arrière-plan"
    echo -e "  ${CYAN}stop${NC}     Arrête le streamer proprement"
    echo -e "  ${CYAN}restart${NC}  Redémarre le streamer"
    echo -e "  ${CYAN}status${NC}   Affiche l'état actuel et la vidéo en cours"
    echo -e "  ${CYAN}logs${NC}     Ouvre les logs complets (less)"
    echo -e "  ${CYAN}tail${NC}     Suit les logs en temps réel (tail -f)"
    echo ""
}

# ─── Dispatch ─────────────────────────────────────────────────────────────────

case "${1:-help}" in
    start)   cmd_start   ;;
    stop)    cmd_stop    ;;
    restart) cmd_restart ;;
    status)  cmd_status  ;;
    logs)    cmd_logs    ;;
    tail)    cmd_tail    ;;
    *)       cmd_help    ;;
esac
