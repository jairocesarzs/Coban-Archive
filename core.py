"""Lógica do Coban Archive: constantes, scanners, workers, cache de miniaturas e a janela (sem layout)."""

import os
import json
import base64
import hashlib
import logging
import random
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QStyle
)
from PySide6.QtCore import (
    QByteArray, QFileSystemWatcher, QObject, QRunnable, QSize, QStandardPaths, Qt,
    QThread, QThreadPool, QTimer, QUrl, Signal
)
from PySide6.QtGui import (
    QCursor, QDesktopServices, QIcon, QImage, QImageReader, QPixmap
)
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

from library_db import LibraryDB

try:
    import mutagen
    from mutagen.id3 import ID3
    from mutagen.flac import FLAC, Picture
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

log = logging.getLogger(__name__)

APP_VERSION = "1.1.2"
GITHUB_URL = "https://github.com/jairocesarzs/Coban-Archive"
APP_DESCRIPTION = (
    "Gerenciador de biblioteca de músicas, CDs, vídeos, jogos e galeria de fotos."
)

AUDIO_EXTS = ('.mp3', '.ogg', '.m4a', '.wav', '.flac')
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp')
VIDEO_EXTS = (
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v",
    ".mpeg", ".mpg", ".ts", ".rm", ".rmvb", ".ram", ".rv",
    ".flv", ".3gp", ".vob", ".ogv", ".divx",
)
GAME_EXTS = ('.gba', '.ciso')

REPEAT_MODES = ("off", "all", "one")


def _first_tag(audio, key, default):
    val = audio.get(key)
    if val is None:
        return default
    if isinstance(val, list):
        return val[0] if val else default
    return val


class ScannerThread(QThread):
    finished_scan = Signal(list)

    def __init__(self, folders, exts, check_mtime=False, db=None, kind=None, extract_tags=False):
        super().__init__()
        self.folders = folders if isinstance(folders, list) else [folders]
        self.exts = exts
        self.check_mtime = check_mtime
        self.db = db
        self.kind = kind
        self.extract_tags = extract_tags

    def run(self):
        try:
            if self.db and self.db.is_ready() and self.kind:
                results = self._cached_scan()
            else:
                results = self._full_scan()
            if not self.isInterruptionRequested():
                self.finished_scan.emit(results)
        except Exception:
            log.exception("Erro no scanner de %s", self.kind)
            self.finished_scan.emit([])

    def _full_scan(self):
        results = []
        for folder in self.folders:
            if self.isInterruptionRequested():
                return []
            if not folder or not os.path.exists(folder):
                continue
            for root, dirs, files in os.walk(folder):
                if self.isInterruptionRequested():
                    return []
                dirs[:] = [d for d in dirs if d.lower() not in {
                    ".git", "__pycache__", ".cache", "node_modules",
                    "$recycle.bin", "system volume information",
                }]
                for f in files:
                    if f.lower().endswith(self.exts):
                        path = os.path.join(root, f)
                        if self.check_mtime:
                            try:
                                mtime = os.path.getmtime(path)
                            except OSError:
                                mtime = 0
                            results.append((mtime, path))
                        else:
                            results.append(path)
        if self.check_mtime:
            results.sort(key=lambda x: x[0], reverse=True)
        else:
            results.sort(key=lambda x: os.path.basename(x).casefold())
        return results

    def _cached_scan(self):
        existing = self._load_existing()
        current = {}
        for folder in self.folders:
            if self.isInterruptionRequested():
                return []
            if not folder or not os.path.exists(folder):
                continue
            for root, dirs, files in os.walk(folder):
                if self.isInterruptionRequested():
                    return []
                dirs[:] = [d for d in dirs if d.lower() not in {
                    ".git", "__pycache__", ".cache", "node_modules",
                    "$recycle.bin", "system volume information",
                }]
                for f in files:
                    if f.lower().endswith(self.exts):
                        path = os.path.join(root, f)
                        try:
                            st = os.stat(path)
                        except OSError:
                            continue
                        current[path] = {
                            "path": path, "folder": root, "filename": f,
                            "mtime": st.st_mtime, "size": st.st_size,
                        }
        updates = []
        for path, info in current.items():
            old = existing.get(path)
            if (old is None or old["mtime"] != info["mtime"]
                    or old["size"] != info["size"]):
                row = dict(info)
                if self.extract_tags:
                    row.update(self._extract_tags(path))
                updates.append(row)
        removed = [p for p in existing if p not in current]
        if updates:
            self._upsert(updates)
        if removed:
            self._delete(removed)
        if updates or removed or existing:
            self.db.record_scan(self.kind, self.folders)
        paths = list(current.keys())
        if self.check_mtime:
            out = [(current[p]["mtime"], p) for p in paths]
            out.sort(key=lambda x: x[0], reverse=True)
            return out
        paths.sort(key=lambda x: os.path.basename(x).casefold())
        return paths

    def _load_existing(self):
        return {
            "tracks": self.db.existing_tracks,
            "videos": self.db.existing_videos,
            "games":  self.db.existing_games,
            "images": self.db.existing_images,
        }[self.kind](self.folders)

    def _upsert(self, rows):
        {
            "tracks": self.db.upsert_tracks,
            "videos": self.db.upsert_videos,
            "games":  self.db.upsert_games,
            "images": self.db.upsert_images,
        }[self.kind](rows)

    def _delete(self, paths):
        {
            "tracks": self.db.delete_tracks,
            "videos": self.db.delete_videos,
            "games":  self.db.delete_games,
            "images": self.db.delete_images,
        }[self.kind](paths)

    def _extract_tags(self, path):
        result = {"title": None, "artist": None, "album": None,
                  "search_text": os.path.basename(path).lower()}
        if not MUTAGEN_AVAILABLE:
            return result
        try:
            audio = mutagen.File(path, easy=True)
            if not audio:
                return result
            parts = [os.path.basename(path).lower()]
            for tag in ("title", "artist", "album"):
                val = audio.get(tag)
                if not val:
                    continue
                v = val[0] if isinstance(val, list) else val
                v = str(v)
                result[tag] = v
                parts.append(v.lower())
            result["search_text"] = " ".join(parts)
        except Exception:
            pass
        return result


class CDScannerThread(QThread):
    finished_scan = Signal(list)

    def __init__(self, folders, db=None):
        super().__init__()
        self.folders = folders
        self.db = db

    def run(self):
        try:
            if self.db and self.db.is_ready():
                results = self._cached_scan()
            else:
                results = self._full_scan()
            if not self.isInterruptionRequested():
                self.finished_scan.emit(results)
        except Exception:
            log.exception("Erro no scanner de CDs")
            self.finished_scan.emit([])

    def _full_scan(self):
        albums = []
        for folder in self.folders:
            if self.isInterruptionRequested():
                return []
            if not folder or not os.path.exists(folder):
                continue
            for root, dirs, files in os.walk(folder):
                if self.isInterruptionRequested():
                    return []
                dirs[:] = [d for d in dirs if d.lower() not in
                           (".git", "__pycache__", "node_modules", "$recycle.bin")]
                audio = sorted([f for f in files if f.lower().endswith(AUDIO_EXTS)])
                if audio:
                    album_name = os.path.basename(root) or os.path.basename(folder)
                    albums.append((root, album_name, os.path.join(root, audio[0])))
        albums.sort(key=lambda x: x[1].casefold())
        return albums

    def _cached_scan(self):
        existing = self.db.existing_albums(self.folders)
        current = {}
        for folder in self.folders:
            if self.isInterruptionRequested():
                return []
            if not folder or not os.path.exists(folder):
                continue
            for root, dirs, files in os.walk(folder):
                if self.isInterruptionRequested():
                    return []
                dirs[:] = [d for d in dirs if d.lower() not in
                           (".git", "__pycache__", "node_modules", "$recycle.bin")]
                audio = sorted([f for f in files if f.lower().endswith(AUDIO_EXTS)])
                if not audio:
                    continue
                album_name = os.path.basename(root) or os.path.basename(folder)
                first = os.path.join(root, audio[0])
                try:
                    fm = os.path.getmtime(root)
                except OSError:
                    fm = 0
                try:
                    am = os.path.getmtime(first)
                except OSError:
                    am = 0
                current[root] = {
                    "folder": root, "name": album_name,
                    "first_audio": first, "mtime": max(fm, am),
                }
        updates = []
        for path, info in current.items():
            old = existing.get(path)
            if (old is None or old["mtime"] != info["mtime"]
                    or old["name"] != info["name"]
                    or old["first_audio"] != info["first_audio"]):
                updates.append(info)
        removed = [p for p in existing if p not in current]
        if updates:
            self.db.upsert_albums(updates)
        if removed:
            self.db.delete_albums(removed)
        if updates or removed or existing:
            self.db.record_scan("albums", self.folders)
        results = [(f, i["name"], i["first_audio"]) for f, i in current.items()]
        results.sort(key=lambda x: x[1].casefold())
        return results


class WorkerSignals(QObject):
    result = Signal(str, QImage)


class ThumbnailCache:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            log.debug("Não foi possível criar cache dir: %s", cache_dir)

    def _key(self, file_path, is_music, size):
        try:
            st = os.stat(file_path)
            mtime = int(st.st_mtime)
            sz = st.st_size
        except OSError:
            return None
        raw = f"{file_path}|{mtime}|{sz}|{is_music}|{size[0]}x{size[1]}"
        return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()

    def get(self, file_path, is_music, size):
        key = self._key(file_path, is_music, size)
        if not key:
            return QImage()
        path = os.path.join(self.cache_dir, f"{key}.png")
        if os.path.exists(path):
            img = QImage(path)
            if not img.isNull():
                return img
        return QImage()

    def put(self, file_path, is_music, size, qimg):
        if qimg.isNull():
            return
        key = self._key(file_path, is_music, size)
        if not key:
            return
        path = os.path.join(self.cache_dir, f"{key}.png")
        try:
            qimg.save(path, "PNG")
        except Exception:
            log.debug("Falha ao salvar thumbnail em cache", exc_info=True)


class ThumbnailWorker(QRunnable):
    def __init__(self, file_path, cache, is_music=False, target_size=(220, 200)):
        super().__init__()
        self.file_path = file_path
        self.cache = cache
        self.is_music = is_music
        self.target_size = target_size
        self.signals = WorkerSignals()

    def run(self):
        qimg = self.cache.get(self.file_path, self.is_music, self.target_size) if self.cache else QImage()
        if qimg.isNull():
            qimg = self._generate()
            if not qimg.isNull() and self.cache:
                self.cache.put(self.file_path, self.is_music, self.target_size, qimg)
        self.signals.result.emit(self.file_path, qimg)

    def _generate(self):
        try:
            if self.is_music:
                qimg = self._extract_music_cover(self.file_path)
                if not qimg.isNull():
                    qimg = qimg.scaled(
                        self.target_size[0], self.target_size[1],
                        Qt.KeepAspectRatio, Qt.SmoothTransformation)
                return qimg
            reader = QImageReader(self.file_path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                target = QSize(self.target_size[0], self.target_size[1])
                reader.setScaledSize(size.scaled(target, Qt.KeepAspectRatio))
            return reader.read()
        except Exception:
            log.debug("Falha ao gerar thumbnail de %s", self.file_path, exc_info=True)
            return QImage()

    def _extract_music_cover(self, file_path):
        if not MUTAGEN_AVAILABLE:
            return QImage()
        try:
            audio = mutagen.File(file_path)
            if not audio:
                return QImage()
            lower = file_path.lower()
            if lower.endswith('.mp3'):
                try:
                    tags = ID3(file_path)
                    for tag in tags.values():
                        if getattr(tag, 'FrameID', None) == 'APIC':
                            return QImage.fromData(tag.data)
                except Exception:
                    pass
            elif lower.endswith(('.m4a', '.mp4')):
                if 'covr' in audio:
                    data = audio['covr'][0]
                    if not isinstance(data, bytes):
                        data = bytes(data)
                    return QImage.fromData(data)
            elif lower.endswith('.flac'):
                if hasattr(audio, 'pictures') and audio.pictures:
                    return QImage.fromData(audio.pictures[0].data)
            elif lower.endswith('.ogg'):
                if 'metadata_block_picture' in audio:
                    for b64_data in audio['metadata_block_picture']:
                        try:
                            pic = Picture(base64.b64decode(b64_data))
                            return QImage.fromData(pic.data)
                        except Exception:
                            continue
        except Exception:
            log.debug("Falha ao extrair capa de %s", file_path, exc_info=True)
        return QImage()


class MetadataIndexSignals(QObject):
    done = Signal(dict)


class MetadataIndexWorker(QRunnable):
    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self.signals = MetadataIndexSignals()

    def run(self):
        index = {}
        for path in self.paths:
            parts = [os.path.basename(path).lower()]
            if MUTAGEN_AVAILABLE:
                try:
                    audio = mutagen.File(path, easy=True)
                    if audio:
                        for tag in ('title', 'artist', 'album'):
                            val = audio.get(tag)
                            if val:
                                if isinstance(val, list):
                                    parts.append(str(val[0]).lower())
                                else:
                                    parts.append(str(val).lower())
                except Exception:
                    pass
            index[path] = ' '.join(parts)
        self.signals.done.emit(index)


class CobanArchiveCore(QMainWindow):
    """Lógica do Coban Archive. A interface vem de layout_ui.py (LayoutUI)."""

    def __init__(self, log_path=None):
        super().__init__()
        self.log_path = log_path
        self._shutting_down = False
        self.setWindowTitle("Coban Archive")
        self.resize(1024, 650)
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.setWindowIcon(QIcon(self._asset_path("coban_archive_app.png")))

        self._load_config()
        self._restore_window_state()

        appdata = os.path.dirname(self.config_path)
        self.thumb_cache = ThumbnailCache(os.path.join(appdata, "thumbnails"))

        self.db = LibraryDB(os.path.join(appdata, "library.db"))
        self._dirty = {k: True for k in ("tracks", "videos", "games", "images", "albums")}
        for kind, key in (
            ("tracks", "music_folders"), ("videos", "video_folders"),
            ("games", "game_folders"), ("albums", "cd_folders"),
            ("images", "gallery_folders"),
        ):
            folders = [f for f in self.app_config.get(key, []) if f]
            if not folders and kind == "tracks":
                fb = self.app_config.get("initial_folder", "")
                folders = [fb] if fb else []
            if folders and self.db.has_scan(kind, folders):
                self._dirty[kind] = False
        self._watched_dirs = set()

        self._track_progress = dict(self.app_config.get("track_progress", {}))
        self._last_track_save_ms = -10000
        self._pending_audio_seek = 0

        self._shuffle = bool(self.app_config.get("shuffle", False))
        self._repeat_mode = self.app_config.get("repeat_mode", "off")
        if self._repeat_mode not in REPEAT_MODES:
            self._repeat_mode = "off"

        self._apply_theme()

        self.threadpool = QThreadPool.globalInstance()
        self.threadpool.setMaxThreadCount(4)

        self.current_cover_pixmap = None
        self.current_track_path = None
        self.playlist_tracks = []
        self.current_track_index = -1

        self.all_gallery_images = []
        self.gallery_loaded_count = 0
        self.gallery_initialized = False
        self.gallery_thumb_refs = {}
        self._gallery_scan_gen = 0
        self._gallery_scanner = None

        self.all_music_tracks = []
        self.filtered_music_tracks = []
        self._track_to_index = {}
        self._track_search_index = {}
        self.music_loaded_count = 0
        self.music_initialized = False
        self.music_thumb_refs = {}
        self._music_scan_gen = 0
        self._music_scanner = None

        self.all_cds = []
        self.filtered_cds = []
        self.cds_loaded_count = 0
        self.cds_initialized = False
        self.cd_thumb_refs = {}
        self._cd_scan_gen = 0
        self._cd_scanner = None
        self._cd_cover_to_folder = {}

        self.all_game_tracks = []
        self.filtered_game_tracks = []
        self.game_loaded_count = 0
        self.games_initialized = False
        self.game_thumb_refs = {}
        self._game_scan_gen = 0
        self._game_scanner = None
        self._cover_cache = {}
        self._cover_to_game = {}

        self._video_scan_gen = 0
        self._video_scanner = None
        self._pending_video_selection = None

        self._pending_seek = 0
        self._resume_target = 0

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)
        self.is_playing = False

        self.player.positionChanged.connect(self._update_progress)
        self.player.durationChanged.connect(self._update_duration)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.errorOccurred.connect(self._on_audio_error)
        self.player.mediaStatusChanged.connect(self._on_audio_media_status_changed)

        self.video_player = QMediaPlayer(self)
        self.video_audio_output = QAudioOutput(self)
        self.video_player.setAudioOutput(self.video_audio_output)
        self.video_audio_output.setVolume(0.8)
        self.video_player.errorOccurred.connect(self._on_video_error)

        self.video_progress = self.app_config.setdefault("video_progress", {})
        self._last_video_config_save_ms = -10000

        self.video_folders = list(self.app_config.get("video_folders", ["", "", "", "", ""]))[:5]
        self.video_folders += [""] * (5 - len(self.video_folders))
        self.video_player.positionChanged.connect(self._save_video_position)
        self.video_player.mediaStatusChanged.connect(self._video_media_status_changed)
        self.video_player.mediaStatusChanged.connect(lambda _: self._try_pending_seek())

        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self._on_audio_devices_changed)

        self._build_ui()
        last_page_key = self.app_config.get("last_page", "inicio")

        self._setup_watchers()
        self._setup_shortcuts()
        self._setup_tray_icon()

        if last_page_key == "explorer":
            self.carregar_musicas_grid()
        elif last_page_key == "games":
            self.carregar_games_grid()
        elif last_page_key == "cds":
            self.carregar_cds_grid()
        elif last_page_key == "galeria":
            self.carregar_fotos_galeria()

        last_track = self.app_config.get("last_track", "")
        if last_track and os.path.isfile(last_track):
            self.current_track_path = last_track
            self._load_metadata(last_track)
            self.player.setSource(QUrl.fromLocalFile(last_track))
            saved_playlist = self.app_config.get("playlist", [])
            if saved_playlist:
                self.playlist_tracks = [p for p in saved_playlist if os.path.isfile(p)]
                try:
                    self.current_track_index = self.playlist_tracks.index(last_track)
                except ValueError:
                    self.current_track_index = 0 if self.playlist_tracks else -1
            else:
                QTimer.singleShot(0, lambda p=last_track: self._build_playlist_from_file(p))

        if self._is_first_run():
            QTimer.singleShot(100, self._show_first_run_wizard)

    def _is_first_run(self):
        if self.app_config.get("first_run_completed"):
            return False
        for key in ("music_folders", "video_folders", "game_folders",
                    "cd_folders", "gallery_folders"):
            folders = self.app_config.get(key, [])
            if any(f for f in folders if f):
                self.app_config["first_run_completed"] = True
                return False
        return True

    def _restore_window_state(self):
        geom_b64 = self.app_config.get("window_geometry")
        if geom_b64:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geom_b64.encode("ascii")))
            except Exception:
                log.debug("Falha ao restaurar geometria", exc_info=True)
        state_b64 = self.app_config.get("window_state")
        if state_b64:
            try:
                self.restoreState(QByteArray.fromBase64(state_b64.encode("ascii")))
            except Exception:
                log.debug("Falha ao restaurar window state", exc_info=True)

    def _on_page_changed(self, index):
        widget = self.stacked_widget.widget(index)
        for key, w in getattr(self, "_page_map", {}).items():
            if w is widget:
                self.app_config["last_page"] = key
                return

    def _folders_status(self, key, fallback_initial=False):
        configured = [f for f in self.app_config.get(key, []) if f]
        if not configured and fallback_initial:
            fb = self.app_config.get("initial_folder", "")
            if fb:
                configured = [fb]
        accessible = [f for f in configured if os.path.isdir(f)]
        dead = [f for f in configured if f not in accessible]
        return configured, accessible, dead

    def _play_single_audio(self, path):
        if not path or not os.path.isfile(path):
            return
        if self.video_player.playbackState() == QMediaPlayer.PlayingState:
            self.video_player.pause()
        self._build_playlist_from_file(path)
        self._play_track_at_index(self.current_track_index)

    def _play_single_video(self, path):
        if not hasattr(self, "video_list"):
            return
        for i in range(self.video_list.count()):
            if self.video_list.item(i).data(Qt.UserRole) == path:
                self.video_list.setCurrentRow(i)
                self._play_selected_video()
                return

    def _on_video_context_menu(self, pos):
        item = self.video_list.itemAt(pos)
        if not item:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        self._show_card_menu(path, self.video_list.mapToGlobal(pos), is_video=True)

    def _setup_watchers(self):
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._dir_change_timer = QTimer(self)
        self._dir_change_timer.setSingleShot(True)
        self._dir_change_timer.setInterval(800)
        self._dir_change_timer.timeout.connect(self._reload_current_page_if_dirty)
        self._refresh_watchers()

    def _refresh_watchers(self):
        if not hasattr(self, "_watcher"):
            return
        roots = []
        for key in ("music_folders", "video_folders", "game_folders",
                    "cd_folders", "gallery_folders"):
            for f in self.app_config.get(key, []):
                if f and os.path.isdir(f):
                    roots.append(f)
        to_watch = set()
        for root in roots:
            to_watch.add(root)
            try:
                count = 0
                for entry in os.scandir(root):
                    if entry.is_dir(follow_symlinks=False) and count < 1000:
                        to_watch.add(entry.path)
                        count += 1
            except OSError:
                pass
        new = to_watch - self._watched_dirs
        removed = self._watched_dirs - to_watch
        if new:
            self._watcher.addPaths(list(new))
        if removed:
            self._watcher.removePaths(list(removed))
        self._watched_dirs = to_watch

    def _on_dir_changed(self, path):
        norm = os.path.normpath(path)
        for kind, key in (
            ("tracks", "music_folders"), ("videos", "video_folders"),
            ("games", "game_folders"), ("albums", "cd_folders"),
            ("images", "gallery_folders"),
        ):
            for root in self.app_config.get(key, []):
                if not root:
                    continue
                nr = os.path.normpath(root)
                if norm == nr or norm.startswith(nr + os.sep):
                    self._dirty[kind] = True
                    break
        if hasattr(self, "_dir_change_timer"):
            self._dir_change_timer.start()

    def _reload_current_page_if_dirty(self):
        if self._shutting_down:
            return
        current = self.stacked_widget.currentWidget()
        if current is self.page_explorer and self._dirty["tracks"]:
            self.carregar_musicas_grid()
        elif current is self.page_videos and self._dirty["videos"]:
            self._refresh_video_list()
        elif current is self.page_games and self._dirty["games"]:
            self.carregar_games_grid()
        elif current is self.page_cds and self._dirty["albums"]:
            self.carregar_cds_grid()
        elif current is self.page_galeria and self._dirty["images"]:
            self.carregar_fotos_galeria()

    def _clear_library_cache(self):
        reply = QMessageBox.question(
            self, "Limpar Cache da Biblioteca",
            "Isso apagará o banco de dados de varreduras e forçará nova\n"
            "indexação na próxima visita a cada página.\n\nDeseja continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        if getattr(self, "db", None) is not None:
            try:
                self.db.clear()
            except Exception:
                log.exception("Falha ao limpar cache")
        for k in self._dirty:
            self._dirty[k] = True
        self._track_search_index = {}
        self.music_initialized = False
        self.cds_initialized = False
        self.games_initialized = False
        self.gallery_initialized = False
        current = self.stacked_widget.currentWidget()
        if current is self.page_explorer:
            self.carregar_musicas_grid(force_scan=True)
        elif current is self.page_videos:
            self._refresh_video_list(force_scan=True)
        elif current is self.page_games:
            self.carregar_games_grid(force_scan=True)
        elif current is self.page_cds:
            self.carregar_cds_grid(force_scan=True)
        elif current is self.page_galeria:
            self.carregar_fotos_galeria(force_scan=True)
        QMessageBox.information(
            self, "Cache Limpo",
            "O cache da biblioteca foi removido. As páginas serão reindexadas "
            "na próxima visita.")

    def _open_log_folder(self):
        if not self.log_path:
            QMessageBox.warning(self, "Log não configurado", "O arquivo de log não foi inicializado.")
            return
        log_dir = os.path.dirname(self.log_path)
        if os.path.isdir(log_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir))
        else:
            QMessageBox.warning(self, "Pasta não encontrada", f"A pasta não existe:\n{log_dir}")

    def _seek_forward(self):
        if self.player.hasAudio() or self.current_track_path:
            dur = self.player.duration()
            target = self.player.position() + 5000
            if dur > 0:
                target = min(target, dur)
            self.player.setPosition(target)

    def _seek_backward(self):
        if self.player.hasAudio() or self.current_track_path:
            self.player.setPosition(max(0, self.player.position() - 5000))

    def _volume_up(self):
        self.slider_volume.setValue(min(100, self.slider_volume.value() + 5))

    def _volume_down(self):
        self.slider_volume.setValue(max(0, self.slider_volume.value() - 5))

    def _toggle_mute(self):
        if self.slider_volume.value() > 0:
            self._prev_volume = self.slider_volume.value()
            self.slider_volume.setValue(0)
        else:
            self.slider_volume.setValue(getattr(self, "_prev_volume", 80))

    def _focus_search(self):
        current = self.stacked_widget.currentWidget()
        if current == self.page_explorer and hasattr(self, "input_search"):
            self.input_search.setFocus()
            self.input_search.selectAll()
        elif current == self.page_games and hasattr(self, "input_search_game"):
            self.input_search_game.setFocus()
            self.input_search_game.selectAll()
        elif current == self.page_cds and hasattr(self, "input_search_cd"):
            self.input_search_cd.setFocus()
            self.input_search_cd.selectAll()

    def _on_audio_error(self, error, error_string):
        log.warning("Erro de áudio: %s (%s)", error_string, error)

    def _on_video_error(self, error, error_string):
        log.warning("Erro de vídeo: %s (%s)", error_string, error)
        if hasattr(self, "video_status"):
            self.video_status.setText(f"❌ {error_string or 'Erro ao reproduzir'}")

    def _on_audio_devices_changed(self):
        if not hasattr(self, "combo_audio"):
            return
        current = self.combo_audio.currentText()
        self.audio_devices = QMediaDevices.audioOutputs()
        self.combo_audio.blockSignals(True)
        self.combo_audio.clear()
        for dev in self.audio_devices:
            self.combo_audio.addItem(dev.description())
        if current:
            idx = self.combo_audio.findText(current)
            if idx >= 0:
                self.combo_audio.setCurrentIndex(idx)
        self.combo_audio.blockSignals(False)

    def _load_config(self):
        self.app_config = {
            "initial_folder": "", "audio_device": "", "last_track": "",
            "theme": "dark", "music_view_mode": "grid", "sidebar_side": "right",
            "gallery_folders": ["", "", "", "", ""], "music_folders": [],
            "video_folders": ["", "", "", "", ""],
            "game_folders": ["", "", "", "", ""],
            "cd_folders": ["", "", "", "", ""],
            "playlist": [], "playlist_index": -1, "volume": 80,
            "last_page": "inicio", "track_progress": {},
            "shuffle": False, "repeat_mode": "off",
            "first_run_completed": False,
        }
        appdata_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not appdata_dir:
            appdata_dir = self.script_dir
        os.makedirs(appdata_dir, exist_ok=True)
        self.config_path = os.path.join(appdata_dir, "config.json")
        legacy_path = os.path.join(self.script_dir, "config.json")
        read_path = self.config_path if os.path.exists(self.config_path) else legacy_path
        if os.path.exists(read_path):
            try:
                with open(read_path, "r", encoding="utf-8") as f:
                    self.app_config.update(json.load(f))
            except Exception:
                log.exception("Falha ao carregar configurações")
        for old_key in ("lkd_folder",):
            self.app_config.pop(old_key, None)

    def _save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.app_config, f, indent=4, ensure_ascii=False)
        except Exception:
            log.exception("Falha ao salvar configurações")

    def _abrir_galeria(self):
        self.stacked_widget.setCurrentWidget(self.page_galeria)
        self.atualizar_combo_pastas_galeria()
        if not self.gallery_initialized:
            self.carregar_fotos_galeria()

    def abrir_pasta_audio(self):
        self.stacked_widget.setCurrentWidget(self.page_explorer)
        if not self.music_initialized:
            self.carregar_musicas_grid()

    def abrir_cds(self):
        self.stacked_widget.setCurrentWidget(self.page_cds)
        if not self.cds_initialized:
            self.carregar_cds_grid()

    def abrir_videos(self):
        self.stacked_widget.setCurrentWidget(self.page_videos)
        self._refresh_video_list()

    def abrir_games(self):
        self.stacked_widget.setCurrentWidget(self.page_games)
        if not self.games_initialized:
            self.carregar_games_grid()

    def closeEvent(self, event):
        self._shutting_down = True
        for attr in ("_gallery_scanner", "_music_scanner", "_video_scanner",
                     "_game_scanner", "_cd_scanner"):
            scanner = getattr(self, attr, None)
            if scanner is not None and scanner.isRunning():
                scanner.requestInterruption()
        if self.current_track_path:
            try:
                pos = int(self.player.position())
                if pos > 1000:
                    self._set_track_progress(self.current_track_path, pos)
            except Exception:
                pass
        if len(self._track_progress) > 500:
            items = list(self._track_progress.items())[-500:]
            self._track_progress = dict(items)

        self.player.stop()
        self.video_player.stop()

        self.app_config["last_track"] = self.current_track_path or ""
        self.app_config["playlist"] = self.playlist_tracks[:1000]
        self.app_config["playlist_index"] = self.current_track_index
        self.app_config["track_progress"] = self._track_progress
        self.app_config["volume"] = self.slider_volume.value()
        self.app_config["shuffle"] = self._shuffle
        self.app_config["repeat_mode"] = self._repeat_mode
        try:
            geom = self.saveGeometry()
            self.app_config["window_geometry"] = bytes(geom.toBase64()).decode("ascii")
            st = self.saveState()
            self.app_config["window_state"] = bytes(st.toBase64()).decode("ascii")
        except Exception:
            log.debug("Falha ao salvar geometria", exc_info=True)
        self._save_video_position(self.video_player.position())
        self._save_config()

        for attr in ("_gallery_scanner", "_music_scanner", "_video_scanner",
                     "_game_scanner", "_cd_scanner"):
            scanner = getattr(self, attr, None)
            if scanner is not None and scanner.isRunning():
                scanner.wait(2000)
        if hasattr(self, "_watcher"):
            try:
                self._watcher.removePaths(list(self._watched_dirs))
            except Exception:
                pass
        if getattr(self, "db", None) is not None:
            self.db.close()
        if self._tray_icon:
            try:
                self._tray_icon.hide()
            except Exception:
                pass
        self.threadpool.waitForDone(3000)
        super().closeEvent(event)

    def _set_track_progress(self, path, position):
        if path in self._track_progress:
            del self._track_progress[path]
        self._track_progress[path] = int(position)

    def _on_shuffle_toggled(self, checked):
        self._shuffle = checked
        self._update_shuffle_button()
        self.app_config["shuffle"] = checked

    def _cycle_repeat_mode(self):
        idx = REPEAT_MODES.index(self._repeat_mode)
        self._repeat_mode = REPEAT_MODES[(idx + 1) % len(REPEAT_MODES)]
        self._update_repeat_button()
        self.app_config["repeat_mode"] = self._repeat_mode

    def _on_volume_changed(self, value):
        v = (value / 100.0) ** 2
        self.audio_output.setVolume(v)
        self.video_audio_output.setVolume(v)
        if not self._shutting_down:
            self.app_config["volume"] = int(value)

    def _on_video_playback_state_changed(self, state):
        playing = state == QMediaPlayer.PlayingState
        if hasattr(self, "video_pause_btn"):
            self.video_pause_btn.setEnabled(playing)
        if hasattr(self, "video_play_btn"):
            if playing:
                self.video_play_btn.setText("Pausar Reprodução")
                self.video_play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            else:
                self.video_play_btn.setText("Assistir / Retomar")
                self.video_play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

    def _toggle_video_fullscreen(self):
        if self.video_widget.isFullScreen():
            self.video_widget.setWindowFlags(Qt.Widget)
            self.video_widget.showNormal()
            self.video_widget.set_fullscreen_state(False)
            self.video_content_layout.insertWidget(0, self.video_widget, 3)
        else:
            self.video_content_layout.removeWidget(self.video_widget)
            self.video_widget.setParent(None)
            self.video_widget.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
            self.video_widget.set_fullscreen_state(True)
            self.video_widget.setGeometry(QApplication.primaryScreen().geometry())
            self.video_widget.showFullScreen()
            self.video_widget.raise_()
            self.video_widget.activateWindow()
            self.video_widget.setFocus()

    def _refresh_video_list(self, force_scan=False):
        if not hasattr(self, "video_list"):
            return
        current_item = self.video_list.currentItem()
        self._pending_video_selection = current_item.data(Qt.UserRole) if current_item else None
        configured, folders, dead = self._folders_status("video_folders")
        if not configured:
            self.video_list.clear()
            self.video_status.setText("Configure até 5 pastas em Opções → Configurações")
            return
        if dead:
            self.video_status.setText(
                f"{len(folders)} pasta(s) OK · ⚠ {len(dead)} inacessível(is)")
        cached = self.db.get_videos(configured) if self.db.is_ready() else []
        if cached and not force_scan and not self._dirty["videos"]:
            self._on_videos_scanned(cached, self._video_scan_gen)
            return
        if cached:
            self._on_videos_scanned(cached, self._video_scan_gen)
        elif not dead:
            self.video_status.setText("🔍 Procurando vídeos...")
        self._dirty["videos"] = False
        if not folders:
            if not cached:
                self.video_list.clear()
                self.video_status.setText("⚠ Nenhuma pasta acessível.")
            return
        self._video_scan_gen += 1
        gen = self._video_scan_gen
        if self._video_scanner is not None and self._video_scanner.isRunning():
            self._video_scanner.requestInterruption()
        self._video_scanner = ScannerThread(folders, VIDEO_EXTS, False, db=self.db, kind="videos")
        self._video_scanner.finished_scan.connect(
            lambda results, g=gen: self._on_videos_scanned(results, g))
        self._video_scanner.start()

    def _on_videos_scanned(self, results, gen):
        if self._shutting_down or gen != self._video_scan_gen:
            return
        self.video_list.clear()
        for path in results:
            state = self.video_progress.get(path, {})
            if isinstance(state, (int, float)):
                state = {"position": int(state), "completed": False}
            if state.get("completed"):
                suffix = "  ✓ Assistido"
            elif state.get("position", 0) > 5000:
                suffix = f"  ↻ Retomar em {self._format_video_time(state['position'])}"
            else:
                suffix = "  • Não assistido"
            item = QListWidgetItem(os.path.basename(path) + suffix)
            item.setData(Qt.UserRole, path)
            self.video_list.addItem(item)
        if self._pending_video_selection:
            for i in range(self.video_list.count()):
                if self.video_list.item(i).data(Qt.UserRole) == self._pending_video_selection:
                    self.video_list.setCurrentRow(i)
                    break
        self._pending_video_selection = None
        if self.video_list.count() == 0:
            self.video_status.setText("Nenhum vídeo encontrado")
        else:
            self.video_status.setText(f"{self.video_list.count()} vídeo(s) encontrado(s)")

    def _update_current_video_item_text(self, path):
        if not hasattr(self, "video_list"):
            return
        state = self.video_progress.get(path, {})
        if state.get("completed"):
            suffix = "  ✓ Assistido"
        elif state.get("position", 0) > 5000:
            suffix = f"  ↻ Retomar em {self._format_video_time(state['position'])}"
        else:
            suffix = "  • Não assistido"
        for i in range(self.video_list.count()):
            item = self.video_list.item(i)
            if item.data(Qt.UserRole) == path:
                item.setText(os.path.basename(path) + suffix)
                break

    def _play_selected_video(self, *_):
        item = self.video_list.currentItem() if hasattr(self, "video_list") else None
        if not item:
            return
        path = item.data(Qt.UserRole)
        if not path or not os.path.isfile(path):
            return
        current_source = self.video_player.source().toLocalFile()
        if current_source and os.path.normpath(current_source) == os.path.normpath(path):
            if self.video_player.playbackState() == QMediaPlayer.PlayingState:
                self.video_player.pause()
            else:
                self.video_player.play()
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.is_playing = False
            play_path = self._nav_icon_path("play")
            if os.path.exists(play_path):
                self.btn_play.setIcon(QIcon(play_path))
            else:
                self.btn_play.setText("▶")
        state = self.video_progress.get(path, {})
        resume = 0 if state.get("completed") else int(state.get("position", 0))
        self.video_player.setSource(QUrl.fromLocalFile(path))
        self._pending_seek = resume
        self._resume_target = resume
        self.video_player.play()
        if resume > 0:
            self._try_pending_seek()
        self.video_status.setText(os.path.basename(path))

    def _try_pending_seek(self):
        if self._pending_seek <= 0:
            return
        status = self.video_player.mediaStatus()
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                      QMediaPlayer.MediaStatus.BufferedMedia):
            pos, self._pending_seek = self._pending_seek, 0
            self.video_player.setPosition(pos)
        else:
            QTimer.singleShot(100, self._try_pending_seek)

    def _save_video_position(self, position):
        path = self.video_player.source().toLocalFile()
        if not path:
            return
        duration = self.video_player.duration()
        if duration <= 0:
            return
        if self._resume_target > 0 and position < self._resume_target - 1000:
            return
        if position >= self._resume_target:
            self._resume_target = 0
        completed = False
        if duration > 0:
            if position >= duration - 10000 or position >= duration * 0.95:
                completed = True
            elif position < duration * 0.85:
                completed = False
            else:
                old = self.video_progress.get(path, {})
                completed = bool(old.get("completed", False))
        self.video_progress[path] = {
            "position": int(position), "duration": int(duration), "completed": completed,
        }
        self.app_config["video_progress"] = self.video_progress
        now_ms = int(datetime.now().timestamp() * 1000)
        if now_ms - self._last_video_config_save_ms >= 15000 or completed:
            self.video_progress[path]["updated"] = datetime.now().isoformat(timespec="seconds")
            self._save_config()
            self._last_video_config_save_ms = now_ms
            if not self._shutting_down:
                self._update_current_video_item_text(path)

    def _video_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            path = self.video_player.source().toLocalFile()
            if path:
                duration = self.video_player.duration()
                self.video_progress[path] = {
                    "position": 0, "duration": duration, "completed": True,
                    "updated": datetime.now().isoformat(timespec="seconds"),
                }
                self._resume_target = 0
                self.app_config["video_progress"] = self.video_progress
                self._save_config()
                if not self._shutting_down:
                    self._update_current_video_item_text(path)
                    self.video_status.setText(f"✓ Vídeo terminado: {os.path.basename(path)}")

    def _update_video_slider(self, position):
        if not self.video_progress_slider.isSliderDown():
            self.video_progress_slider.setValue(position)

    @staticmethod
    def _format_video_time(milliseconds):
        seconds = max(0, int(milliseconds // 1000))
        if seconds >= 3600:
            return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _execute_game_search(self):
        self._filter_game_list(self.input_search_game.text())

    # ======================================================================
    # Grades de mídia (músicas, jogos, CDs, galeria): lógica compartilhada
    # ======================================================================
    # As 4 abas funcionam igual: carregar pastas -> varrer em background -> mostrar
    # cards em lotes -> miniaturas chegam depois. Esta tabela descreve só o que muda
    # entre elas; os valores são NOMES de atributos de self (lidos com getattr/setattr),
    # assim os atributos antigos (_music_scan_gen, music_grid, ...) continuam existindo.
    _GRID_TABS = {
        #           grade          miniaturas          scroll          geração do scan   thread do scan
        "music": dict(grid="music_grid", refs="music_thumb_refs", scroll="scroll_music",
                      scan_gen="_music_scan_gen", scanner="_music_scanner",
                      #   lista exibida        cards já mostrados    lote  colunas  texto do botão
                      items="filtered_music_tracks", loaded="music_loaded_count", batch=40, cols=4, noun="músicas",
                      #   método do db  chave "dirty"  mensagem enquanto varre
                      db_get="get_tracks", dirty="tracks", loading="Lendo pasta de músicas em background..."),
        "games": dict(grid="games_grid", refs="game_thumb_refs", scroll="scroll_games",
                      scan_gen="_game_scan_gen", scanner="_game_scanner",
                      items="filtered_game_tracks", loaded="game_loaded_count", batch=40, cols=4, noun="jogos",
                      db_get="get_games", dirty="games", loading="Lendo pasta de jogos em background..."),
        "cds": dict(grid="cds_grid", refs="cd_thumb_refs", scroll="scroll_cds",
                    scan_gen="_cd_scan_gen", scanner="_cd_scanner",
                    items="filtered_cds", loaded="cds_loaded_count", batch=40, cols=4, noun="CDs",
                    db_get="get_albums", dirty="albums", loading="Lendo CDs em background..."),
        "gallery": dict(grid="gallery_grid", refs="gallery_thumb_refs", scroll="scroll_gallery",
                        scan_gen="_gallery_scan_gen", scanner="_gallery_scanner",
                        items="all_gallery_images", loaded="gallery_loaded_count", batch=100, cols=3, noun="fotos",
                        db_get="get_images", dirty="images", loading="Procurando imagens em background..."),
    }

    def _clear_grid(self, grid):
        """Remove (e agenda a destruição de) todos os widgets de um QGridLayout."""
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _grid_message(self, grid, text):
        """Mostra um aviso (ex.: 'Nenhum jogo encontrado') na primeira célula da grade."""
        lbl = QLabel(text)
        lbl.setObjectName("infoLabel")
        grid.addWidget(lbl, 0, 0)

    def _clear_silently(self, widget):
        """Limpa um campo de busca sem disparar textChanged (evita refiltrar sem querer)."""
        widget.blockSignals(True)
        widget.clear()
        widget.blockSignals(False)

    def _load_grid(self, tab, configured, folders, dead, force_scan, scanner_factory,
                   label=None, no_config_msg="Configure até 5 diretórios válidos nas Opções."):
        """Carrega uma aba de grade: usa o cache do banco se estiver válido, senão varre em background.

        configured: pastas configuradas · folders: as acessíveis · dead: as inacessíveis.
        scanner_factory(folders) cria a thread de varredura específica da aba.
        """
        t = self._GRID_TABS[tab]
        grid = getattr(self, t["grid"])
        on_scanned = getattr(self, f"_on_{tab}_scanned")
        self._clear_grid(grid)
        getattr(self, t["refs"]).clear()
        if label is not None:
            label.setText(
                f"{len(folders)} pasta(s) OK · ⚠ {len(dead)} inacessível(is)" if dead
                else f"{len(folders)} diretório(s) configurado(s)")
        if not configured:
            self._grid_message(grid, no_config_msg)
            return
        # 1) Cache: mostra direto, a menos que o usuário peça atualização ou a pasta tenha mudado
        cached = getattr(self.db, t["db_get"])(configured) if self.db.is_ready() else []
        if cached and not force_scan and not self._dirty[t["dirty"]]:
            on_scanned(cached, getattr(self, t["scan_gen"]))
            return
        if not cached and not dead:
            self._grid_message(grid, t["loading"])
        self._dirty[t["dirty"]] = False
        # 2) Nenhuma pasta acessível: mostra o que houver em cache (ou avisa)
        if not folders:
            if cached:
                on_scanned(cached, getattr(self, t["scan_gen"]))
            else:
                self._grid_message(grid, "⚠ Nenhuma pasta acessível.")
            return
        # 3) Varredura em background. A "geração" descarta resultados de varreduras antigas
        #    (se o usuário recarregar antes da anterior terminar).
        gen = getattr(self, t["scan_gen"]) + 1
        setattr(self, t["scan_gen"], gen)
        old = getattr(self, t["scanner"])
        if old is not None and old.isRunning():
            old.requestInterruption()
        scanner = scanner_factory(folders)
        setattr(self, t["scanner"], scanner)
        scanner.finished_scan.connect(lambda results, g=gen: on_scanned(results, g))
        scanner.start()

    def _append_batch(self, tab):
        """Mostra o próximo lote de cards da aba (e o botão 'Carregar mais' se ainda sobrar)."""
        if self._shutting_down:
            return
        t = self._GRID_TABS[tab]
        grid, items, cols = getattr(self, t["grid"]), getattr(self, t["items"]), t["cols"]
        # Remove o botão "Carregar mais" do lote anterior
        for i in range(grid.count()):
            item = grid.itemAt(i)
            if (item and item.widget() and isinstance(item.widget(), QPushButton)
                    and item.widget().text().startswith("Carregar mais")):
                item.widget().deleteLater()
        start = getattr(self, t["loaded"])
        end = min(start + t["batch"], len(items))
        make_card = getattr(self, f"_card_for_{tab}")   # monta card + sinais da aba
        for idx in range(start, end):
            card, worker = make_card(items[idx])
            grid.addWidget(card, idx // cols, idx % cols)
            if worker:                                   # miniatura carrega em background
                self.threadpool.start(worker)
        setattr(self, t["loaded"], end)
        if end < len(items):
            btn_more = self._create_btn(
                f"Carregar mais (+{t['batch']} {t['noun']} - Restam {len(items) - end})")
            btn_more.clicked.connect(lambda: self._append_batch(tab))
            total_rows = (len(items) + cols - 1) // cols
            grid.addWidget(btn_more, total_rows + 1, 0, 1, cols, Qt.AlignCenter)

    def _thumb_worker(self, path, slot, is_music, size=(220, 200)):
        """Cria o worker que gera a miniatura de `path` e avisa `slot(path, QImage)` quando pronta."""
        worker = ThumbnailWorker(path, self.thumb_cache, is_music=is_music, target_size=size)
        worker.signals.result.connect(slot)
        return worker

    def _apply_thumb(self, lbl, qimg, bg="transparent", on_fail=None):
        """Aplica a miniatura no QLabel; se a imagem for inválida, chama on_fail(lbl) (se houver)."""
        if not lbl:
            return
        if not qimg.isNull():
            lbl.setPixmap(QPixmap.fromImage(qimg))
            lbl.setStyleSheet(f"background-color: {bg}; border-radius: 8px;")
        elif on_fail:
            on_fail(lbl)

    def _refill_grid(self, tab):
        """Repopula a grade do zero (após filtrar) mantendo a posição do scroll."""
        t = self._GRID_TABS[tab]
        sb = getattr(self, t["scroll"]).verticalScrollBar()
        pos = sb.value()
        self._clear_grid(getattr(self, t["grid"]))
        getattr(self, t["refs"]).clear()
        setattr(self, t["loaded"], 0)
        self._append_batch(tab)
        QTimer.singleShot(0, lambda s=sb, p=pos: s.setValue(p))

    def carregar_games_grid(self, force_scan=False):
        self.games_initialized = True
        self._cover_cache = {}      # capas dos jogos são recalculadas a cada recarga
        self._cover_to_game = {}
        configured, folders, dead = self._folders_status("game_folders")
        self._load_grid(
            "games", configured, folders, dead, force_scan,
            lambda f: ScannerThread(f, GAME_EXTS, False, db=self.db, kind="games"),
            label=self.lbl_game_path)

    def _on_games_scanned(self, results, gen):
        if self._shutting_down or gen != self._game_scan_gen:
            return
        self._clear_grid(self.games_grid)
        self.all_game_tracks = results
        self.filtered_game_tracks = list(self.all_game_tracks)
        self._clear_silently(self.input_search_game)
        if not self.all_game_tracks:
            self._grid_message(self.games_grid, "Nenhum jogo encontrado nestas pastas.")
            return
        self.game_loaded_count = 0
        self._append_batch("games")

    def _filter_game_list(self, query):
        query = query.lower().strip()
        self.filtered_game_tracks = [
            t for t in self.all_game_tracks if not query or query in os.path.basename(t).lower()]
        self._refill_grid("games")

    def _card_for_games(self, game_path):
        card, lbl_thumb = self._build_game_card(game_path)
        self.game_thumb_refs[game_path] = lbl_thumb
        lbl_thumb.doubleClicked.connect(lambda p=game_path: self._open_game(p))
        lbl_thumb.rightClicked.connect(lambda p=game_path: self._show_card_menu(p, QCursor.pos()))
        # A capa é um arquivo de imagem ao lado da ROM; sem capa não há worker.
        cover_path = self._find_cover_for_rom(game_path)
        if not cover_path:
            return card, None
        self._cover_to_game[cover_path] = game_path
        return card, self._thumb_worker(cover_path, self._on_game_thumb_ready, False)

    def _find_cover_for_rom(self, rom_path):
        rom_dir = os.path.dirname(rom_path)
        rom_name = os.path.splitext(os.path.basename(rom_path))[0].lower()
        valid_exts = ('.png', '.jpg', '.jpeg', '.webp')
        if rom_dir not in self._cover_cache:
            images = {}
            try:
                for root, dirs, files in os.walk(rom_dir):
                    depth = root[len(rom_dir):].count(os.sep)
                    if depth > 1:
                        dirs[:] = []
                        continue
                    for f in files:
                        if f.lower().endswith(valid_exts):
                            name_no_ext = os.path.splitext(f)[0].lower()
                            if name_no_ext not in images or depth == 0:
                                images[name_no_ext] = os.path.join(root, f)
            except OSError:
                pass
            self._cover_cache[rom_dir] = images
        return self._cover_cache[rom_dir].get(rom_name)

    def _on_game_thumb_ready(self, cover_path, qimg):
        if self._shutting_down:
            return
        game_path = self._cover_to_game.get(cover_path)   # a miniatura chega pelo caminho da capa
        if game_path:
            self._apply_thumb(self.game_thumb_refs.get(game_path), qimg)   # sem capa: mantém o ícone

    def _open_game(self, path):
        if not path or not os.path.isfile(path):
            return
        if self.video_player.playbackState() == QMediaPlayer.PlayingState:
            self.video_player.pause()
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.is_playing = False
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            log.info("Abrindo jogo: %s", path)
        except Exception as e:
            log.error("Falha ao abrir jogo %s: %s", path, e)

    def _execute_cd_search(self):
        self._filter_cd_list(self.input_search_cd.text())

    def carregar_cds_grid(self, force_scan=False):
        self.cds_initialized = True
        self._cd_cover_to_folder = {}
        configured, folders, dead = self._folders_status("cd_folders")
        self._load_grid(
            "cds", configured, folders, dead, force_scan,
            lambda f: CDScannerThread(f, db=self.db),
            label=self.lbl_cd_path)

    def _on_cds_scanned(self, results, gen):
        if self._shutting_down or gen != self._cd_scan_gen:
            return
        self._clear_grid(self.cds_grid)
        self.all_cds = results
        self.filtered_cds = list(self.all_cds)
        self._clear_silently(self.input_search_cd)
        if not self.all_cds:
            self._grid_message(self.cds_grid, "Nenhum CD (álbum) encontrado nestas pastas.")
            return
        self.cds_loaded_count = 0
        self._append_batch("cds")

    def _filter_cd_list(self, query):
        query = query.lower().strip()
        self.filtered_cds = [cd for cd in self.all_cds if not query or query in cd[1].lower()]
        self._refill_grid("cds")

    def _card_for_cds(self, cd):
        folder_path, album_name, first_audio_path = cd
        card, lbl_thumb = self._build_cd_card(album_name)
        self.cd_thumb_refs[folder_path] = lbl_thumb
        lbl_thumb.clicked.connect(lambda p=folder_path: self._play_cd_album(p))
        lbl_thumb.rightClicked.connect(
            lambda p=folder_path, fa=first_audio_path: self._show_folder_menu(
                p, QCursor.pos(), first_audio=fa))
        # A capa do CD vem das tags do primeiro áudio do álbum.
        self._cd_cover_to_folder[first_audio_path] = folder_path
        return card, self._thumb_worker(first_audio_path, self._on_cd_thumb_ready, True)

    def _on_cd_thumb_ready(self, audio_path, qimg):
        if self._shutting_down:
            return
        folder_path = self._cd_cover_to_folder.get(audio_path)   # a miniatura chega pelo 1º áudio
        if folder_path:
            self._apply_thumb(
                self.cd_thumb_refs.get(folder_path), qimg,
                on_fail=lambda lbl: self._set_placeholder_icon(lbl, "cd_icon.png", 96, "💿"))

    def _play_cd_album(self, folder_path):
        self.playlist_tracks = []
        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    if entry.is_file() and entry.name.lower().endswith(AUDIO_EXTS):
                        self.playlist_tracks.append(entry.path)
            self.playlist_tracks.sort(key=lambda p: os.path.basename(p).casefold())
        except OSError:
            pass
        if self.playlist_tracks:
            if self.video_player.playbackState() == QMediaPlayer.PlayingState:
                self.video_player.pause()
            self._play_track_at_index(0)

    def carregar_fotos_galeria(self, force_scan=False):
        self.gallery_initialized = True
        # A galeria não usa _folders_status: respeita a pasta escolhida no combo (ou todas as configuradas).
        selected = (self.combo_galeria_pastas.currentData()
                    if hasattr(self, "combo_galeria_pastas") else "")
        configured = ([selected] if selected else
                      [f for f in self.app_config.get("gallery_folders", ["", "", "", "", ""]) if f])
        accessible = [f for f in configured if os.path.isdir(f)]
        dead = [f for f in configured if f not in accessible]
        self._load_grid(
            "gallery", configured, accessible, dead, force_scan,
            lambda f: ScannerThread(f, IMAGE_EXTS, True, db=self.db, kind="images"),
            no_config_msg="Nenhuma pasta de galeria válida encontrada ou selecionada.")

    def _on_gallery_scanned(self, results, gen):
        if self._shutting_down or gen != self._gallery_scan_gen:
            return
        self._clear_grid(self.gallery_grid)
        self.all_gallery_images = results
        if not self.all_gallery_images:
            self._grid_message(self.gallery_grid, "Nenhuma imagem encontrada nesta pasta.")
            return
        self.gallery_loaded_count = 0
        self._append_batch("gallery")

    def _card_for_gallery(self, image):
        mtime, img_path = image
        card, lbl_thumb = self._build_gallery_card(mtime)
        lbl_thumb.clicked.connect(lambda p=img_path: self._show_image_fullscreen(p))
        lbl_thumb.rightClicked.connect(lambda p=img_path: self._show_card_menu(p, QCursor.pos()))
        self.gallery_thumb_refs[img_path] = lbl_thumb
        return card, self._thumb_worker(img_path, self._on_gallery_thumb_ready, False, (360, 280))

    def _on_gallery_thumb_ready(self, path, qimg):
        if self._shutting_down:
            return
        self._apply_thumb(self.gallery_thumb_refs.get(path), qimg,
                          on_fail=lambda lbl: lbl.setText("Erro"))

    def _execute_search(self):
        self._filter_music_list(self.input_search.text())

    def _change_music_directory(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Selecione a pasta de músicas",
            self.app_config.get("initial_folder", ""))
        if folder:
            self.app_config["initial_folder"] = folder
            folders = list(self.app_config.get("music_folders", []))
            if folders:
                folders[0] = folder
            else:
                folders = [folder]
            self.app_config["music_folders"] = folders[:5]
            self._save_config()
            self._refresh_watchers()
            self.lbl_path.setText(
                folder if len(folders) == 1 else f"{len(folders)} diretório(s) configurado(s)")
            self._dirty["tracks"] = True
            self.carregar_musicas_grid(force_scan=True)

    def carregar_musicas_grid(self, force_scan=False):
        self.music_initialized = True
        configured, folders, dead = self._folders_status("music_folders", fallback_initial=True)
        self.list_music.clear()  # a aba tem também o modo "lista de nomes"
        self._load_grid(
            "music", configured, folders, dead, force_scan,
            lambda f: ScannerThread(f, AUDIO_EXTS, False, db=self.db, kind="tracks", extract_tags=True),
            label=self.lbl_path)

    def _on_music_scanned(self, results, gen):
        if self._shutting_down or gen != self._music_scan_gen:
            return
        self._clear_grid(self.music_grid)
        self.all_music_tracks = results
        self.filtered_music_tracks = list(self.all_music_tracks)
        self._track_to_index = {p: i + 1 for i, p in enumerate(self.all_music_tracks)}
        self._clear_silently(self.input_search)
        if not self.all_music_tracks:
            self._grid_message(self.music_grid, "Nenhuma música encontrada nesta pasta.")
            return
        if self.db.is_ready():
            configured, _, _ = self._folders_status(
                "music_folders", fallback_initial=True)
            self._track_search_index = self.db.get_search_index(configured)
        else:
            self._track_search_index = {}
        missing = [p for p in self.all_music_tracks if p not in self._track_search_index]
        if missing:
            worker = MetadataIndexWorker(missing)
            worker.signals.done.connect(self._on_search_index_ready)
            self.threadpool.start(worker)
        view_mode = self.app_config.get("music_view_mode", "grid")
        if view_mode == "names":
            self.music_stacked.setCurrentIndex(1)
            self._carregar_musicas_lista()
        else:
            self.music_stacked.setCurrentIndex(0)
            self.music_loaded_count = 0
            self._append_batch("music")

    def _on_search_index_ready(self, index):
        if self._shutting_down:
            return
        if isinstance(self._track_search_index, dict):
            self._track_search_index.update(index)
        else:
            self._track_search_index = index
        if self.input_search.text().strip():
            self._filter_music_list(self.input_search.text())

    def _filter_music_list(self, query):
        query = query.lower().strip()
        # Usa o índice de busca (nome/artista/álbum) quando existe; senão, só o nome do arquivo.
        self.filtered_music_tracks = [
            t for t in self.all_music_tracks
            if not query or query in self._track_search_index.get(t, os.path.basename(t).lower())]
        if self.app_config.get("music_view_mode", "grid") == "names":
            self._carregar_musicas_lista()
        else:
            self._refill_grid("music")

    def _carregar_musicas_lista(self):
        self.list_music.clear()
        self.list_music.setIconSize(QSize(20, 20))
        music_icon = self._icon("musica_icon.png")
        for track_path in self.filtered_music_tracks:
            original_idx = self._track_to_index.get(track_path, 0)
            filename = os.path.basename(track_path)
            item = QListWidgetItem(music_icon, f"#{original_idx:04d}   •   {filename}")
            item.setData(Qt.UserRole, track_path)
            self.list_music.addItem(item)

    def _play_selected_list_track(self, item):
        track_path = item.data(Qt.UserRole)
        idx = self._track_to_index.get(track_path, 0) - 1
        if 0 <= idx < len(self.all_music_tracks):
            self._play_grid_track(track_path, idx)

    def _card_for_music(self, track_path):
        original_idx = self._track_to_index.get(track_path, 0)   # nº da faixa na biblioteca (1-based)
        card, lbl_thumb = self._build_music_card(track_path, original_idx)
        self.music_thumb_refs[track_path] = lbl_thumb
        lbl_thumb.clicked.connect(
            lambda p=track_path, i=original_idx - 1: self._play_grid_track(p, i))
        lbl_thumb.rightClicked.connect(
            lambda p=track_path: self._show_card_menu(p, QCursor.pos(), is_audio=True))
        return card, self._thumb_worker(track_path, self._on_music_thumb_ready, True)

    def _on_music_thumb_ready(self, path, qimg):
        if self._shutting_down:
            return

        def sem_capa(lbl):  # ícone de música no lugar da capa
            self._set_placeholder_icon(lbl, "musica_icon.png", 80, "🎵")
            lbl.setStyleSheet(
                "font-size: 40px; background-color: #1e1e1e; border-radius: 8px; color: #777;")
        self._apply_thumb(self.music_thumb_refs.get(path), qimg, "#1a1a1a", sem_capa)

    def _play_grid_track(self, file_path, index):
        if self.video_player.playbackState() == QMediaPlayer.PlayingState:
            self.video_player.pause()
        self.playlist_tracks = self.all_music_tracks
        self._play_track_at_index(index)

    def _browse_folder_generic(self, inputs, index):
        current = inputs[index].text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Selecione a pasta", current or "")
        if folder:
            inputs[index].setText(folder)

    def _browse_initial_folder(self):
        current = self.app_config.get("initial_folder", "")
        folder = QFileDialog.getExistingDirectory(self, "Selecione a pasta", current)
        if folder:
            self.input_config_folder.setText(folder)

    def _apply_music_folders(self):
        folders = []
        for field in self.music_folder_inputs:
            folder = field.text().strip()
            if folder and folder not in folders and os.path.isdir(folder):
                folders.append(folder)
        self.app_config["music_folders"] = folders[:5]
        if folders:
            self.app_config["initial_folder"] = folders[0]
            self.input_config_folder.setText(folders[0])
            self.lbl_path.setText(f"{len(folders)} diretório(s) configurado(s)")
        self._save_config()
        self._refresh_watchers()
        self.music_initialized = False
        self._dirty["tracks"] = True
        self.carregar_musicas_grid(force_scan=True)

    def _apply_cd_folders(self):
        folders = []
        for field in self.cd_folder_inputs:
            folder = field.text().strip()
            if folder and folder not in folders and os.path.isdir(folder):
                folders.append(folder)
        folders = folders[:5]
        self.app_config["cd_folders"] = folders + [""] * (5 - len(folders))
        self._save_config()
        self._refresh_watchers()
        self.cds_initialized = False
        self._dirty["albums"] = True
        self.carregar_cds_grid(force_scan=True)

    def _apply_video_folders(self):
        folders = []
        for field in self.video_folder_inputs:
            folder = field.text().strip()
            if folder and folder not in folders and os.path.isdir(folder):
                folders.append(folder)
        folders = folders[:5]
        self.video_folders = folders + [""] * (5 - len(folders))
        self.app_config["video_folders"] = self.video_folders
        self._save_config()
        self._refresh_watchers()
        self._dirty["videos"] = True
        self._refresh_video_list(force_scan=True)

    def _apply_game_folders(self):
        folders = []
        for field in self.game_folder_inputs:
            folder = field.text().strip()
            if folder and folder not in folders and os.path.isdir(folder):
                folders.append(folder)
        folders = folders[:5]
        self.app_config["game_folders"] = folders + [""] * (5 - len(folders))
        self._save_config()
        self._refresh_watchers()
        self.games_initialized = False
        self._dirty["games"] = True
        self.carregar_games_grid(force_scan=True)

    def _aplicar_pastas_galeria(self):
        folders = [inp.text() for inp in self.gallery_inputs]
        self.app_config["gallery_folders"] = folders
        self._save_config()
        self.atualizar_combo_pastas_galeria()
        self._refresh_watchers()
        self.gallery_initialized = False
        self._dirty["images"] = True
        self.carregar_fotos_galeria(force_scan=True)

    def _change_theme(self, index):
        self.app_config["theme"] = self.combo_theme.itemData(index)
        self._save_config()
        self._update_theme_dynamic()

    def _change_sidebar_side(self, index):
        side = self.combo_sidebar_side.itemData(index) or "right"
        self.app_config["sidebar_side"] = side
        self._save_config()
        self.body_layout.removeWidget(self.sidebar)
        self.body_layout.removeWidget(self.stacked_widget)
        if side == "left":
            self.body_layout.addWidget(self.sidebar)
            self.body_layout.addWidget(self.stacked_widget, stretch=1)
        else:
            self.body_layout.addWidget(self.stacked_widget, stretch=1)
            self.body_layout.addWidget(self.sidebar)

    def _change_music_view_mode(self, index):
        view_key = self.combo_music_view.itemData(index)
        self.app_config["music_view_mode"] = view_key
        self._save_config()
        if self.all_music_tracks:
            if view_key == "names":
                self.music_stacked.setCurrentIndex(1)
                self._carregar_musicas_lista()
            else:
                sb = self.scroll_music.verticalScrollBar()
                pos = sb.value()
                self.music_stacked.setCurrentIndex(0)
                self._clear_grid(self.music_grid)
                self.music_loaded_count = 0
                self._append_batch("music")
                QTimer.singleShot(0, lambda s=sb, p=pos: s.setValue(p))

    def _aplicar_pasta_audio(self):
        self.app_config["initial_folder"] = self.input_config_folder.text()
        self._save_config()
        self._refresh_watchers()
        self._dirty["tracks"] = True
        self.carregar_musicas_grid(force_scan=True)

    def _change_audio_device(self, index):
        if 0 <= index < len(self.audio_devices):
            dev = self.audio_devices[index]
            self.audio_output.setDevice(dev)
            self.video_audio_output.setDevice(dev)
            self.app_config["audio_device"] = dev.description()
            self._save_config()

    def _build_playlist_from_file(self, file_path):
        if self._shutting_down:
            return
        directory = os.path.dirname(file_path)
        self.playlist_tracks = []
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    if entry.is_file() and entry.name.lower().endswith(AUDIO_EXTS):
                        self.playlist_tracks.append(entry.path)
            self.playlist_tracks.sort(key=lambda p: os.path.basename(p).casefold())
            if file_path in self.playlist_tracks:
                self.current_track_index = self.playlist_tracks.index(file_path)
            else:
                self.playlist_tracks.insert(0, file_path)
                self.current_track_index = 0
        except OSError:
            self.playlist_tracks = [file_path]
            self.current_track_index = 0

    def _play_track_at_index(self, index):
        if not self.playlist_tracks:
            return
        if self.current_track_path and self.player.hasAudio():
            try:
                pos = int(self.player.position())
                if pos > 1000:
                    self._set_track_progress(self.current_track_path, pos)
            except Exception:
                pass
        self.current_track_index = index % len(self.playlist_tracks)
        file_path = self.playlist_tracks[self.current_track_index]
        if not os.path.exists(file_path):
            return
        self.current_track_path = file_path
        self._load_metadata(file_path)
        self.player.setSource(QUrl.fromLocalFile(file_path))
        resume = self._track_progress.get(file_path, 0)
        self._pending_audio_seek = resume if resume > 5000 else 0
        self.player.play()
        self.is_playing = True
        pausa_path = self._nav_icon_path("pausa")
        if os.path.exists(pausa_path):
            self.btn_play.setIcon(QIcon(pausa_path))
        else:
            self.btn_play.setText("⏸")
        self._update_tray_play_action()

    def _on_audio_media_status_changed(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                      QMediaPlayer.MediaStatus.BufferedMedia):
            if getattr(self, "_pending_audio_seek", 0) > 0:
                resume = self._pending_audio_seek
                dur = self.player.duration()
                if dur > 0:
                    self._pending_audio_seek = 0
                    if resume < dur - 3000:
                        self.player.setPosition(resume)
                        log.info("Retomando áudio em %.1fs: %s",
                                 resume / 1000.0, os.path.basename(self.current_track_path))

    def _play_next_track(self):
        if not self.playlist_tracks:
            return
        if self._repeat_mode == "one" and self.current_track_path:
            self.player.setPosition(0)
            self.player.play()
            self.is_playing = True
            self._update_tray_play_action()
            return
        if self._shuffle:
            n = len(self.playlist_tracks)
            if n <= 1:
                next_idx = 0
            else:
                while True:
                    next_idx = random.randint(0, n - 1)
                    if next_idx != self.current_track_index:
                        break
        else:
            next_idx = self.current_track_index + 1
            if next_idx >= len(self.playlist_tracks):
                if self._repeat_mode == "all":
                    next_idx = 0
                else:
                    self.is_playing = False
                    play_path = self._nav_icon_path("play")
                    if os.path.exists(play_path):
                        self.btn_play.setIcon(QIcon(play_path))
                    else:
                        self.btn_play.setText("▶")
                    self._update_tray_play_action()
                    return
        self._play_track_at_index(next_idx)

    def _play_prev_track(self):
        if not self.playlist_tracks:
            return
        if self._repeat_mode == "one" and self.current_track_path:
            self.player.setPosition(0)
            self.player.play()
            self.is_playing = True
            self._update_tray_play_action()
            return
        if self._shuffle:
            n = len(self.playlist_tracks)
            if n <= 1:
                prev_idx = 0
            else:
                while True:
                    prev_idx = random.randint(0, n - 1)
                    if prev_idx != self.current_track_index:
                        break
        else:
            prev_idx = self.current_track_index - 1
            if prev_idx < 0:
                if self._repeat_mode == "all":
                    prev_idx = len(self.playlist_tracks) - 1
                else:
                    return
        self._play_track_at_index(prev_idx)

    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.StoppedState and self.is_playing:
            try:
                dur = self.player.duration()
                pos = self.player.position()
                if dur > 0 and pos > 0 and pos >= dur - 500:
                    if self.current_track_path:
                        self._track_progress.pop(self.current_track_path, None)
                        self.app_config["track_progress"] = self._track_progress
                    self._play_next_track()
            except Exception:
                pass

    def _toggle_play(self):
        if self.player.hasAudio() or self.current_track_path:
            pausa_path = self._nav_icon_path("pausa")
            play_path = self._nav_icon_path("play")
            if self.is_playing:
                self.player.pause()
                if self.current_track_path:
                    try:
                        pos = int(self.player.position())
                        if pos > 1000:
                            self._set_track_progress(self.current_track_path, pos)
                            self.app_config["track_progress"] = self._track_progress
                            self._save_config()
                    except Exception:
                        pass
                if os.path.exists(play_path):
                    self.btn_play.setIcon(QIcon(play_path))
                else:
                    self.btn_play.setText("▶")
            else:
                self.player.play()
                if os.path.exists(pausa_path):
                    self.btn_play.setIcon(QIcon(pausa_path))
                else:
                    self.btn_play.setText("⏸")
            self.is_playing = not self.is_playing
            self._update_tray_play_action()

    def _update_progress(self, position):
        self.slider_progress.setValue(position)
        self.lbl_time_cur.setText(self._format_time(position))
        if self.current_track_path and position > 1000:
            now_ms = int(datetime.now().timestamp() * 1000)
            if now_ms - self._last_track_save_ms >= 5000:
                self._set_track_progress(self.current_track_path, position)
                self._last_track_save_ms = now_ms
                self.app_config["track_progress"] = self._track_progress
                self._save_config()

    def _update_duration(self, duration):
        self.slider_progress.setRange(0, duration)
        self.lbl_time_tot.setText(self._format_time(duration))

    def _set_position(self, position):
        self.player.setPosition(position)

    def _format_time(self, ms):
        s = (ms // 1000) % 60
        m = (ms // 60000) % 60
        return f"{m:02}:{s:02}"

    def _load_metadata(self, file_path):
        title = os.path.basename(file_path)
        artist = "Desconhecido"
        year = "---"
        self.current_cover_pixmap = None
        if MUTAGEN_AVAILABLE:
            try:
                audio = mutagen.File(file_path)
                if audio:
                    lower = file_path.lower()
                    if lower.endswith('.mp3'):
                        tags = ID3(file_path)
                        title = _first_tag(tags, 'TIT2', title)
                        artist = _first_tag(tags, 'TPE1', artist)
                        year = str(_first_tag(tags, 'TDRC', year))
                        for tag in tags.values():
                            if getattr(tag, 'FrameID', None) == 'APIC':
                                img = QImage.fromData(tag.data)
                                self.current_cover_pixmap = QPixmap.fromImage(img)
                                break
                    elif lower.endswith(('.m4a', '.mp4')):
                        title = _first_tag(audio, '\xa9nam', title)
                        artist = _first_tag(audio, '\xa9ART', artist)
                        year = str(_first_tag(audio, '\xa9day', year))
                        if 'covr' in audio:
                            cd = audio['covr'][0]
                            if not isinstance(cd, bytes):
                                cd = bytes(cd)
                            self.current_cover_pixmap = QPixmap.fromImage(QImage.fromData(cd))
                    elif lower.endswith('.flac'):
                        title = _first_tag(audio, 'title', title)
                        artist = _first_tag(audio, 'artist', artist)
                        year = str(_first_tag(audio, 'date', year))
                        if hasattr(audio, 'pictures') and audio.pictures:
                            self.current_cover_pixmap = QPixmap.fromImage(
                                QImage.fromData(audio.pictures[0].data))
                    elif lower.endswith('.ogg'):
                        title = _first_tag(audio, 'title', title)
                        artist = _first_tag(audio, 'artist', artist)
                        year = str(_first_tag(audio, 'date', year))
                        if 'metadata_block_picture' in audio:
                            for b64_data in audio['metadata_block_picture']:
                                try:
                                    pic = Picture(base64.b64decode(b64_data))
                                    self.current_cover_pixmap = QPixmap.fromImage(
                                        QImage.fromData(pic.data))
                                    break
                                except Exception:
                                    continue
            except Exception:
                log.debug("Falha ao ler metadata de %s", file_path, exc_info=True)
        self.lbl_title.setText(str(title))
        self.lbl_artist_year.setText(f"{artist} • {year}")
        if self.current_cover_pixmap:
            self.lbl_cover.setPixmap(self.current_cover_pixmap.scaled(
                60, 60, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            self.lbl_cover.setPixmap(QPixmap())
            self._set_placeholder_icon(self.lbl_cover, "musica_icon.png", 36, "🎵")
            self.lbl_cover.setAlignment(Qt.AlignCenter)
