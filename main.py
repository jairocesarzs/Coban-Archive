import sys
import os
import json
import base64
import hashlib
import logging
import random
from logging.handlers import RotatingFileHandler
from datetime import datetime
from PIL import Image

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QSlider, QCheckBox, QStackedWidget,
    QFileDialog, QTabWidget, QComboBox, QLineEdit, QDialog, QScrollArea,
    QGridLayout, QListWidget, QListWidgetItem, QStyle, QSizePolicy,
    QMessageBox, QMenu, QSystemTrayIcon, QTreeWidget, QTreeWidgetItem
)
from PySide6.QtCore import (
    Qt, QUrl, Signal, QSize, QTimer, QRect, QRectF, QThread, QRunnable,
    QThreadPool, QObject, QStandardPaths, QFileSystemWatcher, QByteArray
)
from PySide6.QtGui import (
    QPixmap, QImage, QIcon, QPainter, QColor, QImageReader, QPen,
    QShortcut, QKeySequence, QDesktopServices, QCursor, QAction
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices, QVideoSink

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
GITHUB_URL = "https://github.com/seu-usuario/coban-archive"
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

BTN_STYLES = {
    "primary": "QPushButton { padding: 8px 16px; background-color: #0078D7; color: white; border-radius: 4px; border: none; font-weight: bold; } QPushButton:hover { background-color: #005A9E; }",
    "success": "QPushButton { padding: 8px 16px; background-color: #28a745; color: white; border-radius: 4px; border: none; font-weight: bold; } QPushButton:hover { background-color: #218838; }",
    "warning": "QPushButton { padding: 8px 16px; background-color: #C9C819; color: #111111; border-radius: 5px; border: none; font-weight: bold; } QPushButton:hover { background-color: #D2D02A; } QPushButton:pressed { background-color: #B5B316; }",
    "info":    "QPushButton { padding: 8px 16px; background-color: #087DB5; color: white; border-radius: 5px; border: none; font-weight: bold; } QPushButton:hover { background-color: #0A8FC9; }",
}

BTN_ICONS = (
    ("Atualizar", "atualizar_icon.png"),
    ("Procurar", "pasta_icon.png"),
    ("Outra Pasta", "pasta_icon.png"),
)


def _first_tag(audio, key, default):
    val = audio.get(key)
    if val is None:
        return default
    if isinstance(val, list):
        return val[0] if val else default
    return val


class ClickableLabel(QLabel):
    clicked = Signal()
    doubleClicked = Signal()
    rightClicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        elif event.button() == Qt.RightButton:
            self.rightClicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class VideoPlayerWidget(QWidget):
    toggle_fullscreen_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("border: none;")
        self._bg_color = QColor("#101010")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_sink = QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self._on_frame_changed)
        self.current_image = QImage()
        self.overlay_pixmap = QPixmap()
        self.screen_opening = (183, 173, 1082, 684)
        self._is_fullscreen = False
        self._scanlines = self._make_scanlines()

    def _make_scanlines(self):
        px = QPixmap(1, 2)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.fillRect(0, 1, 1, 1, QColor(0, 0, 0, 130))
        p.end()
        return px

    def set_background_color(self, color):
        self._bg_color = QColor(color)
        self.update()

    def set_overlay_pixmap(self, pixmap):
        self.overlay_pixmap = pixmap
        self.update()

    def setMediaPlayer(self, player):
        player.setVideoSink(self.video_sink)

    def _on_frame_changed(self, frame):
        if not frame.isValid():
            return
        img = frame.toImage()
        if not img.isNull():
            self.current_image = img
            self.update()

    def set_fullscreen_state(self, is_fs):
        self._is_fullscreen = is_fs
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F11):
            self.toggle_fullscreen_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.toggle_fullscreen_requested.emit()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        if self._is_fullscreen:
            painter.fillRect(self.rect(), Qt.black)
            if not self.current_image.isNull():
                scaled = self.current_image.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
            return
        painter.fillRect(self.rect(), self._bg_color)
        if self.overlay_pixmap.isNull():
            if not self.current_image.isNull():
                scaled = self.current_image.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
            return
        pw, ph = self.overlay_pixmap.width(), self.overlay_pixmap.height()
        scale = min(w / pw, h / ph)
        fw, fh = pw * scale, ph * scale
        fx, fy = (w - fw) / 2, (h - fh) / 2
        ox, oy, ow, oh = self.screen_opening
        vx, vy, vw, vh = fx + ox * scale, fy + oy * scale, ow * scale, oh * scale
        v_rect = QRectF(vx, vy, vw, vh)
        painter.drawPixmap(QRectF(fx, fy, fw, fh), self.overlay_pixmap, QRectF(self.overlay_pixmap.rect()))
        if not self.current_image.isNull():
            painter.save()
            painter.setClipRect(v_rect)
            img = self.current_image
            iw, ih = img.width(), img.height()
            if iw > 0 and ih > 0 and vw > 0 and vh > 0:
                target_ar = vw / vh
                img_ar = iw / ih
                if img_ar > target_ar:
                    new_w = int(ih * target_ar)
                    src = QRect((iw - new_w) // 2, 0, new_w, ih)
                else:
                    new_h = int(iw / target_ar)
                    src = QRect(0, (ih - new_h) // 2, iw, new_h)
                painter.drawImage(v_rect, img, QRectF(src))
            else:
                painter.drawImage(v_rect, img)
            if not self._scanlines.isNull():
                painter.drawTiledPixmap(v_rect, self._scanlines)
            painter.fillRect(v_rect, QColor(0, 10, 5, 30))
            painter.restore()


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


class GlobalSearchDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.selected_kind = None
        self.selected_data = None
        self.setWindowTitle("Busca Global")
        self.setMinimumSize(650, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        title = QLabel("🔍  Busca Global")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        hint = QLabel("Pesquise por nome de música, artista, álbum, vídeo ou jogo.")
        hint.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(hint)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Digite pelo menos 2 caracteres...")
        self.input.setFixedHeight(38)
        self.input.setStyleSheet("padding: 0 12px; font-size: 14px;")
        layout.addWidget(self.input)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.itemDoubleClicked.connect(self._on_item_activated)
        layout.addWidget(self.tree, 1)
        footer = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.reject)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(btn_close)
        layout.addLayout(footer)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._perform_search)
        self.input.textChanged.connect(self._schedule_search)
        self.input.setFocus()

    def _schedule_search(self):
        text = self.input.text().strip()
        if len(text) < 2:
            self.tree.clear()
            self.status_label.setText("")
            return
        self._debounce.start()

    def _perform_search(self):
        query = self.input.text().strip()
        if len(query) < 2:
            return
        results = self.db.search_all(query)
        self.tree.clear()
        total = 0
        labels = {
            "tracks": "🎵 Músicas", "albums": "💿 CDs / Álbuns",
            "videos": "🎬 Vídeos", "games": "🎮 Jogos",
        }
        for kind in ("tracks", "albums", "videos", "games"):
            items = results.get(kind, [])
            if not items:
                continue
            root = QTreeWidgetItem([f"{labels[kind]} ({len(items)})"])
            root.setExpanded(True)
            root.setFlags(root.flags() & ~Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(root)
            for row in items:
                if kind == "tracks":
                    display = row.get("title") or os.path.basename(row["path"])
                    extra = row.get("artist") or ""
                elif kind == "albums":
                    display = row.get("name") or os.path.basename(row["folder"])
                    extra = ""
                else:
                    display = row.get("filename") or os.path.basename(row["path"])
                    extra = ""
                text = display + (f"  —  {extra}" if extra else "")
                child = QTreeWidgetItem([text])
                child.setData(0, Qt.UserRole, kind)
                child.setData(0, Qt.UserRole + 1, row)
                root.addChild(child)
                total += 1
        self.status_label.setText(f"{total} resultado(s)" if total else "Nada encontrado")

    def _on_item_activated(self, item, col):
        kind = item.data(0, Qt.UserRole)
        row = item.data(0, Qt.UserRole + 1)
        if kind and row:
            self.selected_kind = kind
            self.selected_data = row
            self.accept()


class FirstRunWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bem-vindo ao Coban Archive")
        self.setMinimumWidth(620)
        self.folders = {
            "music_folders": "", "video_folders": "", "game_folders": "",
            "cd_folders": "", "gallery_folders": "",
        }
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(10)
        title = QLabel("🎵  Bem-vindo ao Coban Archive")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)
        subtitle = QLabel(
            "Configure as pastas da sua biblioteca. Você pode pular e configurar depois.")
        subtitle.setStyleSheet("color: #888; font-size: 12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(10)
        sections = [
            ("music_folders", "🎵 Músicas"), ("cd_folders", "💿 CDs / Álbuns"),
            ("video_folders", "🎬 Vídeos"), ("game_folders", "🎮 Jogos"),
            ("gallery_folders", "🖼 Galeria"),
        ]
        self._inputs = {}
        for key, label in sections:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(140)
            lbl.setStyleSheet("font-weight: bold;")
            field = QLineEdit()
            field.setPlaceholderText("Opcional — deixe em branco para pular")
            btn = QPushButton("Procurar")
            btn.setStyleSheet(BTN_STYLES["primary"])
            btn.clicked.connect(lambda checked=False, k=key: self._browse(k))
            self._inputs[key] = field
            row.addWidget(lbl)
            row.addWidget(field, 1)
            row.addWidget(btn)
            layout.addLayout(row)
        layout.addStretch()
        buttons = QHBoxLayout()
        btn_skip = QPushButton("Configurar depois")
        btn_skip.clicked.connect(self.reject)
        btn_ok = QPushButton("Salvar e continuar")
        btn_ok.setStyleSheet(BTN_STYLES["success"])
        btn_ok.clicked.connect(self._save)
        buttons.addStretch()
        buttons.addWidget(btn_skip)
        buttons.addWidget(btn_ok)
        layout.addLayout(buttons)

    def _browse(self, key):
        folder = QFileDialog.getExistingDirectory(self, "Selecione a pasta", "")
        if folder:
            self._inputs[key].setText(folder)

    def _save(self):
        for key, field in self._inputs.items():
            self.folders[key] = field.text().strip()
        self.accept()


class CobanArchiveHome(QMainWindow):
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

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.stacked_widget = QStackedWidget()
        self.page_explorer = self._create_explorer_page()
        self.page_inicio = self._create_inicio_page()
        self.page_equalizador = self._create_equalizador_page()
        self.page_config = self._create_config_page()
        self.page_galeria = self._create_galeria_page()
        self.page_videos = self._create_videos_page()
        self.page_games = self._create_games_page()
        self.page_cds = self._create_cds_page()

        self.stacked_widget.addWidget(self.page_inicio)
        self.stacked_widget.addWidget(self.page_explorer)
        self.stacked_widget.addWidget(self.page_equalizador)
        self.stacked_widget.addWidget(self.page_galeria)
        self.stacked_widget.addWidget(self.page_config)
        self.stacked_widget.addWidget(self.page_videos)
        self.stacked_widget.addWidget(self.page_games)
        self.stacked_widget.addWidget(self.page_cds)

        self._page_map = {
            "inicio": self.page_inicio, "explorer": self.page_explorer,
            "equalizador": self.page_equalizador, "galeria": self.page_galeria,
            "config": self.page_config, "videos": self.page_videos,
            "games": self.page_games, "cds": self.page_cds,
        }
        self.stacked_widget.currentChanged.connect(self._on_page_changed)

        self.header = QFrame()
        self.header.setObjectName("appHeader")
        self.header.setFixedHeight(78)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(0)

        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setMinimumWidth(0)
        logo_path = self._asset_path("coban_archive.png")
        pix_logo = QPixmap(logo_path)
        if not pix_logo.isNull():
            if pix_logo.hasAlphaChannel():
                try:
                    with Image.open(logo_path) as src:
                        bbox = src.getchannel("A").getbbox()
                    if bbox:
                        pix_logo = pix_logo.copy(bbox[0], bbox[1],
                                                  bbox[2] - bbox[0], bbox[3] - bbox[1])
                except Exception:
                    log.debug("Falha ao recortar logo", exc_info=True)
            self.logo_label.setPixmap(
                pix_logo.scaled(540, 68, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.logo_label.setText("COBAN ARCHIVE")
            self.logo_label.setStyleSheet(
                "font-size: 20px; font-weight: bold; border: none; background: transparent;")

        left_balance = QWidget()
        left_balance.setFixedWidth(150)
        right_balance = QWidget()
        right_balance.setFixedWidth(150)
        header_layout.addWidget(left_balance)
        header_layout.addWidget(self.logo_label, 1)
        header_layout.addWidget(right_balance)

        self.body_layout = QHBoxLayout()
        body_layout = self.body_layout

        self.sidebar = QFrame()
        self.sidebar.setObjectName("appSidebar")
        self.sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 14, 10, 12)
        sidebar_layout.setSpacing(8)
        sidebar_layout.setAlignment(Qt.AlignTop)

        category_row = QVBoxLayout()
        category_row.setSpacing(6)
        self.sidebar_buttons = {}
        for key, label in (("navegacao", "  Navegação"), ("opcoes", "  Opções")):
            button = self._create_sidebar_btn(label)
            button.clicked.connect(
                lambda checked=False, section=key: self._set_sidebar_section(section))
            self.sidebar_buttons[key] = button
            category_row.addWidget(button)
        sidebar_layout.addLayout(category_row)

        self.sidebar_separator = QFrame()
        self.sidebar_separator.setObjectName("sidebarSeparator")
        self.sidebar_separator.setFrameShape(QFrame.HLine)
        sidebar_layout.addWidget(self.sidebar_separator)
        self.sidebar_submenu = QVBoxLayout()
        self.sidebar_submenu.setSpacing(4)
        sidebar_layout.addLayout(self.sidebar_submenu)
        sidebar_layout.addStretch(1)

        body_layout.addWidget(self.stacked_widget, stretch=1)
        body_layout.addWidget(self.sidebar)

        self._build_footer(main_layout)

        main_layout.insertWidget(0, self.header)
        main_layout.insertLayout(1, body_layout, stretch=1)

        if self.app_config.get("sidebar_side", "right") == "left":
            self.body_layout.removeWidget(self.sidebar)
            self.body_layout.removeWidget(self.stacked_widget)
            self.body_layout.addWidget(self.sidebar)
            self.body_layout.addWidget(self.stacked_widget, stretch=1)

        last_page_key = self.app_config.get("last_page", "inicio")
        self.stacked_widget.setCurrentWidget(self._page_map.get(last_page_key, self.page_inicio))

        self._current_sidebar_section = "navegacao"
        self._set_sidebar_section("navegacao")
        self._update_theme_dynamic()
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

    def _setup_tray_icon(self):
        self._tray_icon = None
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                log.info("System tray não disponível")
                return
            self._tray_icon = QSystemTrayIcon(self)
            self._tray_icon.setIcon(self._get_tray_icon())
            self._tray_icon.setToolTip("Coban Archive")
            menu = QMenu()
            self._tray_play_action = menu.addAction("▶  Tocar")
            self._tray_play_action.triggered.connect(self._toggle_play)
            menu.addAction("⏭  Próxima", self._play_next_track)
            menu.addAction("⏮  Anterior", self._play_prev_track)
            menu.addSeparator()
            menu.addAction("🔍  Busca Global (Ctrl+K)", self._open_global_search)
            menu.addAction("📂  Mostrar Janela", self._show_from_tray)
            menu.addSeparator()
            menu.addAction("❌  Sair", self._quit_app)
            self._tray_icon.setContextMenu(menu)
            self._tray_icon.activated.connect(self._on_tray_activated)
            self._tray_icon.show()
            log.info("Tray icon ativado")
        except Exception:
            log.exception("Falha ao criar tray icon")
            self._tray_icon = None

    def _get_tray_icon(self):
        icon = self._icon("coban_archive_app.png")
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        return icon

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self):
        if self._tray_icon:
            self._tray_icon.hide()
        self.close()
        QApplication.instance().quit()

    def _update_tray_play_action(self):
        if not self._tray_icon or not hasattr(self, "_tray_play_action"):
            return
        self._tray_play_action.setText("⏸  Pausar" if self.is_playing else "▶  Tocar")

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

    def _show_first_run_wizard(self):
        if self._shutting_down:
            return
        wizard = FirstRunWizard(self)
        if wizard.exec() == QDialog.Accepted:
            for key, folder in wizard.folders.items():
                if folder and os.path.isdir(folder):
                    folders = list(self.app_config.get(key, []))
                    if not folders:
                        folders = [folder]
                    else:
                        folders[0] = folder
                    self.app_config[key] = folders[:5]
                    if key == "music_folders" and not self.app_config.get("initial_folder"):
                        self.app_config["initial_folder"] = folder
            self._save_config()
            self._refresh_watchers()
            self._dirty = {k: True for k in self._dirty}
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
        self.app_config["first_run_completed"] = True
        self._save_config()

    def _open_global_search(self):
        dlg = GlobalSearchDialog(self.db, self)
        if dlg.exec() == QDialog.Accepted and dlg.selected_kind and dlg.selected_data:
            kind = dlg.selected_kind
            row = dlg.selected_data
            if kind == "tracks":
                self._play_single_audio(row["path"])
            elif kind == "albums":
                self._play_cd_album(row["folder"])
            elif kind == "videos":
                self.stacked_widget.setCurrentWidget(self.page_videos)
                self._play_single_video(row["path"])
            elif kind == "games":
                self._open_game(row["path"])

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

    def _show_card_menu(self, file_path, global_pos, is_audio=False, is_video=False):
        menu = QMenu(self)
        if is_audio:
            menu.addAction("▶  Tocar agora", lambda: self._play_single_audio(file_path))
        if is_video:
            menu.addAction("▶  Assistir", lambda: self._play_single_video(file_path))
        menu.addSeparator()
        menu.addAction(
            "📂  Abrir pasta",
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(
                os.path.dirname(file_path) or file_path)))
        menu.addAction(
            "📋  Copiar caminho",
            lambda: QApplication.clipboard().setText(file_path))
        menu.addSeparator()
        menu.addAction("ℹ  Propriedades", lambda: self._show_file_properties(file_path))
        menu.exec(global_pos)

    def _show_folder_menu(self, folder_path, global_pos, first_audio=None):
        menu = QMenu(self)
        if first_audio:
            menu.addAction("▶  Tocar álbum", lambda: self._play_cd_album(folder_path))
        menu.addSeparator()
        menu.addAction("📂  Abrir pasta",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path)))
        menu.addAction("📋  Copiar caminho",
                       lambda: QApplication.clipboard().setText(folder_path))
        menu.exec(global_pos)

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

    def _show_file_properties(self, path):
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Arquivo não encontrado", f"O arquivo não existe mais:\n{path}")
            return
        try:
            st = os.stat(path)
        except OSError as e:
            QMessageBox.warning(self, "Erro", str(e))
            return
        size_mb = st.st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M:%S")
        lines = [
            f"<b>{os.path.basename(path)}</b>", "",
            f"<b>Caminho:</b> {path}",
            f"<b>Tamanho:</b> {size_mb:.2f} MB",
            f"<b>Modificado:</b> {mtime}",
        ]
        if MUTAGEN_AVAILABLE and path.lower().endswith(AUDIO_EXTS):
            try:
                audio = mutagen.File(path, easy=True)
                if audio:
                    for tag in ("title", "artist", "album", "date", "tracknumber"):
                        val = audio.get(tag)
                        if val:
                            v = val[0] if isinstance(val, list) else val
                            lines.append(f"<b>{tag.capitalize()}:</b> {v}")
            except Exception:
                pass
        QMessageBox.information(self, "Propriedades", "<br>".join(lines))

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

    def _show_about_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Sobre o Coban Archive")
        dlg.setMinimumWidth(500)
        dlg.setStyleSheet(f"""
            QDialog {{ background-color: {self.theme_colors['bg_main']}; }}
            QLabel {{ color: {self.theme_colors['text']}; background: transparent; }}
            QLabel#aboutVersion {{ color: {self.theme_colors['text_sec']}; font-size: 13px; }}
            QLabel#aboutLink a {{ color: #4DA6FF; text-decoration: none; }}
        """)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(30, 30, 30, 20)
        layout.setSpacing(12)
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        logo_pix = QPixmap(self._asset_path("coban_archive.png"))
        if logo_pix.isNull():
            logo_pix = QPixmap(self._asset_path("coban_archive_app.png"))
        if not logo_pix.isNull():
            logo_label.setPixmap(
                logo_pix.scaled(360, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(logo_label)
        version = QLabel(f"Versão {APP_VERSION}")
        version.setObjectName("aboutVersion")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)
        desc = QLabel(APP_DESCRIPTION)
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc)
        layout.addSpacing(10)
        link = QLabel(f'<a href="{GITHUB_URL}">🐙 {GITHUB_URL}</a>')
        link.setObjectName("aboutLink")
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignCenter)
        layout.addWidget(link)
        tech = QLabel("<small>Tecnologias: Python · PySide6 · SQLite · Mutagen · Pillow</small>")
        tech.setStyleSheet(f"color: {self.theme_colors['text_sec']};")
        tech.setAlignment(Qt.AlignCenter)
        layout.addWidget(tech)
        layout.addSpacing(10)
        btn_close = QPushButton("Fechar")
        btn_close.setStyleSheet(BTN_STYLES["primary"])
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignCenter)
        dlg.exec()

    def _setup_shortcuts(self):
        self._shortcuts = []

        def add(key, callback):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(callback)
            self._shortcuts.append(sc)

        add(Qt.Key_MediaPlay, self._toggle_play)
        add(Qt.Key_MediaNext, self._play_next_track)
        add(Qt.Key_MediaPrevious, self._play_prev_track)
        add("Ctrl+Space", self._toggle_play)
        add("Ctrl+Right", self._seek_forward)
        add("Ctrl+Left", self._seek_backward)
        add("Ctrl+Up", self._volume_up)
        add("Ctrl+Down", self._volume_down)
        add("Ctrl+N", self._play_next_track)
        add("Ctrl+B", self._play_prev_track)
        add("Ctrl+M", self._toggle_mute)
        add("Ctrl+F", self._focus_search)
        add("Ctrl+K", self._open_global_search)
        add("F11", self._toggle_video_fullscreen)

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

    def _asset_path(self, filename):
        candidates = (
            os.path.join(self.script_dir, "assets", "icons", filename),
            os.path.join(self.script_dir, filename),
        )
        for path in candidates:
            if os.path.isfile(path):
                return path
        return candidates[0]

    def _icon(self, filename):
        path = self._asset_path(filename)
        return QIcon(path) if os.path.isfile(path) else QIcon()

    def _icon_pixmap(self, filename, size):
        cache = self.__dict__.setdefault("_icon_pix_cache", {})
        key = (filename, size)
        if key not in cache:
            path = self._asset_path(filename)
            if os.path.isfile(path):
                cache[key] = QPixmap(path).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            else:
                cache[key] = QPixmap()
        return cache[key]

    def _set_placeholder_icon(self, label, filename, size, fallback_text=""):
        pix = self._icon_pixmap(filename, size)
        if pix.isNull():
            label.setText(fallback_text)
        else:
            label.setPixmap(pix)

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

    def _apply_theme(self):
        theme = self.app_config.get("theme", "dark")
        if theme == "light":
            c = {
                "bg_main": "#F0F0F0", "bg_header": "#E4E4E4", "bg_sidebar": "#EBEBEB",
                "bg_footer": "#E4E4E4", "bg_card": "#FFFFFF", "border": "#CCCCCC",
                "text": "#111111", "text_sec": "#555555", "input_bg": "#FFFFFF",
                "tree_bg": "#F0F0F0", "video_bg": "#F0F0F0", "video_list_border": "#CCCCCC",
                "video_item_bg": "#FFFFFF", "video_item_text": "#111111",
                "video_item_border": "#E2E2E2", "video_item_hover": "#E8E8E8",
                "video_sel_bg": "#FBF6B8", "video_sel_text": "#4A4600",
                "video_scroll_handle": "#BDBDBD", "video_scroll_hover": "#9A9A9A",
                "video_groove": "#CFCFCF", "video_status": "#666666",
            }
        else:
            c = {
                "bg_main": "#121212", "bg_header": "#1E1E1E", "bg_sidebar": "#181818",
                "bg_footer": "#222222", "bg_card": "#1E1E1E", "border": "#333333",
                "text": "#FFFFFF", "text_sec": "#AAAAAA", "input_bg": "#222222",
                "tree_bg": "#121212", "video_bg": "#101010", "video_list_border": "#242424",
                "video_item_bg": "#151515", "video_item_text": "#EAEAEA",
                "video_item_border": "#202020", "video_item_hover": "#202020",
                "video_sel_bg": "#34310D", "video_sel_text": "#FFF58A",
                "video_scroll_handle": "#3A3A3A", "video_scroll_hover": "#666666",
                "video_groove": "#303030", "video_status": "#999999",
            }
        self.theme_colors = c
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {c['bg_main']}; color: {c['text']}; font-family: 'Segoe UI', Arial, sans-serif; }}
            QWidget {{ color: {c['text']}; }}
            QStackedWidget {{ background-color: {c['bg_main']}; }}
            QScrollArea {{ border: none; background-color: transparent; }}
            QScrollArea > QWidget > QWidget {{ background-color: transparent; }}
            QFrame {{ background-color: transparent; }}
            QLabel {{ color: {c['text']}; background: transparent; }}
            QCheckBox {{ color: {c['text']}; background: transparent; }}
            QFrame#appHeader {{ background-color: {c['bg_header']}; border: none; }}
            QFrame#appSidebar {{ background-color: {c['bg_sidebar']}; border: none; }}
            QFrame#appFooter {{ background-color: {c['bg_footer']}; border: none; }}
            QFrame#videosPage {{ background-color: {c['video_bg']}; border: none; }}
            QFrame#sidebarSeparator {{ color: {c['border']}; margin: 8px 0; }}
            QLabel#nowPlayingTitle {{ font-size: 14px; font-weight: bold; color: {c['text']}; border: none; }}
            QLabel#nowPlayingArtist {{ font-size: 12px; color: {c['text_sec']}; border: none; }}
            QLabel#playerTimeLabel {{ border: none; font-size: 11px; color: {c['text_sec']}; }}
            QLabel#configLabel {{ font-size: 14px; font-weight: bold; border: none; color: {c['text']}; }}
            QLabel#configTitle {{ font-size: 24px; font-weight: bold; margin-bottom: 30px; border: none; color: {c['text']}; }}
            QLabel#configSection {{ font-size: 14px; font-weight: bold; margin-top: 20px; border: none; color: {c['text']}; }}
            QLabel#pageTitle {{ font-size: 20px; font-weight: bold; border: none; color: {c['text']}; }}
            QLabel#pageSubtitle {{ font-size: 18px; font-weight: bold; border: none; color: {c['text']}; }}
            QLabel#infoLabel {{ font-size: 14px; color: {c['text_sec']}; border: none; }}
            QComboBox {{ background-color: {c['input_bg']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 6px; }}
            QComboBox QAbstractItemView {{ background-color: {c['input_bg']}; color: {c['text']}; selection-background-color: #0078D7; border: 1px solid {c['border']}; }}
            QComboBox::drop-down {{ border: 0px; width: 0px; }}
            QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
            QLineEdit {{ background-color: {c['input_bg']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 4px; padding: 6px; }}
            QLineEdit#searchInput {{ border-radius: 6px; padding: 0 12px; font-size: 13px; }}
            QLineEdit#searchInput:focus {{ border: 1px solid #0078D7; }}
            QLineEdit#folderInput {{ padding: 7px; border-radius: 5px; }}
            QListWidget#musicList {{ background: transparent; border: none; outline: none; color: {c['text']}; }}
            QListWidget#musicList::item {{ padding: 10px 14px; border: none; border-radius: 6px; margin-bottom: 3px; color: {c['text']}; }}
            QListWidget#musicList::item:hover {{ background-color: rgba(128, 128, 128, 0.1); }}
            QListWidget#musicList::item:selected {{ background-color: #0078D7; color: white; }}
            QSlider#mediaSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border: none; }}
            QSlider#mediaSlider::handle:horizontal {{ background: #0078D7; width: 10px; margin: -3px 0; border-radius: 5px; }}
            QTabWidget::pane {{ border: 1px solid {c['border']}; background-color: transparent; }}
            QTabBar::tab {{ padding: 10px 20px; border: 1px solid {c['border']}; background-color: {c['bg_card']}; color: {c['text']}; }}
            QTabBar::tab:selected {{ background-color: {c['bg_main']}; }}
        """)
        self._apply_video_theme()
        self._update_nav_icons()
        self._update_shuffle_button()
        self._update_repeat_button()

    def _apply_video_theme(self):
        if not hasattr(self, "video_list"):
            return
        c = self.theme_colors
        self.video_list.setStyleSheet(f"""
            QListWidget {{ background-color: {c['video_bg']}; color: {c['video_item_text']};
                         border: 1px solid {c['video_list_border']}; border-radius: 6px;
                         padding: 4px; outline: none; }}
            QListWidget::item {{ background-color: {c['video_item_bg']}; color: {c['video_item_text']};
                               padding: 7px 6px; border-bottom: 1px solid {c['video_item_border']}; }}
            QListWidget::item:hover {{ background-color: {c['video_item_hover']}; }}
            QListWidget::item:selected {{ background-color: {c['video_sel_bg']};
                                        color: {c['video_sel_text']};
                                        border-left: 3px solid #C9C819; }}
            QScrollBar:vertical {{ background: {c['video_bg']}; width: 9px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: {c['video_scroll_handle']};
                                         min-height: 24px; border-radius: 4px; }}
            QScrollBar::handle:vertical:hover {{ background: {c['video_scroll_hover']}; }}
            QScrollBar:horizontal {{ background: {c['video_bg']}; height: 9px; margin: 2px; }}
            QScrollBar::handle:horizontal {{ background: {c['video_scroll_handle']};
                                           min-width: 24px; border-radius: 4px; }}
            QScrollBar::handle:horizontal:hover {{ background: {c['video_scroll_hover']}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
        """)
        self.video_status.setStyleSheet(f"color: {c['video_status']}; border: none;")
        self.video_progress_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ height: 5px; background: {c['video_groove']}; "
            "border-radius: 2px; } "
            "QSlider::sub-page:horizontal { background: #C9C819; border-radius: 2px; } "
            "QSlider::handle:horizontal { background: #C9C819; width: 13px; "
            "margin: -5px 0; border-radius: 6px; }")
        self.video_widget.set_background_color(c["video_bg"])

    def _nav_icon_path(self, name):
        variant = "claro" if self.app_config.get("theme", "dark") == "light" else "escuro"
        return self._asset_path(f"{name}_icon_{variant}.png")

    def _update_nav_icons(self):
        if not hasattr(self, "btn_prev"):
            return
        playing = getattr(self, "is_playing", False)
        for btn, name in ((self.btn_prev, "anterior"),
                          (self.btn_play, "pausa" if playing else "play"),
                          (self.btn_next, "proximo")):
            path = self._nav_icon_path(name)
            if os.path.isfile(path):
                btn.setIcon(QIcon(path))

    def _update_theme_dynamic(self):
        self._apply_theme()
        if hasattr(self, "_current_sidebar_section"):
            self._set_sidebar_section(self._current_sidebar_section)

    def _set_sidebar_section(self, section):
        self._current_sidebar_section = section
        c = self.theme_colors
        while self.sidebar_submenu.count():
            item = self.sidebar_submenu.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for key, button in self.sidebar_buttons.items():
            active = key == section
            if active:
                bg, bd, txt = "#075985", "#0284C7", "#FFFFFF"
            else:
                bg, bd, txt = c["bg_card"], c["border"], c["text"]
            button.setStyleSheet(
                f"text-align: left; padding: 11px 12px; background: {bg}; "
                f"color: {txt}; border: 1px solid {bd}; border-radius: 6px; "
                f"font-size: 14px; font-weight: {'bold' if active else 'normal'};")
        
        # Mapeamento dos ícones do topo
        for key, btn in self.sidebar_buttons.items():
            if key == "navegacao":
                btn.setIcon(self._icon("navegacao_icon.png"))
            elif key == "opcoes":
                btn.setIcon(self._icon("opcao_icon.png"))
            btn.setIconSize(QSize(20, 20))

        if section == "opcoes":
            entries = [
                ("Equalizador", lambda: self.stacked_widget.setCurrentWidget(self.page_equalizador), "config_icon.png"),
                ("Configurações", lambda: self.stacked_widget.setCurrentWidget(self.page_config), "config_icon.png"),
                ("Sobre", self._show_about_dialog, "sobre_icon.png"),
            ]
        else:
            entries = [
                ("Início", lambda: self.stacked_widget.setCurrentWidget(self.page_inicio), "inicio_icon.png"),
                ("Músicas", self.abrir_pasta_audio, "musica_icon.png"),
                ("CDs (Disk)", self.abrir_cds, "cd_icon.png"),
                ("Vídeos", self.abrir_videos, "filmes_icon.png"),
                ("Jogos", self.abrir_games, "jogos_icon.png"),
                ("Galeria", self._abrir_galeria, "galeria_icon.png"),
            ]
        for label, callback, icon_name in entries:
            button = self._create_sidebar_btn(label)
            if icon_name:
                button.setIcon(self._icon(icon_name))
            else:
                blank = QPixmap(22, 22)
                blank.fill(Qt.transparent)
                button.setIcon(QIcon(blank))
            button.setIconSize(QSize(22, 22))
            button.setStyleSheet(
                f"text-align: left; padding: 10px 12px 10px 18px; "
                f"background: transparent; border: none; border-radius: 4px; "
                f"font-size: 13px; color: {c['text']};")
            button.clicked.connect(callback)
            self.sidebar_submenu.addWidget(button)

    def _create_sidebar_btn(self, text):
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _create_btn(self, text, kind="primary"):
        btn = QPushButton(text)
        btn.setStyleSheet(BTN_STYLES.get(kind, BTN_STYLES["primary"]))
        for prefix, icon_name in BTN_ICONS:
            if text.startswith(prefix):
                btn.setIcon(self._icon(icon_name))
                btn.setIconSize(QSize(18, 18))
                break
        return btn

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

    def _build_footer(self, main_layout):
        self.footer = QFrame()
        self.footer.setObjectName("appFooter")
        self.footer.setFixedHeight(90)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(20, 10, 20, 10)
        footer_layout.setSpacing(10)

        track_info_widget = QWidget()
        track_info_layout = QHBoxLayout(track_info_widget)
        track_info_layout.setContentsMargins(0, 0, 0, 0)
        track_info_layout.setSpacing(10)
        self.lbl_cover = ClickableLabel()
        self.lbl_cover.setFixedSize(60, 60)
        self.lbl_cover.setStyleSheet("background-color: #333; border-radius: 4px;")
        self.lbl_cover.setCursor(Qt.PointingHandCursor)
        self.lbl_cover.clicked.connect(self._show_cover_fullscreen)
        text_info_layout = QVBoxLayout()
        text_info_layout.setAlignment(Qt.AlignVCenter)
        text_info_layout.setContentsMargins(0, 0, 0, 0)
        text_info_layout.setSpacing(2)
        self.lbl_title = QLabel("Nenhuma faixa selecionada")
        self.lbl_title.setObjectName("nowPlayingTitle")
        self.lbl_artist_year = QLabel("Artista - Ano")
        self.lbl_artist_year.setObjectName("nowPlayingArtist")
        text_info_layout.addWidget(self.lbl_title)
        text_info_layout.addWidget(self.lbl_artist_year)
        track_info_layout.addWidget(self.lbl_cover)
        track_info_layout.addLayout(text_info_layout)

        center_container = QWidget()
        center_container_layout = QVBoxLayout(center_container)
        center_container_layout.setContentsMargins(0, 0, 0, 0)
        center_container_layout.setSpacing(4)
        center_container_layout.setAlignment(Qt.AlignCenter)

        controls_layout = QHBoxLayout()
        controls_layout.setAlignment(Qt.AlignCenter)
        controls_layout.setSpacing(10)

        self.btn_shuffle = QPushButton()
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.setChecked(self._shuffle)
        self.btn_shuffle.setFixedSize(30, 30)
        self.btn_shuffle.setCursor(Qt.PointingHandCursor)
        self.btn_shuffle.setToolTip("Aleatório")
        self.btn_shuffle.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.btn_shuffle.toggled.connect(self._on_shuffle_toggled)

        self.btn_prev = QPushButton()
        self.btn_play = QPushButton()
        self.btn_next = QPushButton()

        btn_assets = [(self.btn_prev, "anterior"), (self.btn_play, "play"), (self.btn_next, "proximo")]
        for btn, name in btn_assets:
            btn.setFixedSize(36, 36)
            btn.setCursor(Qt.PointingHandCursor)
            asset_path = self._nav_icon_path(name)
            if os.path.exists(asset_path):
                btn.setIcon(QIcon(asset_path))
                btn.setIconSize(QSize(32, 32))
                btn.setStyleSheet("QPushButton { background-color: transparent; border: none; }")
            else:
                lbl_text = "⏮" if name == "anterior" else "▶" if name == "play" else "⏭"
                btn.setText(lbl_text)
                btn.setStyleSheet("QPushButton { background-color: transparent; font-size: 18px; border: none; } QPushButton:hover { color: #0078D7; }")

        self.btn_repeat = QPushButton()
        self.btn_repeat.setFixedSize(30, 30)
        self.btn_repeat.setCursor(Qt.PointingHandCursor)
        self.btn_repeat.setToolTip("Repetir")
        self.btn_repeat.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.btn_repeat.clicked.connect(self._cycle_repeat_mode)

        controls_layout.addWidget(self.btn_shuffle)
        controls_layout.addWidget(self.btn_prev)
        controls_layout.addWidget(self.btn_play)
        controls_layout.addWidget(self.btn_next)
        controls_layout.addWidget(self.btn_repeat)

        self._update_shuffle_button()
        self._update_repeat_button()

        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_next.clicked.connect(self._play_next_track)
        self.btn_prev.clicked.connect(self._play_prev_track)

        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_time_cur = QLabel("00:00")
        self.lbl_time_cur.setObjectName("playerTimeLabel")
        self.slider_progress = QSlider(Qt.Horizontal)
        self.slider_progress.setObjectName("mediaSlider")
        self.slider_progress.sliderMoved.connect(self._set_position)
        self.lbl_time_tot = QLabel("00:00")
        self.lbl_time_tot.setObjectName("playerTimeLabel")
        progress_layout.addWidget(self.lbl_time_cur)
        progress_layout.addWidget(self.slider_progress, stretch=1)
        progress_layout.addWidget(self.lbl_time_tot)
        center_container_layout.addLayout(controls_layout)
        center_container_layout.addLayout(progress_layout)

        volume_widget = QWidget()
        volume_layout = QHBoxLayout(volume_widget)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(8)
        lbl_volume_icon = QLabel()
        self._set_placeholder_icon(lbl_volume_icon, "volume_icon.png", 28, "🔊")
        lbl_volume_icon.setStyleSheet("border: none; background: transparent;")
        self.slider_volume = QSlider(Qt.Horizontal)
        self.slider_volume.setObjectName("mediaSlider")
        self.slider_volume.setFixedWidth(100)
        self.slider_volume.setRange(0, 100)
        try:
            saved_volume = int(self.app_config.get("volume", 80))
        except (TypeError, ValueError):
            saved_volume = 80
        saved_volume = max(0, min(100, saved_volume))
        self.slider_volume.setValue(saved_volume)
        v = (saved_volume / 100.0) ** 2
        self.audio_output.setVolume(v)
        self.video_audio_output.setVolume(v)
        self.slider_volume.valueChanged.connect(self._on_volume_changed)
        volume_layout.addWidget(lbl_volume_icon)
        volume_layout.addWidget(self.slider_volume)

        footer_layout.addWidget(track_info_widget, stretch=1)
        footer_layout.addWidget(center_container, stretch=2)
        footer_layout.addStretch(1)
        footer_layout.addWidget(volume_widget)
        main_layout.addWidget(self.footer)

    def _on_shuffle_toggled(self, checked):
        self._shuffle = checked
        self._update_shuffle_button()
        self.app_config["shuffle"] = checked

    def _update_shuffle_button(self):
        if not hasattr(self, "btn_shuffle"):
            return
        if self._shuffle:
            self.btn_shuffle.setIcon(self._icon("aleatorio_true_icon.png"))
        else:
            self.btn_shuffle.setIcon(self._icon("aleatorio_false_icon.png"))
        self.btn_shuffle.setIconSize(QSize(24, 24))

    def _cycle_repeat_mode(self):
        idx = REPEAT_MODES.index(self._repeat_mode)
        self._repeat_mode = REPEAT_MODES[(idx + 1) % len(REPEAT_MODES)]
        self._update_repeat_button()
        self.app_config["repeat_mode"] = self._repeat_mode

    def _update_repeat_button(self):
        if not hasattr(self, "btn_repeat"):
            return
        if self._repeat_mode == "off":
            self.btn_repeat.setIcon(self._icon("repetir_false_icon.png"))
        else:
            self.btn_repeat.setIcon(self._icon("repetindo_true_icon.png"))
        
        # Optional: adjust tooltip to indicate mode
        if self._repeat_mode == "one":
            self.btn_repeat.setToolTip("Repetir: Faixa Atual")
        elif self._repeat_mode == "all":
            self.btn_repeat.setToolTip("Repetir: Tudo")
        else:
            self.btn_repeat.setToolTip("Repetir: Desligado")
        self.btn_repeat.setIconSize(QSize(24, 24))

    def _on_volume_changed(self, value):
        v = (value / 100.0) ** 2
        self.audio_output.setVolume(v)
        self.video_audio_output.setVolume(v)
        if not self._shutting_down:
            self.app_config["volume"] = int(value)

    def _create_inicio_page(self):
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        title = QLabel("Bem-vindo ao Coban Archive")
        title.setObjectName("configTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        hint = QLabel("Ctrl+K para busca global  ·  Ctrl+Space para play/pause")
        hint.setStyleSheet("color: #888; margin-top: 12px;")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)
        return page

    def _create_videos_page(self):
        page = QFrame()
        page.setObjectName("videosPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        top = QHBoxLayout()
        title = QLabel("Vídeos")
        title.setObjectName("pageTitle")
        self.video_status = QLabel("Escolha um vídeo para assistir")
        refresh = self._create_btn("Atualizar", kind="warning")
        refresh.clicked.connect(lambda: self._refresh_video_list(force_scan=True))
        top.addWidget(title)
        top.addWidget(self.video_status, 1)
        top.addWidget(refresh)
        layout.addLayout(top)

        self.video_content_layout = QHBoxLayout()
        self.video_widget = VideoPlayerWidget()
        self.video_widget.setMinimumSize(320, 240)
        self.video_widget.toggle_fullscreen_requested.connect(self._toggle_video_fullscreen)
        overlay_path = os.path.join(self.script_dir, "assets", "retro_tv_overlay.png")
        self.video_widget.set_overlay_pixmap(QPixmap(overlay_path))
        self.video_widget.setMediaPlayer(self.video_player)
        self.video_content_layout.addWidget(self.video_widget, 3)

        right = QVBoxLayout()
        self.video_list = QListWidget()
        self.video_list.itemDoubleClicked.connect(self._play_selected_video)
        self.video_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.video_list.customContextMenuRequested.connect(self._on_video_context_menu)
        right.addWidget(self.video_list, 1)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.video_play_btn = self._create_btn("Assistir / Retomar", kind="warning")
        self.video_play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.video_play_btn.setIconSize(QSize(18, 18))
        self.video_play_btn.clicked.connect(self._play_selected_video)

        self.video_pause_btn = self._create_btn("Pausar", kind="warning")
        self.video_pause_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.video_pause_btn.setIconSize(QSize(18, 18))
        self.video_pause_btn.setEnabled(False)
        self.video_pause_btn.clicked.connect(self.video_player.pause)
        controls.addWidget(self.video_play_btn, 2)
        controls.addWidget(self.video_pause_btn, 1)
        right.addLayout(controls)
        self.video_content_layout.addLayout(right, 2)
        layout.addLayout(self.video_content_layout, 1)

        self.video_progress_slider = QSlider(Qt.Horizontal)
        self.video_progress_slider.setRange(0, 0)
        self.video_progress_slider.sliderMoved.connect(self.video_player.setPosition)
        layout.addWidget(self.video_progress_slider)

        self.video_player.durationChanged.connect(
            lambda duration: self.video_progress_slider.setRange(0, max(0, duration)))
        self.video_player.positionChanged.connect(self._update_video_slider)
        self.video_player.playbackStateChanged.connect(self._on_video_playback_state_changed)
        self._apply_video_theme()
        self._refresh_video_list()
        return page

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

    def _create_games_page(self):
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        toolbar = QHBoxLayout()
        title = QLabel("Jogos")
        title.setObjectName("pageSubtitle")
        self.lbl_game_path = QLabel("Nenhuma pasta selecionada")
        self.lbl_game_path.setObjectName("infoLabel")
        btn_refresh = self._create_btn("Atualizar")
        btn_refresh.clicked.connect(lambda: self.carregar_games_grid(force_scan=True))
        toolbar.addWidget(title)
        toolbar.addWidget(self.lbl_game_path, stretch=1)
        toolbar.addWidget(btn_refresh)
        layout.addLayout(toolbar)

        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 5, 0, 10)
        self.input_search_game = QLineEdit()
        self.input_search_game.setObjectName("searchInput")
        self.input_search_game.setPlaceholderText("🔍 Pesquisar jogo...")
        self.input_search_game.setFixedHeight(36)
        self._search_game_debounce = QTimer(self)
        self._search_game_debounce.setSingleShot(True)
        self._search_game_debounce.setInterval(250)
        self._search_game_debounce.timeout.connect(self._execute_game_search)
        self.input_search_game.textChanged.connect(lambda _: self._search_game_debounce.start())
        search_layout.addWidget(self.input_search_game)
        layout.addLayout(search_layout)

        self.scroll_games = QScrollArea()
        self.scroll_games.setWidgetResizable(True)
        self.scroll_games.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_games.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_games.setStyleSheet(self._modern_scrollbar_style())
        self.games_content = QWidget()
        self.games_content.setStyleSheet("background: transparent; border: none;")
        self.games_grid = QGridLayout(self.games_content)
        self.games_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.games_grid.setContentsMargins(0, 0, 0, 0)
        self.games_grid.setSpacing(16)
        self.scroll_games.setWidget(self.games_content)
        layout.addWidget(self.scroll_games, stretch=1)
        return page

    def _execute_game_search(self):
        self._filter_game_list(self.input_search_game.text())

    def carregar_games_grid(self, force_scan=False):
        self.games_initialized = True
        self._cover_cache = {}
        self._cover_to_game = {}
        configured, folders, dead = self._folders_status("game_folders")
        while self.games_grid.count():
            item = self.games_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.game_thumb_refs.clear()
        self.lbl_game_path.setText(
            f"{len(folders)} pasta(s) OK · ⚠ {len(dead)} inacessível(is)" if dead
            else f"{len(folders)} diretório(s) configurado(s)")
        if not configured:
            lbl = QLabel("Configure até 5 diretórios válidos nas Opções.")
            lbl.setObjectName("infoLabel")
            self.games_grid.addWidget(lbl, 0, 0)
            return
        cached = self.db.get_games(configured) if self.db.is_ready() else []
        if cached and not force_scan and not self._dirty["games"]:
            self._on_games_scanned(cached, self._game_scan_gen)
            return
        if not cached and not dead:
            lbl = QLabel("Lendo pasta de jogos em background...")
            lbl.setObjectName("infoLabel")
            self.games_grid.addWidget(lbl, 0, 0)
        self._dirty["games"] = False
        if not folders:
            if cached:
                self._on_games_scanned(cached, self._game_scan_gen)
            else:
                lbl = QLabel("⚠ Nenhuma pasta acessível.")
                lbl.setObjectName("infoLabel")
                self.games_grid.addWidget(lbl, 0, 0)
            return
        self._game_scan_gen += 1
        gen = self._game_scan_gen
        if self._game_scanner is not None and self._game_scanner.isRunning():
            self._game_scanner.requestInterruption()
        self._game_scanner = ScannerThread(folders, GAME_EXTS, False, db=self.db, kind="games")
        self._game_scanner.finished_scan.connect(
            lambda results, g=gen: self._on_games_scanned(results, g))
        self._game_scanner.start()

    def _on_games_scanned(self, results, gen):
        if self._shutting_down or gen != self._game_scan_gen:
            return
        while self.games_grid.count():
            item = self.games_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.all_game_tracks = results
        self.filtered_game_tracks = list(self.all_game_tracks)
        self.input_search_game.blockSignals(True)
        self.input_search_game.clear()
        self.input_search_game.blockSignals(False)
        if not self.all_game_tracks:
            lbl = QLabel("Nenhum jogo encontrado nestas pastas.")
            lbl.setObjectName("infoLabel")
            self.games_grid.addWidget(lbl, 0, 0)
            return
        self.game_loaded_count = 0
        self._append_games_batch()

    def _filter_game_list(self, query):
        query = query.lower().strip()
        if not query:
            self.filtered_game_tracks = list(self.all_game_tracks)
        else:
            self.filtered_game_tracks = [
                t for t in self.all_game_tracks if query in os.path.basename(t).lower()]
        sb = self.scroll_games.verticalScrollBar()
        pos = sb.value()
        while self.games_grid.count():
            item = self.games_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.game_thumb_refs.clear()
        self.game_loaded_count = 0
        self._append_games_batch()
        QTimer.singleShot(0, lambda s=sb, p=pos: s.setValue(p))

    def _append_games_batch(self):
        if self._shutting_down:
            return
        for i in range(self.games_grid.count()):
            item = self.games_grid.itemAt(i)
            if (item and item.widget() and isinstance(item.widget(), QPushButton)
                    and item.widget().text().startswith("Carregar mais")):
                item.widget().deleteLater()
        start_idx = self.game_loaded_count
        end_idx = min(start_idx + 40, len(self.filtered_game_tracks))
        max_cols = 4
        c = self.theme_colors
        for idx in range(start_idx, end_idx):
            game_path = self.filtered_game_tracks[idx]
            card = QFrame()
            card.setFixedSize(220, 260)
            card.setStyleSheet("background-color: transparent; border: none;")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(6)
            lbl_thumb = ClickableLabel()
            lbl_thumb.setFixedSize(220, 200)
            lbl_thumb.setAlignment(Qt.AlignCenter)
            lbl_thumb.setCursor(Qt.PointingHandCursor)
            self._set_placeholder_icon(lbl_thumb, "jogos_icon.png", 96, "🎮")
            lbl_thumb.setStyleSheet(
                "font-size: 50px; background-color: #1e1e1e; border-radius: 8px; color: #555;")
            self.game_thumb_refs[game_path] = lbl_thumb
            lbl_thumb.doubleClicked.connect(lambda p=game_path: self._open_game(p))
            lbl_thumb.rightClicked.connect(
                lambda p=game_path: self._show_card_menu(p, QCursor.pos()))
            filename = os.path.basename(game_path)
            track_title, _ = os.path.splitext(filename)
            lbl_name = QLabel(track_title)
            lbl_name.setAlignment(Qt.AlignCenter)
            lbl_name.setWordWrap(True)
            lbl_name.setStyleSheet(
                f"font-size: 12px; font-weight: bold; color: {c['text']}; border: none;")
            card_layout.addWidget(lbl_thumb)
            card_layout.addWidget(lbl_name)
            row = idx // max_cols
            col = idx % max_cols
            self.games_grid.addWidget(card, row, col)
            cover_path = self._find_cover_for_rom(game_path)
            if cover_path:
                self._cover_to_game[cover_path] = game_path
                worker = ThumbnailWorker(cover_path, self.thumb_cache, is_music=False, target_size=(220, 200))
                worker.signals.result.connect(self._on_game_thumb_ready)
                self.threadpool.start(worker)
        self.game_loaded_count = end_idx
        if self.game_loaded_count < len(self.filtered_game_tracks):
            restantes = len(self.filtered_game_tracks) - self.game_loaded_count
            btn_more = self._create_btn(f"Carregar mais (+40 jogos - Restam {restantes})")
            btn_more.clicked.connect(self._append_games_batch)
            total_rows = (len(self.filtered_game_tracks) + max_cols - 1) // max_cols
            self.games_grid.addWidget(btn_more, total_rows + 1, 0, 1, max_cols, Qt.AlignCenter)

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
        game_path = self._cover_to_game.get(cover_path)
        if not game_path:
            return
        lbl = self.game_thumb_refs.get(game_path)
        if lbl and not qimg.isNull():
            lbl.setPixmap(QPixmap.fromImage(qimg))
            lbl.setStyleSheet("background-color: transparent; border-radius: 8px;")

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

    def _create_cds_page(self):
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        toolbar = QHBoxLayout()
        title = QLabel("CDs (Disk)")
        title.setObjectName("pageSubtitle")
        self.lbl_cd_path = QLabel("Nenhuma pasta selecionada")
        self.lbl_cd_path.setObjectName("infoLabel")
        btn_refresh = self._create_btn("Atualizar")
        btn_refresh.clicked.connect(lambda: self.carregar_cds_grid(force_scan=True))
        toolbar.addWidget(title)
        toolbar.addWidget(self.lbl_cd_path, stretch=1)
        toolbar.addWidget(btn_refresh)
        layout.addLayout(toolbar)

        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 5, 0, 10)
        self.input_search_cd = QLineEdit()
        self.input_search_cd.setObjectName("searchInput")
        self.input_search_cd.setPlaceholderText("🔍 Pesquisar álbum...")
        self.input_search_cd.setFixedHeight(36)
        self._search_cd_debounce = QTimer(self)
        self._search_cd_debounce.setSingleShot(True)
        self._search_cd_debounce.setInterval(250)
        self._search_cd_debounce.timeout.connect(self._execute_cd_search)
        self.input_search_cd.textChanged.connect(lambda _: self._search_cd_debounce.start())
        search_layout.addWidget(self.input_search_cd)
        layout.addLayout(search_layout)

        self.scroll_cds = QScrollArea()
        self.scroll_cds.setWidgetResizable(True)
        self.scroll_cds.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_cds.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_cds.setStyleSheet(self._modern_scrollbar_style())
        self.cds_content = QWidget()
        self.cds_content.setStyleSheet("background: transparent; border: none;")
        self.cds_grid = QGridLayout(self.cds_content)
        self.cds_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.cds_grid.setContentsMargins(0, 0, 0, 0)
        self.cds_grid.setSpacing(16)
        self.scroll_cds.setWidget(self.cds_content)
        layout.addWidget(self.scroll_cds, stretch=1)
        return page

    def _execute_cd_search(self):
        self._filter_cd_list(self.input_search_cd.text())

    def carregar_cds_grid(self, force_scan=False):
        self.cds_initialized = True
        self._cd_cover_to_folder = {}
        configured, folders, dead = self._folders_status("cd_folders")
        while self.cds_grid.count():
            item = self.cds_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cd_thumb_refs.clear()
        self.lbl_cd_path.setText(
            f"{len(folders)} pasta(s) OK · ⚠ {len(dead)} inacessível(is)" if dead
            else f"{len(folders)} diretório(s) configurado(s)")
        if not configured:
            lbl = QLabel("Configure até 5 diretórios válidos nas Opções.")
            lbl.setObjectName("infoLabel")
            self.cds_grid.addWidget(lbl, 0, 0)
            return
        cached = self.db.get_albums(configured) if self.db.is_ready() else []
        if cached and not force_scan and not self._dirty["albums"]:
            self._on_cds_scanned(cached, self._cd_scan_gen)
            return
        if not cached and not dead:
            lbl = QLabel("Lendo CDs em background...")
            lbl.setObjectName("infoLabel")
            self.cds_grid.addWidget(lbl, 0, 0)
        self._dirty["albums"] = False
        if not folders:
            if cached:
                self._on_cds_scanned(cached, self._cd_scan_gen)
            else:
                lbl = QLabel("⚠ Nenhuma pasta acessível.")
                lbl.setObjectName("infoLabel")
                self.cds_grid.addWidget(lbl, 0, 0)
            return
        self._cd_scan_gen += 1
        gen = self._cd_scan_gen
        if self._cd_scanner is not None and self._cd_scanner.isRunning():
            self._cd_scanner.requestInterruption()
        self._cd_scanner = CDScannerThread(folders, db=self.db)
        self._cd_scanner.finished_scan.connect(
            lambda results, g=gen: self._on_cds_scanned(results, g))
        self._cd_scanner.start()

    def _on_cds_scanned(self, results, gen):
        if self._shutting_down or gen != self._cd_scan_gen:
            return
        while self.cds_grid.count():
            item = self.cds_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.all_cds = results
        self.filtered_cds = list(self.all_cds)
        self.input_search_cd.blockSignals(True)
        self.input_search_cd.clear()
        self.input_search_cd.blockSignals(False)
        if not self.all_cds:
            lbl = QLabel("Nenhum CD (álbum) encontrado nestas pastas.")
            lbl.setObjectName("infoLabel")
            self.cds_grid.addWidget(lbl, 0, 0)
            return
        self.cds_loaded_count = 0
        self._append_cds_batch()

    def _filter_cd_list(self, query):
        query = query.lower().strip()
        if not query:
            self.filtered_cds = list(self.all_cds)
        else:
            self.filtered_cds = [cd for cd in self.all_cds if query in cd[1].lower()]
        sb = self.scroll_cds.verticalScrollBar()
        pos = sb.value()
        while self.cds_grid.count():
            item = self.cds_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cd_thumb_refs.clear()
        self.cds_loaded_count = 0
        self._append_cds_batch()
        QTimer.singleShot(0, lambda s=sb, p=pos: s.setValue(p))

    def _append_cds_batch(self):
        if self._shutting_down:
            return
        for i in range(self.cds_grid.count()):
            item = self.cds_grid.itemAt(i)
            if (item and item.widget() and isinstance(item.widget(), QPushButton)
                    and item.widget().text().startswith("Carregar mais")):
                item.widget().deleteLater()
        start_idx = self.cds_loaded_count
        end_idx = min(start_idx + 40, len(self.filtered_cds))
        max_cols = 4
        c = self.theme_colors
        for idx in range(start_idx, end_idx):
            folder_path, album_name, first_audio_path = self.filtered_cds[idx]
            card = QFrame()
            card.setFixedSize(220, 260)
            card.setStyleSheet("background-color: transparent; border: none;")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(6)
            lbl_thumb = ClickableLabel()
            lbl_thumb.setFixedSize(220, 200)
            lbl_thumb.setAlignment(Qt.AlignCenter)
            lbl_thumb.setCursor(Qt.PointingHandCursor)
            self._set_placeholder_icon(lbl_thumb, "cd_icon.png", 96, "💿")
            lbl_thumb.setStyleSheet(
                "font-size: 50px; background-color: #1e1e1e; border-radius: 8px; color: #555;")
            self.cd_thumb_refs[folder_path] = lbl_thumb
            lbl_thumb.clicked.connect(lambda p=folder_path: self._play_cd_album(p))
            lbl_thumb.rightClicked.connect(
                lambda p=folder_path, fa=first_audio_path: self._show_folder_menu(
                    p, QCursor.pos(), first_audio=fa))
            lbl_name = QLabel(album_name)
            lbl_name.setAlignment(Qt.AlignCenter)
            lbl_name.setWordWrap(True)
            lbl_name.setStyleSheet(
                f"font-size: 12px; font-weight: bold; color: {c['text']}; border: none;")
            card_layout.addWidget(lbl_thumb)
            card_layout.addWidget(lbl_name)
            row = idx // max_cols
            col = idx % max_cols
            self.cds_grid.addWidget(card, row, col)
            self._cd_cover_to_folder[first_audio_path] = folder_path
            worker = ThumbnailWorker(first_audio_path, self.thumb_cache, is_music=True, target_size=(220, 200))
            worker.signals.result.connect(self._on_cd_thumb_ready)
            self.threadpool.start(worker)
        self.cds_loaded_count = end_idx
        if self.cds_loaded_count < len(self.filtered_cds):
            restantes = len(self.filtered_cds) - self.cds_loaded_count
            btn_more = self._create_btn(f"Carregar mais (+40 CDs - Restam {restantes})")
            btn_more.clicked.connect(self._append_cds_batch)
            total_rows = (len(self.filtered_cds) + max_cols - 1) // max_cols
            self.cds_grid.addWidget(btn_more, total_rows + 1, 0, 1, max_cols, Qt.AlignCenter)

    def _on_cd_thumb_ready(self, audio_path, qimg):
        if self._shutting_down:
            return
        folder_path = self._cd_cover_to_folder.get(audio_path)
        if not folder_path:
            return
        lbl = self.cd_thumb_refs.get(folder_path)
        if lbl:
            if not qimg.isNull():
                lbl.setPixmap(QPixmap.fromImage(qimg))
                lbl.setStyleSheet("background-color: transparent; border-radius: 8px;")
            else:
                self._set_placeholder_icon(lbl, "cd_icon.png", 96, "💿")

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

    def _create_galeria_page(self):
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        top_bar = QHBoxLayout()
        title = QLabel("Galeria de Fotos")
        title.setObjectName("pageTitle")
        self.combo_galeria_pastas = QComboBox()
        self.combo_galeria_pastas.setFixedWidth(280)
        self.atualizar_combo_pastas_galeria()
        self.combo_galeria_pastas.currentIndexChanged.connect(
            lambda *_: self.carregar_fotos_galeria())
        btn_atualizar = self._create_btn("Atualizar Galeria")
        btn_atualizar.clicked.connect(lambda: self.carregar_fotos_galeria(force_scan=True))
        top_bar.addWidget(title)
        top_bar.addStretch()
        top_bar.addWidget(self.combo_galeria_pastas)
        top_bar.addWidget(btn_atualizar)
        layout.addLayout(top_bar)

        self.scroll_gallery = QScrollArea()
        self.scroll_gallery.setWidgetResizable(True)
        self.scroll_gallery.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_gallery.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_gallery.setStyleSheet(self._modern_scrollbar_style())
        self.gallery_content = QWidget()
        self.gallery_content.setStyleSheet("background: transparent; border: none;")
        self.gallery_grid = QGridLayout(self.gallery_content)
        self.gallery_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.gallery_grid.setContentsMargins(0, 0, 0, 0)
        self.gallery_grid.setSpacing(14)
        self.scroll_gallery.setWidget(self.gallery_content)
        layout.addWidget(self.scroll_gallery, stretch=1)
        return page

    def atualizar_combo_pastas_galeria(self):
        if not hasattr(self, "combo_galeria_pastas"):
            return
        current_data = self.combo_galeria_pastas.currentData()
        self.combo_galeria_pastas.blockSignals(True)
        self.combo_galeria_pastas.clear()
        self.combo_galeria_pastas.addItem(
            self._icon("pasta_icon.png"), "Todas as Pastas Configuradas", "")
        folders = self.app_config.get("gallery_folders", ["", "", "", "", ""])
        for i, folder in enumerate(folders):
            if folder:
                exists = os.path.exists(folder)
                prefix = "" if exists else "⚠ "
                folder_name = os.path.basename(folder) or folder
                self.combo_galeria_pastas.addItem(
                    self._icon("pasta_icon.png"),
                    f"{prefix}Pasta {i+1}: {folder_name}", folder)
        index = self.combo_galeria_pastas.findData(current_data)
        self.combo_galeria_pastas.setCurrentIndex(index if index >= 0 else 0)
        self.combo_galeria_pastas.blockSignals(False)

    def carregar_fotos_galeria(self, force_scan=False):
        self.gallery_initialized = True
        selected_folder = (self.combo_galeria_pastas.currentData()
                           if hasattr(self, "combo_galeria_pastas") else "")
        if selected_folder:
            configured = [selected_folder]
        else:
            configured = [f for f in self.app_config.get("gallery_folders", ["", "", "", "", ""]) if f]
        accessible = [f for f in configured if os.path.isdir(f)]
        dead = [f for f in configured if f not in accessible]
        while self.gallery_grid.count():
            item = self.gallery_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.gallery_thumb_refs.clear()
        if not configured:
            lbl = QLabel("Nenhuma pasta de galeria válida encontrada ou selecionada.")
            lbl.setObjectName("infoLabel")
            self.gallery_grid.addWidget(lbl, 0, 0)
            return
        cached = self.db.get_images(configured) if self.db.is_ready() else []
        if cached and not force_scan and not self._dirty["images"]:
            self._on_gallery_scanned(cached, self._gallery_scan_gen)
            return
        if not cached and not dead:
            lbl = QLabel("Procurando imagens em background...")
            lbl.setObjectName("infoLabel")
            self.gallery_grid.addWidget(lbl, 0, 0)
        self._dirty["images"] = False
        if not accessible:
            if cached:
                self._on_gallery_scanned(cached, self._gallery_scan_gen)
            else:
                lbl = QLabel("⚠ Nenhuma pasta acessível.")
                lbl.setObjectName("infoLabel")
                self.gallery_grid.addWidget(lbl, 0, 0)
            return
        self._gallery_scan_gen += 1
        gen = self._gallery_scan_gen
        if self._gallery_scanner is not None and self._gallery_scanner.isRunning():
            self._gallery_scanner.requestInterruption()
        self._gallery_scanner = ScannerThread(
            accessible, IMAGE_EXTS, True, db=self.db, kind="images")
        self._gallery_scanner.finished_scan.connect(
            lambda results, g=gen: self._on_gallery_scanned(results, g))
        self._gallery_scanner.start()

    def _on_gallery_scanned(self, results, gen):
        if self._shutting_down or gen != self._gallery_scan_gen:
            return
        while self.gallery_grid.count():
            item = self.gallery_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.all_gallery_images = results
        if not self.all_gallery_images:
            lbl = QLabel("Nenhuma imagem encontrada nesta pasta.")
            lbl.setObjectName("infoLabel")
            self.gallery_grid.addWidget(lbl, 0, 0)
            return
        self.gallery_loaded_count = 0
        self._append_gallery_batch()

    def _append_gallery_batch(self):
        if self._shutting_down:
            return
        for i in range(self.gallery_grid.count()):
            item = self.gallery_grid.itemAt(i)
            if (item and item.widget() and isinstance(item.widget(), QPushButton)
                    and item.widget().text().startswith("Carregar mais")):
                item.widget().deleteLater()
        start_idx = self.gallery_loaded_count
        end_idx = min(start_idx + 100, len(self.all_gallery_images))
        max_cols = 3
        c = self.theme_colors
        for idx in range(start_idx, end_idx):
            mtime, img_path = self.all_gallery_images[idx]
            card = QFrame()
            card.setFixedSize(360, 310)
            card.setStyleSheet("background-color: transparent; border: none;")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(1)
            lbl_thumb = ClickableLabel()
            lbl_thumb.setFixedSize(360, 280)
            lbl_thumb.setAlignment(Qt.AlignCenter)
            lbl_thumb.setCursor(Qt.PointingHandCursor)
            lbl_thumb.setText("⏳")
            lbl_thumb.setStyleSheet(
                "font-size: 30px; background-color: #1e1e1e; border-radius: 8px; color: #555;")
            lbl_thumb.clicked.connect(lambda p=img_path: self._show_image_fullscreen(p))
            lbl_thumb.rightClicked.connect(
                lambda p=img_path: self._show_card_menu(p, QCursor.pos()))
            self.gallery_thumb_refs[img_path] = lbl_thumb
            try:
                dt_str = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
            except (OSError, OverflowError):
                dt_str = "Data desconhecida"
            lbl_date = QLabel(dt_str)
            lbl_date.setAlignment(Qt.AlignCenter)
            lbl_date.setStyleSheet(
                f"font-size: 11px; color: {c['text_sec']}; border: none;")
            card_layout.addWidget(lbl_thumb)
            card_layout.addWidget(lbl_date)
            row = idx // max_cols
            col = idx % max_cols
            self.gallery_grid.addWidget(card, row, col)
            worker = ThumbnailWorker(img_path, self.thumb_cache, is_music=False, target_size=(360, 280))
            worker.signals.result.connect(self._on_gallery_thumb_ready)
            self.threadpool.start(worker)
        self.gallery_loaded_count = end_idx
        if self.gallery_loaded_count < len(self.all_gallery_images):
            restantes = len(self.all_gallery_images) - self.gallery_loaded_count
            btn_more = self._create_btn(f"Carregar mais (+100 fotos - Restam {restantes})")
            btn_more.clicked.connect(self._append_gallery_batch)
            total_rows = (len(self.all_gallery_images) + max_cols - 1) // max_cols
            self.gallery_grid.addWidget(btn_more, total_rows + 1, 0, 1, max_cols, Qt.AlignCenter)

    def _on_gallery_thumb_ready(self, path, qimg):
        if self._shutting_down:
            return
        lbl = self.gallery_thumb_refs.get(path)
        if lbl:
            if not qimg.isNull():
                lbl.setPixmap(QPixmap.fromImage(qimg))
                lbl.setStyleSheet("background-color: transparent; border-radius: 8px;")
            else:
                lbl.setText("Erro")

    def _show_image_fullscreen(self, image_path):
        overlay = QDialog(self, Qt.FramelessWindowHint)
        overlay.setAttribute(Qt.WA_TranslucentBackground)
        overlay.resize(self.size())
        overlay.move(self.mapToGlobal(self.rect().topLeft()))
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        bg_frame = QFrame()
        bg_frame.setStyleSheet("background-color: rgba(0, 0, 0, 230); border: none;")
        bg_layout = QVBoxLayout(bg_frame)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        bg_layout.setAlignment(Qt.AlignCenter)
        lbl_img = QLabel()
        reader = QImageReader(image_path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            target = QSize(1200, 1200)
            scaled_size = size.scaled(target, Qt.KeepAspectRatio)
            if scaled_size.width() < size.width() or scaled_size.height() < size.height():
                reader.setScaledSize(scaled_size)
        qimg = reader.read()
        if not qimg.isNull():
            pix = QPixmap.fromImage(qimg)
            lbl_img.setPixmap(pix.scaled(950, 950, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lbl_img.setStyleSheet("border: none; background: transparent;")
        bg_layout.addWidget(lbl_img)
        layout.addWidget(bg_frame)
        overlay.mousePressEvent = lambda event: overlay.accept()
        overlay.exec()

    def _show_cover_fullscreen(self):
        if not self.current_cover_pixmap:
            return
        overlay = QDialog(self, Qt.FramelessWindowHint)
        overlay.setAttribute(Qt.WA_TranslucentBackground)
        overlay.resize(self.size())
        overlay.move(self.mapToGlobal(self.rect().topLeft()))
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        bg_frame = QFrame()
        bg_frame.setStyleSheet("background-color: rgba(0, 0, 0, 210);")
        bg_layout = QVBoxLayout(bg_frame)
        bg_layout.setAlignment(Qt.AlignCenter)
        lbl_img = QLabel()
        lbl_img.setPixmap(self.current_cover_pixmap.scaled(
            450, 450, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lbl_img.setStyleSheet("border: 2px solid #555; background-color: #111; border-radius: 8px;")
        bg_layout.addWidget(lbl_img)
        layout.addWidget(bg_frame)
        overlay.mousePressEvent = lambda event: overlay.accept()
        overlay.exec()

    def _create_explorer_page(self):
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        toolbar = QHBoxLayout()
        title = QLabel("Músicas")
        title.setObjectName("pageSubtitle")
        self.lbl_path = QLabel(self.app_config["initial_folder"] or "Nenhuma pasta selecionada")
        self.lbl_path.setObjectName("infoLabel")
        btn_change_dir = self._create_btn("Outra Pasta...")
        btn_change_dir.clicked.connect(self._change_music_directory)
        toolbar.addWidget(title)
        toolbar.addWidget(self.lbl_path, stretch=1)
        toolbar.addWidget(btn_change_dir)
        layout.addLayout(toolbar)

        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 5, 0, 10)
        self.input_search = QLineEdit()
        self.input_search.setObjectName("searchInput")
        self.input_search.setPlaceholderText("🔍 Pesquisar por nome, artista ou álbum...")
        self.input_search.setFixedHeight(36)
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(250)
        self._search_debounce.timeout.connect(self._execute_search)
        self.input_search.textChanged.connect(lambda _: self._search_debounce.start())
        search_layout.addWidget(self.input_search)
        layout.addLayout(search_layout)

        self.music_stacked = QStackedWidget()
        self.scroll_music = QScrollArea()
        self.scroll_music.setWidgetResizable(True)
        self.scroll_music.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_music.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_music.setStyleSheet(self._modern_scrollbar_style())
        self.music_content = QWidget()
        self.music_content.setStyleSheet("background: transparent; border: none;")
        self.music_grid = QGridLayout(self.music_content)
        self.music_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.music_grid.setContentsMargins(0, 0, 0, 0)
        self.music_grid.setSpacing(16)
        self.scroll_music.setWidget(self.music_content)

        self.list_music = QListWidget()
        self.list_music.setObjectName("musicList")
        self.list_music.itemDoubleClicked.connect(self._play_selected_list_track)
        self.music_stacked.addWidget(self.scroll_music)
        self.music_stacked.addWidget(self.list_music)
        layout.addWidget(self.music_stacked, stretch=1)
        return page

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
        configured, folders, dead = self._folders_status(
            "music_folders", fallback_initial=True)
        while self.music_grid.count():
            item = self.music_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.list_music.clear()
        self.music_thumb_refs.clear()
        self.lbl_path.setText(
            f"{len(folders)} pasta(s) OK · ⚠ {len(dead)} inacessível(is)" if dead
            else f"{len(folders)} diretório(s) configurado(s)")
        if not configured:
            lbl = QLabel("Configure até 5 diretórios válidos nas Opções.")
            lbl.setObjectName("infoLabel")
            self.music_grid.addWidget(lbl, 0, 0)
            return
        cached = self.db.get_tracks(configured) if self.db.is_ready() else []
        if cached and not force_scan and not self._dirty["tracks"]:
            self._on_music_scanned(cached, self._music_scan_gen)
            return
        if not cached and not dead:
            lbl = QLabel("Lendo pasta de músicas em background...")
            lbl.setObjectName("infoLabel")
            self.music_grid.addWidget(lbl, 0, 0)
        self._dirty["tracks"] = False
        if not folders:
            if cached:
                self._on_music_scanned(cached, self._music_scan_gen)
            else:
                lbl = QLabel("⚠ Nenhuma pasta acessível.")
                lbl.setObjectName("infoLabel")
                self.music_grid.addWidget(lbl, 0, 0)
            return
        self._music_scan_gen += 1
        gen = self._music_scan_gen
        if self._music_scanner is not None and self._music_scanner.isRunning():
            self._music_scanner.requestInterruption()
        self._music_scanner = ScannerThread(
            folders, AUDIO_EXTS, False, db=self.db, kind="tracks", extract_tags=True)
        self._music_scanner.finished_scan.connect(
            lambda results, g=gen: self._on_music_scanned(results, g))
        self._music_scanner.start()

    def _on_music_scanned(self, results, gen):
        if self._shutting_down or gen != self._music_scan_gen:
            return
        while self.music_grid.count():
            item = self.music_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.all_music_tracks = results
        self.filtered_music_tracks = list(self.all_music_tracks)
        self._track_to_index = {p: i + 1 for i, p in enumerate(self.all_music_tracks)}
        self.input_search.blockSignals(True)
        self.input_search.clear()
        self.input_search.blockSignals(False)
        if not self.all_music_tracks:
            lbl = QLabel("Nenhuma música encontrada nesta pasta.")
            lbl.setObjectName("infoLabel")
            self.music_grid.addWidget(lbl, 0, 0)
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
            self._append_music_batch()

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
        if not query:
            self.filtered_music_tracks = list(self.all_music_tracks)
        else:
            self.filtered_music_tracks = [
                t for t in self.all_music_tracks
                if query in self._track_search_index.get(t, os.path.basename(t).lower())
            ]
        view_mode = self.app_config.get("music_view_mode", "grid")
        if view_mode == "names":
            self._carregar_musicas_lista()
        else:
            sb = self.scroll_music.verticalScrollBar()
            pos = sb.value()
            while self.music_grid.count():
                item = self.music_grid.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.music_thumb_refs.clear()
            self.music_loaded_count = 0
            self._append_music_batch()
            QTimer.singleShot(0, lambda s=sb, p=pos: s.setValue(p))

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

    def _append_music_batch(self):
        if self._shutting_down:
            return
        for i in range(self.music_grid.count()):
            item = self.music_grid.itemAt(i)
            if (item and item.widget() and isinstance(item.widget(), QPushButton)
                    and item.widget().text().startswith("Carregar mais")):
                item.widget().deleteLater()
        start_idx = self.music_loaded_count
        end_idx = min(start_idx + 40, len(self.filtered_music_tracks))
        max_cols = 4
        c = self.theme_colors
        for idx in range(start_idx, end_idx):
            track_path = self.filtered_music_tracks[idx]
            original_idx = self._track_to_index.get(track_path, 0)
            card = QFrame()
            card.setFixedSize(220, 260)
            card.setStyleSheet("background-color: transparent; border: none;")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(6)
            lbl_thumb = ClickableLabel()
            lbl_thumb.setFixedSize(220, 200)
            lbl_thumb.setAlignment(Qt.AlignCenter)
            lbl_thumb.setCursor(Qt.PointingHandCursor)
            lbl_thumb.setText("⏳")
            lbl_thumb.setStyleSheet(
                "font-size: 30px; background-color: #1e1e1e; border-radius: 8px; color: #555;")
            self.music_thumb_refs[track_path] = lbl_thumb
            global_idx = original_idx - 1
            lbl_thumb.clicked.connect(
                lambda p=track_path, i=global_idx: self._play_grid_track(p, i))
            lbl_thumb.rightClicked.connect(
                lambda p=track_path: self._show_card_menu(p, QCursor.pos(), is_audio=True))
            filename = os.path.basename(track_path)
            track_title, _ = os.path.splitext(filename)
            lbl_name = QLabel(f"#{original_idx:04d} - {track_title}")
            lbl_name.setAlignment(Qt.AlignCenter)
            lbl_name.setWordWrap(True)
            lbl_name.setStyleSheet(
                f"font-size: 12px; font-weight: bold; color: {c['text']}; border: none;")
            card_layout.addWidget(lbl_thumb)
            card_layout.addWidget(lbl_name)
            row = idx // max_cols
            col = idx % max_cols
            self.music_grid.addWidget(card, row, col)
            worker = ThumbnailWorker(track_path, self.thumb_cache, is_music=True, target_size=(220, 200))
            worker.signals.result.connect(self._on_music_thumb_ready)
            self.threadpool.start(worker)
        self.music_loaded_count = end_idx
        if self.music_loaded_count < len(self.filtered_music_tracks):
            restantes = len(self.filtered_music_tracks) - self.music_loaded_count
            btn_more = self._create_btn(f"Carregar mais (+40 músicas - Restam {restantes})")
            btn_more.clicked.connect(self._append_music_batch)
            total_rows = (len(self.filtered_music_tracks) + max_cols - 1) // max_cols
            self.music_grid.addWidget(btn_more, total_rows + 1, 0, 1, max_cols, Qt.AlignCenter)

    def _on_music_thumb_ready(self, path, qimg):
        if self._shutting_down:
            return
        lbl = self.music_thumb_refs.get(path)
        if lbl:
            if not qimg.isNull():
                lbl.setPixmap(QPixmap.fromImage(qimg))
                lbl.setStyleSheet("background-color: #1a1a1a; border-radius: 8px;")
            else:
                self._set_placeholder_icon(lbl, "musica_icon.png", 80, "🎵")
                lbl.setStyleSheet(
                    "font-size: 40px; background-color: #1e1e1e; "
                    "border-radius: 8px; color: #777;")

    def _play_grid_track(self, file_path, index):
        if self.video_player.playbackState() == QMediaPlayer.PlayingState:
            self.video_player.pause()
        self.playlist_tracks = self.all_music_tracks
        self._play_track_at_index(index)

    def _create_equalizador_page(self):
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Equalizador & Efeitos")
        title.setObjectName("configTitle")
        layout.addWidget(title)
        tabs = QTabWidget()
        tab_bbe = QWidget()
        bbe_layout = QVBoxLayout(tab_bbe)
        bbe_layout.setAlignment(Qt.AlignTop)
        bbe_layout.setContentsMargins(30, 30, 30, 30)
        chk = QCheckBox("Activar Processamento BBE  (em desenvolvimento)")
        chk.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 15px;")
        bbe_layout.addWidget(chk)
        ctrls = QVBoxLayout()
        ctrls.setSpacing(20)
        ctrls.addLayout(self._create_slider_row("Atraso Graves (Low ms)", 0, 50, 25))
        ctrls.addLayout(self._create_slider_row("Atraso Médios (Mid ms)", 0, 20, 8))
        ctrls.addLayout(self._create_slider_row("Definição (Agudos)", 0, 100, 0))
        ctrls.addLayout(self._create_slider_row("Reforço de Graves (Bass)", 0, 100, 0))
        bbe_layout.addLayout(ctrls)
        bbe_layout.addStretch()
        tab_filtros = QWidget()
        filtros_layout = QVBoxLayout(tab_filtros)
        filtros_layout.setAlignment(Qt.AlignCenter)
        lbl_filtros = QLabel("Filtros de Frequência (Em Desenvolvimento)")
        lbl_filtros.setObjectName("configSection")
        filtros_layout.addWidget(lbl_filtros)
        tabs.addTab(tab_bbe, "BBE Sound")
        tabs.addTab(tab_filtros, "Filtros de Frequência")
        layout.addWidget(tabs)
        return page

    def _create_slider_row(self, label_text, min_val, max_val, default_val):
        row_layout = QHBoxLayout()
        label = QLabel(label_text)
        label.setFixedWidth(180)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default_val)
        slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: #444; "
            "border-radius: 2px; border: none; } "
            "QSlider::handle:horizontal { background: #0078D7; width: 16px; "
            "margin: -6px 0; border-radius: 8px; }")
        value_label = QLabel(str(default_val))
        value_label.setFixedWidth(40)
        slider.valueChanged.connect(lambda v, l=value_label: l.setText(str(v)))
        row_layout.addWidget(label)
        row_layout.addWidget(slider, stretch=1)
        row_layout.addWidget(value_label)
        return row_layout

    def _modern_scrollbar_style(self):
        return """
            QScrollArea { border: none; background-color: transparent; }
            QScrollArea > QWidget > QWidget { background-color: transparent; }
            QScrollBar:vertical { background: transparent; width: 10px;
                                 margin: 4px 2px 4px 2px; }
            QScrollBar::handle:vertical { background: #3D4652;
                                         min-height: 28px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #168BD2; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px; border: none; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent; }
            QScrollBar:horizontal { background: transparent; height: 10px;
                                   margin: 2px 4px; }
            QScrollBar::handle:horizontal { background: #3D4652;
                                           min-width: 28px; border-radius: 5px; }
            QScrollBar::handle:horizontal:hover { background: #168BD2; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px; border: none; }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent; }
        """

    def _create_config_page(self):
        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer_scroll.setStyleSheet(self._modern_scrollbar_style())
        page = QFrame()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setAlignment(Qt.AlignTop)
        title = QLabel("⚙️ Configurações do Sistema")
        title.setObjectName("configTitle")
        layout.addWidget(title)

        theme_layout = QHBoxLayout()
        lbl = QLabel("Tema da Interface:")
        lbl.setObjectName("configLabel")
        lbl.setFixedWidth(200)
        self.combo_theme = QComboBox()
        self.combo_theme.addItem("Escuro (Dark)", "dark")
        self.combo_theme.addItem("Claro (Light)", "light")
        saved_theme = self.app_config.get("theme", "dark")
        self.combo_theme.setCurrentIndex(1 if saved_theme == "light" else 0)
        self.combo_theme.currentIndexChanged.connect(self._change_theme)
        theme_layout.addWidget(lbl)
        theme_layout.addWidget(self.combo_theme, stretch=1)
        layout.addLayout(theme_layout)

        sidebar_layout = QHBoxLayout()
        sidebar_layout.setContentsMargins(0, 20, 0, 0)
        lbl = QLabel("Posição da Barra Lateral:")
        lbl.setObjectName("configLabel")
        lbl.setFixedWidth(200)
        self.combo_sidebar_side = QComboBox()
        self.combo_sidebar_side.addItem("Lado Direito", "right")
        self.combo_sidebar_side.addItem("Lado Esquerdo", "left")
        saved_side = self.app_config.get("sidebar_side", "right")
        self.combo_sidebar_side.setCurrentIndex(1 if saved_side == "left" else 0)
        self.combo_sidebar_side.currentIndexChanged.connect(self._change_sidebar_side)
        sidebar_layout.addWidget(lbl)
        sidebar_layout.addWidget(self.combo_sidebar_side, stretch=1)
        layout.addLayout(sidebar_layout)

        view_layout = QHBoxLayout()
        view_layout.setContentsMargins(0, 20, 0, 0)
        lbl = QLabel("Visualização de Músicas:")
        lbl.setObjectName("configLabel")
        lbl.setFixedWidth(200)
        self.combo_music_view = QComboBox()
        self.combo_music_view.addItem("Visão Atual (Grelha com Capas)", "grid")
        self.combo_music_view.addItem("Apenas Nomes (Lista Limpa)", "names")
        saved_view = self.app_config.get("music_view_mode", "grid")
        self.combo_music_view.setCurrentIndex(1 if saved_view == "names" else 0)
        self.combo_music_view.currentIndexChanged.connect(self._change_music_view_mode)
        view_layout.addWidget(lbl)
        view_layout.addWidget(self.combo_music_view, stretch=1)
        layout.addLayout(view_layout)

        audio_layout = QHBoxLayout()
        audio_layout.setContentsMargins(0, 20, 0, 0)
        lbl = QLabel("Dispositivo de Áudio:")
        lbl.setObjectName("configLabel")
        lbl.setFixedWidth(200)
        self.combo_audio = QComboBox()
        self.audio_devices = QMediaDevices.audioOutputs()
        saved_device_desc = self.app_config.get("audio_device", "")
        for i, dev in enumerate(self.audio_devices):
            desc = dev.description()
            self.combo_audio.addItem(desc)
            if desc == saved_device_desc:
                self.combo_audio.setCurrentIndex(i)
                self.audio_output.setDevice(dev)
                self.video_audio_output.setDevice(dev)
        self.combo_audio.currentIndexChanged.connect(self._change_audio_device)
        audio_layout.addWidget(lbl)
        audio_layout.addWidget(self.combo_audio, stretch=1)
        layout.addLayout(audio_layout)

        folder_layout = QHBoxLayout()
        folder_layout.setContentsMargins(0, 20, 0, 0)
        lbl = QLabel("Pasta Inicial (Áudio):")
        lbl.setObjectName("configLabel")
        lbl.setFixedWidth(200)
        self.input_config_folder = QLineEdit(self.app_config.get("initial_folder", ""))
        self.input_config_folder.setObjectName("folderInput")
        btn_browse = self._create_btn("Procurar")
        btn_browse.clicked.connect(self._browse_initial_folder)
        btn_apply = self._create_btn("Aplicar", kind="success")
        btn_apply.clicked.connect(self._aplicar_pasta_audio)
        folder_layout.addWidget(lbl)
        folder_layout.addWidget(self.input_config_folder, stretch=1)
        folder_layout.addWidget(btn_browse)
        folder_layout.addWidget(btn_apply)
        layout.addLayout(folder_layout)

        def _folder_section(section_title, config_key, n_entries=5):
            lbl = QLabel(section_title)
            lbl.setObjectName("configSection")
            layout.addWidget(lbl)
            inputs = []
            saved = list(self.app_config.get(config_key, []))[:n_entries]
            saved += [""] * (n_entries - len(saved))
            for i in range(n_entries):
                row = QHBoxLayout()
                l = QLabel(f"Pasta {i+1}:")
                l.setObjectName("configLabel")
                l.setFixedWidth(200)
                field = QLineEdit(saved[i])
                field.setObjectName("folderInput")
                inputs.append(field)
                btn = self._create_btn("Procurar")
                btn.clicked.connect(lambda checked=False, idx=i, flds=inputs: self._browse_folder_generic(flds, idx))
                row.addWidget(l)
                row.addWidget(field, stretch=1)
                row.addWidget(btn)
                layout.addLayout(row)
            return inputs

        self.music_folder_inputs = _folder_section(
            "Diretórios de Músicas (até 5):", "music_folders")
        btn = self._create_btn("Aplicar Diretórios de Músicas", kind="info")
        btn.clicked.connect(self._apply_music_folders)
        layout.addWidget(btn)

        self.cd_folder_inputs = _folder_section(
            "Diretórios de CDs (até 5):", "cd_folders")
        btn = self._create_btn("Aplicar Diretórios de CDs")
        btn.clicked.connect(self._apply_cd_folders)
        layout.addWidget(btn)

        self.video_folder_inputs = _folder_section(
            "Diretórios de Vídeos (até 5):", "video_folders")
        btn = self._create_btn("Aplicar Diretórios de Vídeos")
        btn.clicked.connect(self._apply_video_folders)
        layout.addWidget(btn)

        self.game_folder_inputs = _folder_section(
            "Diretórios de Jogos (até 5):", "game_folders")
        btn = self._create_btn("Aplicar Diretórios de Jogos")
        btn.clicked.connect(self._apply_game_folders)
        layout.addWidget(btn)

        self.gallery_inputs = _folder_section(
            "Pastas da Galeria (até 5):", "gallery_folders")
        btn = self._create_btn("Aplicar Pastas da Galeria", kind="success")
        btn.clicked.connect(self._aplicar_pastas_galeria)
        layout.addWidget(btn)

        lbl = QLabel("Cache da Biblioteca (SQLite):")
        lbl.setObjectName("configSection")
        layout.addWidget(lbl)
        row = QHBoxLayout()
        desc = QLabel("Remove o banco de dados de varreduras. A próxima visita irá reindexar tudo.")
        desc.setObjectName("infoLabel")
        desc.setWordWrap(True)
        btn = self._create_btn("🧹 Limpar Cache", kind="warning")
        btn.clicked.connect(self._clear_library_cache)
        row.addWidget(desc, stretch=1)
        row.addWidget(btn)
        layout.addLayout(row)

        lbl = QLabel("Arquivo de Log:")
        lbl.setObjectName("configSection")
        layout.addWidget(lbl)
        row = QHBoxLayout()
        log_text = self.log_path if self.log_path else "Não inicializado"
        lbl_log = QLabel(f"📄 {log_text}")
        lbl_log.setObjectName("infoLabel")
        lbl_log.setWordWrap(True)
        lbl_log.setTextInteractionFlags(Qt.TextSelectableByMouse)
        btn = self._create_btn("📂 Abrir pasta do log")
        btn.clicked.connect(self._open_log_folder)
        row.addWidget(lbl_log, stretch=1)
        row.addWidget(btn)
        layout.addLayout(row)

        layout.addStretch()
        outer_scroll.setWidget(page)
        return outer_scroll

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
                while self.music_grid.count():
                    item = self.music_grid.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                self.music_loaded_count = 0
                self._append_music_batch()
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


def _setup_logging():
    log_path = None
    try:
        log_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not log_dir:
            log_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "coban_archive.log")
        file_handler = RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
        stream_handler = logging.StreamHandler()
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[file_handler, stream_handler])
        logging.getLogger(__name__).info("=" * 60)
        logging.getLogger(__name__).info("Coban Archive %s iniciado", APP_VERSION)
        logging.getLogger(__name__).info("Log file: %s", log_path)
        logging.getLogger(__name__).info("=" * 60)
        print(f"[Coban Archive] Log file: {log_path}", flush=True)
    except Exception as exc:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger(__name__).warning("Falha no logging: %s", exc)

    def _exception_hook(exc_type, exc, tb):
        logging.getLogger("uncaught").error(
            "Exceção não capturada", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _exception_hook
    return log_path


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("CobanArchive")
    app.setOrganizationName("Coban")
    log_path = _setup_logging()

    app_dir = os.path.dirname(os.path.abspath(__file__))
    app_icon_png = os.path.join(app_dir, "assets", "icons", "coban_archive_app.png")
    if os.path.isfile(app_icon_png):
        app.setWindowIcon(QIcon(app_icon_png))

    window = CobanArchiveHome(log_path=log_path)
    window.show()
    sys.exit(app.exec())