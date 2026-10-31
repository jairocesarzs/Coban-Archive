"""Interface do Coban Archive: widgets, diálogos, páginas, cards, tema e janela.

Aqui fica tudo que é visual. Regras de negócio, scanners e workers ficam em core.py.
"""

import os
import logging
from datetime import datetime
from PIL import Image

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QStackedWidget, QStyle, QSystemTrayIcon,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget
)
from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QDesktopServices, QIcon, QImage, QImageReader, QKeySequence, QPainter,
    QPixmap, QShortcut
)
from PySide6.QtMultimedia import QMediaDevices, QVideoSink

from core import APP_DESCRIPTION, APP_VERSION, AUDIO_EXTS, GITHUB_URL

try:
    import mutagen
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

log = logging.getLogger(__name__)


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


class LayoutUI:
    """Toda a interface do Coban Archive. A lógica fica em core.py (CobanArchiveCore)."""

    # ======================================================================
    # Janela: casca, cabeçalho, sidebar, rodapé (player) e atalhos
    # ======================================================================


    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._build_pages()
        self._build_header()

        self.body_layout = QHBoxLayout()
        body_layout = self.body_layout

        self._build_sidebar()

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

    def _build_pages(self):
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

    def _build_header(self):
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

    def _build_sidebar(self):
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

    def _update_shuffle_button(self):
        if not hasattr(self, "btn_shuffle"):
            return
        if self._shuffle:
            self.btn_shuffle.setIcon(self._icon("aleatorio_true_icon.png"))
        else:
            self.btn_shuffle.setIcon(self._icon("aleatorio_false_icon.png"))
        self.btn_shuffle.setIconSize(QSize(24, 24))

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

    # ======================================================================
    # Páginas
    # ======================================================================


    # ---- helpers reutilizados pelas páginas --------------------------------

    def _make_page(self, h, v=None, name=None):
        page = QFrame()
        if name:
            page.setObjectName(name)
        layout = QVBoxLayout(page)
        v = h if v is None else v
        layout.setContentsMargins(h, v, h, v)
        return page, layout

    def _make_path_toolbar(self, layout, title_text, path_text, btn_text, on_click):
        toolbar = QHBoxLayout()
        title = QLabel(title_text)
        title.setObjectName("pageSubtitle")
        lbl_path = QLabel(path_text)
        lbl_path.setObjectName("infoLabel")
        btn = self._create_btn(btn_text)
        btn.clicked.connect(on_click)
        toolbar.addWidget(title)
        toolbar.addWidget(lbl_path, stretch=1)
        toolbar.addWidget(btn)
        layout.addLayout(toolbar)
        return lbl_path

    def _make_search_bar(self, layout, placeholder, on_search):
        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 5, 0, 10)
        field = QLineEdit()
        field.setObjectName("searchInput")
        field.setPlaceholderText(placeholder)
        field.setFixedHeight(36)
        debounce = QTimer(self)
        debounce.setSingleShot(True)
        debounce.setInterval(250)
        debounce.timeout.connect(on_search)
        field.textChanged.connect(lambda _: debounce.start())
        search_layout.addWidget(field)
        layout.addLayout(search_layout)
        return field, debounce

    def _make_scroll_grid(self, spacing=16):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(self._modern_scrollbar_style())
        content = QWidget()
        content.setStyleSheet("background: transparent; border: none;")
        grid = QGridLayout(content)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(spacing)
        scroll.setWidget(content)
        return scroll, content, grid

    def _config_row(self, label_text, margin_top=20):
        row = QHBoxLayout()
        if margin_top:
            row.setContentsMargins(0, margin_top, 0, 0)
        lbl = QLabel(label_text)
        lbl.setObjectName("configLabel")
        lbl.setFixedWidth(200)
        return row, lbl

    def _config_combo_row(self, layout, label_text, items, current, on_change, margin_top=20):
        row, lbl = self._config_row(label_text, margin_top)
        combo = QComboBox()
        for text, value in items:
            combo.addItem(text, value)
        combo.setCurrentIndex(1 if current == items[1][1] else 0)
        combo.currentIndexChanged.connect(on_change)
        row.addWidget(lbl)
        row.addWidget(combo, stretch=1)
        layout.addLayout(row)
        return combo

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
        page, layout = self._make_page(16, 14, name="videosPage")
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

    def _create_games_page(self):
        page, layout = self._make_page(20)
        self.lbl_game_path = self._make_path_toolbar(
            layout, "Jogos", "Nenhuma pasta selecionada", "Atualizar",
            lambda: self.carregar_games_grid(force_scan=True))

        self.input_search_game, self._search_game_debounce = self._make_search_bar(
            layout, "🔍 Pesquisar jogo...", self._execute_game_search)

        self.scroll_games, self.games_content, self.games_grid = self._make_scroll_grid()
        layout.addWidget(self.scroll_games, stretch=1)
        return page

    def _create_cds_page(self):
        page, layout = self._make_page(20)
        self.lbl_cd_path = self._make_path_toolbar(
            layout, "CDs (Disk)", "Nenhuma pasta selecionada", "Atualizar",
            lambda: self.carregar_cds_grid(force_scan=True))

        self.input_search_cd, self._search_cd_debounce = self._make_search_bar(
            layout, "🔍 Pesquisar álbum...", self._execute_cd_search)

        self.scroll_cds, self.cds_content, self.cds_grid = self._make_scroll_grid()
        layout.addWidget(self.scroll_cds, stretch=1)
        return page

    def _create_galeria_page(self):
        page, layout = self._make_page(15)
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

        self.scroll_gallery, self.gallery_content, self.gallery_grid = self._make_scroll_grid(14)
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

    def _create_explorer_page(self):
        page, layout = self._make_page(20)
        self.lbl_path = self._make_path_toolbar(
            layout, "Músicas", self.app_config["initial_folder"] or "Nenhuma pasta selecionada",
            "Outra Pasta...", self._change_music_directory)

        self.input_search, self._search_debounce = self._make_search_bar(
            layout, "🔍 Pesquisar por nome, artista ou álbum...", self._execute_search)

        self.music_stacked = QStackedWidget()
        self.scroll_music, self.music_content, self.music_grid = self._make_scroll_grid()

        self.list_music = QListWidget()
        self.list_music.setObjectName("musicList")
        self.list_music.itemDoubleClicked.connect(self._play_selected_list_track)
        self.music_stacked.addWidget(self.scroll_music)
        self.music_stacked.addWidget(self.list_music)
        layout.addWidget(self.music_stacked, stretch=1)
        return page

    def _create_equalizador_page(self):
        page, layout = self._make_page(20)
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

        self.combo_theme = self._config_combo_row(
            layout, "Tema da Interface:",
            [("Escuro (Dark)", "dark"), ("Claro (Light)", "light")],
            self.app_config.get("theme", "dark"), self._change_theme, margin_top=0)
        self.combo_sidebar_side = self._config_combo_row(
            layout, "Posição da Barra Lateral:",
            [("Lado Direito", "right"), ("Lado Esquerdo", "left")],
            self.app_config.get("sidebar_side", "right"), self._change_sidebar_side)
        self.combo_music_view = self._config_combo_row(
            layout, "Visualização de Músicas:",
            [("Visão Atual (Grelha com Capas)", "grid"), ("Apenas Nomes (Lista Limpa)", "names")],
            self.app_config.get("music_view_mode", "grid"), self._change_music_view_mode)

        audio_layout, lbl = self._config_row("Dispositivo de Áudio:")
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

        folder_layout, lbl = self._config_row("Pasta Inicial (Áudio):")
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

        folder_sections = (
            ("music_folder_inputs", "Diretórios de Músicas (até 5):", "music_folders",
             "Aplicar Diretórios de Músicas", "info", self._apply_music_folders),
            ("cd_folder_inputs", "Diretórios de CDs (até 5):", "cd_folders",
             "Aplicar Diretórios de CDs", "primary", self._apply_cd_folders),
            ("video_folder_inputs", "Diretórios de Vídeos (até 5):", "video_folders",
             "Aplicar Diretórios de Vídeos", "primary", self._apply_video_folders),
            ("game_folder_inputs", "Diretórios de Jogos (até 5):", "game_folders",
             "Aplicar Diretórios de Jogos", "primary", self._apply_game_folders),
            ("gallery_inputs", "Pastas da Galeria (até 5):", "gallery_folders",
             "Aplicar Pastas da Galeria", "success", self._aplicar_pastas_galeria),
        )
        for attr, section_title, config_key, btn_text, kind, on_apply in folder_sections:
            setattr(self, attr, _folder_section(section_title, config_key))
            btn = self._create_btn(btn_text, kind=kind)
            btn.clicked.connect(on_apply)
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

    # ======================================================================
    # Cards das grades
    # ======================================================================


    def _build_card_shell(self, card_size, thumb_size, spacing):
        card = QFrame()
        card.setFixedSize(*card_size)
        card.setStyleSheet("background-color: transparent; border: none;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(spacing)
        lbl_thumb = ClickableLabel()
        lbl_thumb.setFixedSize(*thumb_size)
        lbl_thumb.setAlignment(Qt.AlignCenter)
        lbl_thumb.setCursor(Qt.PointingHandCursor)
        return card, card_layout, lbl_thumb

    def _build_title_label(self, text):
        c = self.theme_colors
        lbl_name = QLabel(text)
        lbl_name.setAlignment(Qt.AlignCenter)
        lbl_name.setWordWrap(True)
        lbl_name.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {c['text']}; border: none;")
        return lbl_name

    def _build_music_card(self, track_path, original_idx):
        card, card_layout, lbl_thumb = self._build_card_shell((220, 260), (220, 200), 6)
        lbl_thumb.setText("⏳")
        lbl_thumb.setStyleSheet(
            "font-size: 30px; background-color: #1e1e1e; border-radius: 8px; color: #555;")
        filename = os.path.basename(track_path)
        track_title, _ = os.path.splitext(filename)
        lbl_name = self._build_title_label(f"#{original_idx:04d} - {track_title}")
        card_layout.addWidget(lbl_thumb)
        card_layout.addWidget(lbl_name)
        return card, lbl_thumb

    def _build_game_card(self, game_path):
        card, card_layout, lbl_thumb = self._build_card_shell((220, 260), (220, 200), 6)
        self._set_placeholder_icon(lbl_thumb, "jogos_icon.png", 96, "🎮")
        lbl_thumb.setStyleSheet(
            "font-size: 50px; background-color: #1e1e1e; border-radius: 8px; color: #555;")
        filename = os.path.basename(game_path)
        track_title, _ = os.path.splitext(filename)
        lbl_name = self._build_title_label(track_title)
        card_layout.addWidget(lbl_thumb)
        card_layout.addWidget(lbl_name)
        return card, lbl_thumb

    def _build_cd_card(self, album_name):
        card, card_layout, lbl_thumb = self._build_card_shell((220, 260), (220, 200), 6)
        self._set_placeholder_icon(lbl_thumb, "cd_icon.png", 96, "💿")
        lbl_thumb.setStyleSheet(
            "font-size: 50px; background-color: #1e1e1e; border-radius: 8px; color: #555;")
        lbl_name = self._build_title_label(album_name)
        card_layout.addWidget(lbl_thumb)
        card_layout.addWidget(lbl_name)
        return card, lbl_thumb

    def _build_gallery_card(self, mtime):
        c = self.theme_colors
        card, card_layout, lbl_thumb = self._build_card_shell((360, 310), (360, 280), 1)
        lbl_thumb.setText("⏳")
        lbl_thumb.setStyleSheet(
            "font-size: 30px; background-color: #1e1e1e; border-radius: 8px; color: #555;")
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
        return card, lbl_thumb

    # ======================================================================
    # Tema, ícones e estilos
    # ======================================================================


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

    def _create_btn(self, text, kind="primary"):
        btn = QPushButton(text)
        btn.setStyleSheet(BTN_STYLES.get(kind, BTN_STYLES["primary"]))
        for prefix, icon_name in BTN_ICONS:
            if text.startswith(prefix):
                btn.setIcon(self._icon(icon_name))
                btn.setIconSize(QSize(18, 18))
                break
        return btn

    def _create_sidebar_btn(self, text):
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    # ======================================================================
    # Diálogos, menus e overlays
    # ======================================================================


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

    # ======================================================================
    # Bandeja do sistema
    # ======================================================================


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
