# Streamer 24/7 — Guide d'installation

## Prérequis

```bash
# FFmpeg
sudo apt update && sudo apt install -y ffmpeg python3

# Vérification
ffmpeg -version
python3 --version  # >= 3.11 requis (tomllib inclus)
```

---

## Installation rapide

```bash
# 1. Créer le répertoire et copier les fichiers
sudo mkdir -p /opt/stream/videos
sudo cp streamer.py config.toml stream-manager.sh /opt/stream/

# 2. Rendre le script exécutable
sudo chmod +x /opt/stream/stream-manager.sh

# 3. Créer le dossier de logs
sudo mkdir -p /var/log/streamer

# 4. Adapter la configuration
sudo nano /opt/stream/config.toml
```

---

## Configuration essentielle

Éditez `/opt/stream/config.toml` — les deux champs obligatoires :

```toml
[stream]
rtmp_url   = "rtmp://votre-serveur/live/votre-cle"  # ← votre endpoint RTMP
videos_dir = "/opt/stream/videos"                    # ← votre dossier vidéos
```

---

## Utilisation avec stream-manager.sh

```bash
cd /opt/stream

./stream-manager.sh start    # Démarre en arrière-plan
./stream-manager.sh stop     # Arrête proprement
./stream-manager.sh restart  # Redémarre
./stream-manager.sh status   # État + vidéo en cours
./stream-manager.sh tail     # Logs en temps réel
./stream-manager.sh logs     # Historique complet (less)
```

---

## Service systemd (recommandé pour la production)

```bash
# Créer un utilisateur dédié
sudo useradd -r -s /bin/false streamer
sudo chown -R streamer:streamer /opt/stream /var/log/streamer

# Installer le service
sudo cp streamer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable streamer   # démarrage automatique au boot
sudo systemctl start streamer

# Commandes utiles
sudo systemctl status streamer
sudo journalctl -u streamer -f   # logs en temps réel via journald
```

---

## Gestion des vidéos

Déposez simplement vos fichiers dans le dossier configuré :

```
/opt/stream/videos/
├── intro.mp4
├── episode-01.mp4
├── episode-02.mkv
└── ...
```

- Les vidéos sont lues **dans l'ordre alphabétique** (`order = "sequential"`).
- Pour un ordre aléatoire, changez en `order = "shuffle"` dans `config.toml`.
- Le dossier est **re-scanné à chaque fin de cycle** : ajoutez ou supprimez des fichiers à chaud, sans redémarrer.
- Les vidéos sont automatiquement **redimensionnées et recadrées** (letterbox/pillarbox) à la résolution configurée.

---

## Accélération GPU (optionnel)

Pour réduire la charge CPU, activez l'encodage matériel dans `config.toml` :

```toml
[video]
# NVIDIA (NVENC)
video_codec = "h264_nvenc"
preset      = "p4"           # p1 (rapide) → p7 (qualité max)

# AMD / Intel (VAAPI — Linux)
video_codec = "h264_vaapi"
preset      = "veryfast"
```

> Vérifiez la disponibilité : `ffmpeg -encoders | grep nvenc` ou `| grep vaapi`

---

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `FFmpeg introuvable` | FFmpeg non installé | `sudo apt install ffmpeg` |
| Erreur code `-9` | Mémoire insuffisante | Réduire le bitrate ou le preset |
| Stream qui coupe | Réseau instable | Vérifier la bande passante uplink |
| Vidéo ignorée | Format non supporté | Ajouter l'extension dans `config.toml` → `extensions` |
| Aucun son | Audio manquant dans la source | Ajouter `-f lavfi -i anullsrc` (voir FFmpeg docs) |
