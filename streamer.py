#!/usr/bin/env python3
"""
streamer.py — Moteur de stream 24/7 basé sur FFmpeg
Surveille un dossier, construit une playlist et stream en continu via RTMP.
"""

import os
import sys
import time
import random
import logging
import logging.handlers
import subprocess
import signal
import tomllib
from pathlib import Path


# ─── Constantes ──────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.toml"


# ─── Chargement de la configuration ──────────────────────────────────────────

def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


# ─── Logging ─────────────────────────────────────────────────────────────────

def setup_logging(cfg: dict) -> logging.Logger:
    log_cfg   = cfg["logging"]
    level     = getattr(logging, log_cfg["level"].upper(), logging.INFO)
    log_file  = log_cfg.get("log_file", "").strip()
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger("streamer")
    logger.setLevel(level)

    # Handler console
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    # Handler fichier avec rotation
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        max_bytes = log_cfg.get("max_log_size_mb", 50) * 1024 * 1024
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=log_cfg.get("backup_count", 5),
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


# ─── Gestion des vidéos ───────────────────────────────────────────────────────

def scan_videos(videos_dir: str, extensions: list[str]) -> list[Path]:
    """Scanne le dossier et retourne la liste des fichiers vidéo trouvés."""
    exts = {f".{e.lower().strip('.')}" for e in extensions}
    videos = sorted(
        p for p in Path(videos_dir).rglob("*")
        if p.is_file() and p.suffix.lower() in exts
    )
    return videos


def build_playlist(videos: list[Path], order: str) -> list[Path]:
    """Retourne la liste ordonnée selon la configuration."""
    if order == "shuffle":
        playlist = videos.copy()
        random.shuffle(playlist)
        return playlist
    return list(videos)  # sequential


# ─── Construction de la commande FFmpeg ──────────────────────────────────────

def build_ffmpeg_cmd(video_path: Path, cfg: dict) -> list[str]:
    vc   = cfg["video"]
    ac   = cfg["audio"]
    rtmp = cfg["stream"]["rtmp_url"]

    gop = vc["keyframe_interval"] * vc["fps"]  # keyframe interval en frames

    cmd = [
        "ffmpeg",
        "-loglevel", "warning",
        "-re",                          # lecture en temps réel
        "-i", str(video_path),          # fichier source

        # Vidéo
        "-c:v",        vc["video_codec"],
        "-preset",     vc["preset"],
        "-profile:v",  vc["profile"],
        "-b:v",        vc["video_bitrate"],
        "-maxrate",    vc["video_bitrate"],
        "-bufsize",    str(int(vc["video_bitrate"].rstrip("k")) * 2) + "k",
        "-vf",         f"scale={vc['width']}:{vc['height']}:force_original_aspect_ratio=decrease,"
                       f"pad={vc['width']}:{vc['height']}:(ow-iw)/2:(oh-ih)/2,"
                       f"fps={vc['fps']}",
        "-g",          str(gop),
        "-keyint_min", str(gop),
        "-sc_threshold", "0",

        # Audio
        "-c:a",        ac["audio_codec"],
        "-b:a",        ac["audio_bitrate"],
        "-ar",         str(ac["sample_rate"]),
        "-ac",         str(ac["channels"]),

        # Sortie RTMP
        "-f",   "flv",
        rtmp,
    ]
    return cmd


# ─── Gestion du signal d'arrêt ───────────────────────────────────────────────

class GracefulShutdown:
    def __init__(self, logger: logging.Logger):
        self.running = True
        self.current_process: subprocess.Popen | None = None
        self.logger = logger
        signal.signal(signal.SIGTERM, self._handle)
        signal.signal(signal.SIGINT,  self._handle)

    def _handle(self, signum, frame):
        self.logger.info(f"Signal {signal.Signals(signum).name} reçu — arrêt propre en cours...")
        self.running = False
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()
            try:
                self.current_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.current_process.kill()


# ─── Boucle principale ────────────────────────────────────────────────────────

def run(cfg: dict, logger: logging.Logger, shutdown: GracefulShutdown):
    stream_cfg   = cfg["stream"]
    behavior_cfg = cfg["behavior"]

    videos_dir      = stream_cfg["videos_dir"]
    extensions      = stream_cfg["extensions"]
    order           = stream_cfg["order"]
    reload_on_cycle = behavior_cfg["reload_on_cycle"]
    error_delay     = behavior_cfg["error_retry_delay"]
    empty_delay     = behavior_cfg["empty_dir_retry_delay"]
    max_errors      = behavior_cfg["max_consecutive_errors"]
    long_pause      = behavior_cfg["long_pause_delay"]

    consecutive_errors = 0

    logger.info("=== Streamer 24/7 démarré ===")
    logger.info(f"Dossier vidéos : {videos_dir}")
    logger.info(f"RTMP cible     : {stream_cfg['rtmp_url']}")
    logger.info(f"Ordre          : {order}")

    while shutdown.running:
        # ── Scan du dossier ─────────────────────────────────────────────────
        videos = scan_videos(videos_dir, extensions)

        if not videos:
            logger.warning(f"Aucune vidéo trouvée dans '{videos_dir}'. Nouvelle tentative dans {empty_delay}s...")
            time.sleep(empty_delay)
            continue

        playlist = build_playlist(videos, order)
        logger.info(f"Playlist chargée : {len(playlist)} vidéo(s)")

        # ── Parcours de la playlist ──────────────────────────────────────────
        for video in playlist:
            if not shutdown.running:
                break

            logger.info(f"▶  Lecture : {video.name}")
            cmd = build_ffmpeg_cmd(video, cfg)

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                shutdown.current_process = proc

                # Lecture des erreurs FFmpeg en temps réel
                stderr_lines = []
                for line in proc.stderr:
                    line = line.strip()
                    if line:
                        logger.debug(f"[ffmpeg] {line}")
                        stderr_lines.append(line)

                proc.wait()
                return_code = proc.returncode

                if not shutdown.running:
                    break

                if return_code == 0:
                    logger.info(f"✓  Fin normale : {video.name}")
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                    last_err = stderr_lines[-1] if stderr_lines else "(aucun message)"
                    logger.error(
                        f"✗  FFmpeg a quitté avec le code {return_code} "
                        f"sur '{video.name}' | Dernière erreur : {last_err}"
                    )

                    # Pause longue si trop d'erreurs consécutives
                    if max_errors > 0 and consecutive_errors >= max_errors:
                        logger.error(
                            f"{consecutive_errors} erreurs consécutives — "
                            f"pause de {long_pause}s avant de reprendre."
                        )
                        time.sleep(long_pause)
                        consecutive_errors = 0
                        break  # recharge la playlist

                    logger.info(f"Reprise dans {error_delay}s...")
                    time.sleep(error_delay)

            except FileNotFoundError:
                logger.critical("FFmpeg introuvable. Vérifiez qu'il est installé et dans le PATH.")
                shutdown.running = False
                break
            except Exception as e:
                logger.exception(f"Erreur inattendue : {e}")
                time.sleep(error_delay)

        # ── Fin d'un cycle de playlist ───────────────────────────────────────
        if shutdown.running:
            if reload_on_cycle:
                logger.info("Cycle terminé — rechargement de la playlist.")
            else:
                logger.info("Cycle terminé — reprise depuis le début.")

    logger.info("=== Streamer arrêté proprement ===")


# ─── Point d'entrée ───────────────────────────────────────────────────────────

def main():
    if not CONFIG_PATH.exists():
        print(f"[ERREUR] Fichier de configuration introuvable : {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    cfg    = load_config(CONFIG_PATH)
    logger = setup_logging(cfg)

    # Vérification de base
    videos_dir = cfg["stream"]["videos_dir"]
    if not Path(videos_dir).exists():
        logger.warning(f"Le dossier vidéos '{videos_dir}' n'existe pas encore — il sera créé.")
        Path(videos_dir).mkdir(parents=True, exist_ok=True)

    shutdown = GracefulShutdown(logger)
    run(cfg, logger, shutdown)


if __name__ == "__main__":
    main()
