import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "uprev"
_configured = False


def get_app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_log_path():
    return get_app_dir() / "error.log"


def get_logger(name=None):
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def setup_logging():
    global _configured
    if _configured:
        return get_logger()
    _configured = True

    logger = get_logger()
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        handler = RotatingFileHandler(get_log_path(), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        # App folder not writable; fall back to the user's home folder.
        handler = RotatingFileHandler(Path.home() / "error.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    def log_uncaught(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

    def log_thread_exception(args):
        logger.critical(
            "Uncaught exception in thread %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread_exception

    try:
        import faulthandler

        if sys.stderr is None:
            sys.stderr = handler.stream
        faulthandler.enable(file=handler.stream)
    except Exception:
        logger.exception("Unable to enable faulthandler")

    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

        levels = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }

        def qt_handler(msg_type, _context, message):
            logger.log(levels.get(msg_type, logging.INFO), "Qt: %s", message)

        qInstallMessageHandler(qt_handler)
    except Exception:
        logger.exception("Unable to install Qt message handler")

    logger.info("Logging started. Log file: %s", handler.baseFilename)
    return logger
