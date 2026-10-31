"""Ponto de entrada do Coban Archive."""

import sys
import os
import logging
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QIcon

from core import APP_VERSION, CobanArchiveCore
from layout_ui import LayoutUI


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


class CobanArchiveHome(LayoutUI, CobanArchiveCore):
    """Janela principal = interface (layout_ui.py) + lógica (core.py)."""


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
