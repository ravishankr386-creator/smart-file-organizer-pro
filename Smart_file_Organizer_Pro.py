import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import sys
import threading
import tkinter as tk
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from ctypes import windll
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib import error as urlerror
from urllib import request as urlrequest


DEFAULT_FILE_TYPES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".svg", ".heic", ".ico"},
    "Videos": {".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".m4v"},
    "Documents": {".pdf", ".docx", ".txt", ".xlsx", ".pptx", ".odt", ".csv", ".doc", ".rtf", ".md"},
    "Audio": {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"},
    "Archives": {".zip", ".rar", ".tar", ".gz", ".7z", ".bz2"},
    "Executables": {".exe", ".msi", ".bat", ".sh", ".app", ".ps1", ".cmd"},
    "Code": {".py", ".java", ".cpp", ".js", ".html", ".css", ".json", ".ts", ".tsx", ".jsx", ".yml", ".yaml"},
    "Design": {".fig", ".psd", ".ai", ".xd"},
    "Others": set(),
}

KEYWORD_CATEGORY_RULES = {
    "Images": {"screenshot", "photo", "wallpaper", "camera", "img"},
    "Documents": {"invoice", "resume", "report", "notes", "statement", "contract", "receipt"},
    "Videos": {"clip", "recording", "reel", "trailer", "movie"},
    "Audio": {"podcast", "voice", "mix", "track"},
    "Archives": {"backup", "archive", "bundle"},
    "Executables": {"setup", "install", "installer", "driver"},
    "Code": {"script", "source", "project", "module"},
}

PROTECTED_FOLDERS = {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "system volume information",
    "$recycle.bin",
    "recovery",
    "boot",
    "perflogs",
}
BUILD_ARTIFACT_FOLDERS = {"build", "dist"}

PARTIAL_HASH_SIZE = 64 * 1024
HASH_CHUNK_SIZE = 1024 * 1024
MAX_HASH_WORKERS = max(2, min(8, (os.cpu_count() or 4)))

BG = "#08131f"
SURFACE = "#0f1d2e"
SURFACE_ALT = "#13243a"
CARD = "#102133"
CARD_SOFT = "#162c45"
BORDER = "#28435e"
TEXT = "#ecf4ff"
TEXT_MUTED = "#9db3ca"
ACCENT = "#2cc6b8"
ACCENT_ALT = "#6db5ff"
SUCCESS = "#49d17d"
WARNING = "#ffb75e"
DANGER = "#ff7b7b"
INK = "#07111b"
APP_NAME = "Smart File Organizer Pro"
APP_VERSION = "1.0.1"
APP_PUBLISHER = "Ravis Automation Lab"


@dataclass
class FileRecord:
    path: str
    name: str
    extension: str
    size: int
    modified_at: float
    is_system: bool = False
    category: str = "Others"


@dataclass
class PlanAction:
    action: str
    source: str
    target: str
    category: str
    reason: str


@dataclass
class ScanResult:
    files: list[FileRecord] = field(default_factory=list)
    summary: Counter = field(default_factory=Counter)
    extension_counts: Counter = field(default_factory=Counter)
    noisy_names: int = 0
    duplicates: int = 0
    duplicate_groups: list[list[str]] = field(default_factory=list)


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_drive_root(path: str) -> bool:
    normalized = os.path.abspath(path)
    drive, tail = os.path.splitdrive(normalized)
    return bool(drive) and tail in {"\\", "/"}


def has_system_attribute(path: str) -> bool:
    try:
        attributes = windll.kernel32.GetFileAttributesW(str(path))
    except Exception:
        return False
    if attributes == -1:
        return False
    return bool(attributes & 0x4)


def is_protected_folder(path: str) -> bool:
    normalized = normalize_path(path)
    folder_name = os.path.basename(normalized).lower()

    if is_drive_root(normalized):
        return True
    if folder_name in PROTECTED_FOLDERS:
        return True

    windows_dir = normalize_path(os.environ.get("WINDIR", r"C:\Windows"))
    protected_roots = [
        windows_dir,
        normalize_path(r"C:\Program Files"),
        normalize_path(r"C:\Program Files (x86)"),
        normalize_path(r"C:\ProgramData"),
        normalize_path(r"C:\Users\Default"),
        normalize_path(r"C:\Users\Public"),
    ]
    return any(normalized == root or normalized.startswith(root + os.sep) for root in protected_roots)


def contains_build_artifact_folders(path: str) -> bool:
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_dir() and entry.name.lower() in BUILD_ARTIFACT_FOLDERS:
                    return True
    except OSError:
        return False
    return False


def validate_selected_folder(path: str) -> tuple[bool, str]:
    if not path:
        return False, "No folder selected."
    if is_protected_folder(path):
        return False, "Safety Shield blocked this folder. System locations and drive roots cannot be organized."
    if os.path.basename(normalize_path(path)).lower() in BUILD_ARTIFACT_FOLDERS:
        return False, "Safety Shield blocked this folder because build output folders like build/dist should not be organized."
    if contains_build_artifact_folders(path):
        return False, "Safety Shield blocked this folder because it contains build or dist output folders."

    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if has_system_attribute(entry.path):
                    return False, "Safety Shield blocked this folder because it contains protected system files."
    except OSError as error:
        return False, f"Unable to scan folder: {error}"
    return True, ""


def sanitize_folder_name(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", name.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned.strip("._ ") or "Others"


def parse_custom_rules(raw_text: str) -> dict[str, str]:
    rules: dict[str, str] = {}
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        extension_part, folder_name = line.split("=", 1)
        extension = extension_part.strip().lower()
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        folder_name = sanitize_folder_name(folder_name.strip())
        if extension and folder_name:
            rules[extension] = folder_name
    return rules


def sanitize_file_name(file_name: str) -> str:
    base_name, extension = os.path.splitext(file_name)
    cleaned = re.sub(r"\s+", "_", base_name.strip())
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    if not cleaned:
        cleaned = "file"
    return f"{cleaned.lower()}{extension.lower()}"


def build_unique_path(destination_folder: str, desired_name: str, reserved_paths: set[str] | None = None) -> str:
    reserved_paths = reserved_paths or set()
    target_path = os.path.join(destination_folder, desired_name)
    if target_path not in reserved_paths and not os.path.exists(target_path):
        return target_path

    stem, extension = os.path.splitext(desired_name)
    counter = 1
    while True:
        candidate_name = f"{stem}_{counter}{extension}"
        candidate_path = os.path.join(destination_folder, candidate_name)
        if candidate_path not in reserved_paths and not os.path.exists(candidate_path):
            return candidate_path
        counter += 1


def partial_hash(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as file_handle:
        digest.update(file_handle.read(PARTIAL_HASH_SIZE))
    return digest.hexdigest()


def full_hash(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FileOrganizerEngine:
    def scan_root_files(
        self,
        folder_path: str,
        progress_callback=None,
        status_callback=None,
    ) -> ScanResult:
        result = ScanResult()
        try:
            with os.scandir(folder_path) as entries:
                file_entries = [entry for entry in entries if entry.is_file() and not has_system_attribute(entry.path)]
                total_files = len(file_entries)

                for index, entry in enumerate(file_entries, start=1):
                    if not entry.is_file():
                        continue
                    try:
                        stat_result = entry.stat()
                    except OSError:
                        continue

                    extension = Path(entry.name).suffix.lower()
                    record = FileRecord(
                        path=entry.path,
                        name=entry.name,
                        extension=extension,
                        size=stat_result.st_size,
                        modified_at=stat_result.st_mtime,
                    )
                    record.category = self.classify_record(record)
                    result.files.append(record)
                    result.summary[record.category] += 1
                    result.extension_counts[record.extension or ".unknown"] += 1
                    if self.is_noisy_name(record.name):
                        result.noisy_names += 1
                    if status_callback:
                        status_callback(f"Scanning file {index}/{total_files}: {record.name}")
                    if progress_callback:
                        progress_callback(index, total_files, record.name)
        except OSError as error:
            raise RuntimeError(f"Unable to read folder: {error}") from error

        if status_callback and result.files:
            status_callback("Finalizing AI scan insights...")
        duplicate_groups = self.find_duplicate_groups(result.files)
        result.duplicate_groups = duplicate_groups
        result.duplicates = sum(max(0, len(group) - 1) for group in duplicate_groups)
        return result


    def classify_record(self, record: FileRecord) -> str:
        extension = record.extension
        for category, extensions in DEFAULT_FILE_TYPES.items():
            if extension in extensions:
                return category

        mime_type, _ = mimetypes.guess_type(record.name)
        if mime_type:
            if mime_type.startswith("image/"):
                return "Images"
            if mime_type.startswith("video/"):
                return "Videos"
            if mime_type.startswith("audio/"):
                return "Audio"
            if mime_type.startswith("text/"):
                return "Documents"

        normalized_name = record.name.lower()
        for category, keywords in KEYWORD_CATEGORY_RULES.items():
            if any(keyword in normalized_name for keyword in keywords):
                return category

        return "Others"


    def get_destination_folder(self, record: FileRecord, organize_mode: str, custom_rules: dict[str, str]) -> tuple[str, str]:
        if record.extension in custom_rules:
            return custom_rules[record.extension], f"custom rule for {record.extension}"

        if organize_mode == "smart":
            month_folder = datetime.fromtimestamp(record.modified_at).strftime("%Y-%m")
            if record.category == "Others":
                return f"Others/{month_folder}", "smart fallback by month"
            if record.category == "Documents" and any(token in record.name.lower() for token in {"invoice", "receipt", "statement"}):
                return "Documents/Finance", "document keyword refinement"
            if record.category == "Code":
                return "Code/Source", "code refinement"
            return f"{record.category}/{month_folder}", "smart category + month"

        if organize_mode == "type":
            return record.category, f"type classification: {record.category}"

        if organize_mode == "date":
            return datetime.fromtimestamp(record.modified_at).strftime("%Y-%m"), "date bucket"

        if organize_mode == "size":
            if record.size < 1_000_000:
                return "Small_Files", "size bucket < 1 MB"
            if record.size < 10_000_000:
                return "Medium_Files", "size bucket < 10 MB"
            if record.size < 100_000_000:
                return "Large_Files", "size bucket < 100 MB"
            return "Huge_Files", "size bucket >= 100 MB"

        return "Others", "default fallback"


    def build_plan(
        self,
        folder_path: str,
        organize_mode: str,
        rename_enabled: bool,
        duplicate_enabled: bool,
        custom_rules: dict[str, str],
    ) -> tuple[list[PlanAction], ScanResult]:
        scan_result = self.scan_root_files(folder_path)
        actions: list[PlanAction] = []
        reserved_targets: set[str] = set()
        duplicate_lookup = self.build_duplicate_lookup(scan_result.duplicate_groups) if duplicate_enabled else {}

        for record in sorted(scan_result.files, key=lambda item: item.name.lower()):
            if duplicate_enabled and record.path in duplicate_lookup:
                actions.append(
                    PlanAction(
                        action="duplicate",
                        source=record.path,
                        target=duplicate_lookup[record.path],
                        category=record.category,
                        reason="same SHA-256 hash as existing file",
                    )
                )
                continue

            destination_name = sanitize_file_name(record.name) if rename_enabled else record.name
            folder_name, reason = self.get_destination_folder(record, organize_mode, custom_rules)
            destination_folder = os.path.join(folder_path, *folder_name.split("/"))
            destination_path = build_unique_path(destination_folder, destination_name, reserved_targets)
            reserved_targets.add(destination_path)

            actions.append(
                PlanAction(
                    action="move",
                    source=record.path,
                    target=destination_path,
                    category=record.category,
                    reason=reason,
                )
            )
        return actions, scan_result


    def build_duplicate_lookup(self, duplicate_groups: list[list[str]]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for group in duplicate_groups:
            sorted_group = sorted(group, key=lambda path: (os.path.getmtime(path), os.path.getsize(path), path))
            keeper = sorted_group[0]
            for duplicate_path in sorted_group[1:]:
                lookup[duplicate_path] = keeper
        return lookup


    def find_duplicate_groups(self, records: list[FileRecord]) -> list[list[str]]:
        by_size: dict[int, list[FileRecord]] = defaultdict(list)
        for record in records:
            by_size[record.size].append(record)

        partial_candidates: list[FileRecord] = []
        for group in by_size.values():
            if len(group) > 1:
                partial_candidates.extend(group)

        if not partial_candidates:
            return []

        partial_groups: dict[tuple[int, str], list[FileRecord]] = defaultdict(list)
        with ThreadPoolExecutor(max_workers=MAX_HASH_WORKERS) as executor:
            future_map = {executor.submit(partial_hash, record.path): record for record in partial_candidates}
            for future, record in future_map.items():
                try:
                    digest = future.result()
                except OSError:
                    continue
                partial_groups[(record.size, digest)].append(record)

        full_candidates: list[FileRecord] = []
        for group in partial_groups.values():
            if len(group) > 1:
                full_candidates.extend(group)

        if not full_candidates:
            return []

        full_groups: dict[str, list[str]] = defaultdict(list)
        with ThreadPoolExecutor(max_workers=MAX_HASH_WORKERS) as executor:
            future_map = {executor.submit(full_hash, record.path): record for record in full_candidates}
            for future, record in future_map.items():
                try:
                    digest = future.result()
                except OSError:
                    continue
                full_groups[digest].append(record.path)

        return [group for group in full_groups.values() if len(group) > 1]


    @staticmethod
    def is_noisy_name(file_name: str) -> bool:
        return bool(re.search(r"\s{2,}|[^A-Za-z0-9._ -]", file_name)) or file_name != sanitize_file_name(file_name)


class SmartFileOrganizerPro:
    @staticmethod
    def get_app_dir() -> str:
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    @staticmethod
    def get_resource_path(*parts: str) -> str:
        if getattr(sys, "frozen", False):
            base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, *parts)

    def __init__(self) -> None:
        self.engine = FileOrganizerEngine()
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1380x900")
        self.root.minsize(1180, 760)
        self.root.configure(bg=BG)

        self.folder_path = ""
        self.move_log: list[tuple[str, str]] = []
        self.duplicate_log: list[tuple[str, str]] = []
        self.last_plan: list[PlanAction] = []
        self.last_scan = ScanResult()
        self.last_snapshot: set[tuple[str, int, int]] = set()
        self.auto_mode_job: str | None = None
        self.is_busy = False
        self.is_ai_scanning = False
        self.last_ai_analysis: dict = {}
        self.base_dir = self.get_app_dir()
        self.undo_log_path = os.path.join(self.base_dir, "undo_log.json")
        self.log_file_path = os.path.join(self.base_dir, "app.log")

        self.organize_mode_var = tk.StringVar(value="smart")
        self.rename_var = tk.BooleanVar(value=True)
        self.duplicate_var = tk.BooleanVar(value=True)
        self.auto_mode_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value=f"{APP_NAME} {APP_VERSION} ready. Choose a folder to begin.")
        self.folder_var = tk.StringVar(value="No folder selected")
        self.progress_var = tk.StringVar(value="0%")
        self.progress_detail_var = tk.StringVar(value="0 / 0")
        self.current_file_var = tk.StringVar(value="Waiting...")
        self.scan_summary_var = tk.StringVar(value="Files: 0 | Duplicates: 0 | Categories ready")
        self.ai_summary_var = tk.StringVar(value="No scan yet")

        self.configure_logging()
        self.configure_styles()
        self.build_ui()
        self.configure_window_icon()
        self.render_ai_insights(self.build_local_analysis())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def configure_logging(self) -> None:
        logging.basicConfig(
            filename=self.log_file_path,
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            force=True,
        )

    def configure_window_icon(self) -> None:
        png_icon_path = self.get_resource_path("assets", "smart_file_organizer_pro.png")
        ico_icon_path = self.get_resource_path("assets", "smart_file_organizer_pro.ico")
        try:
            if os.path.exists(png_icon_path):
                self.window_icon = tk.PhotoImage(file=png_icon_path)
                self.root.iconphoto(True, self.window_icon)
            if os.path.exists(ico_icon_path):
                self.root.iconbitmap(ico_icon_path)
        except Exception as error:
            logging.error("Failed to load app icon: %s", error)

    def configure_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE, bordercolor=BORDER)
        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD, relief="flat")
        style.configure("SoftCard.TFrame", background=CARD_SOFT, relief="flat")
        style.configure("App.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=CARD, foreground=TEXT_MUTED, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI Semibold", 22))
        style.configure("Section.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI Semibold", 12))
        style.configure("HeroStat.TLabel", background=CARD_SOFT, foreground=TEXT, font=("Segoe UI", 10, "bold"))
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground=INK,
            bordercolor=ACCENT,
            darkcolor=ACCENT,
            lightcolor=ACCENT,
            relief="flat",
            focusthickness=0,
            focuscolor=ACCENT,
            font=("Segoe UI Semibold", 10),
            padding=(16, 11),
        )
        style.map(
            "Accent.TButton",
            background=[("pressed", "#24a79b"), ("active", "#51ddd2"), ("disabled", "#335b63")],
            foreground=[("disabled", "#8aa2b3")],
            bordercolor=[("pressed", "#24a79b"), ("active", "#51ddd2"), ("disabled", "#335b63")],
        )
        style.configure(
            "Alt.TButton",
            background=ACCENT_ALT,
            foreground=INK,
            bordercolor=ACCENT_ALT,
            darkcolor=ACCENT_ALT,
            lightcolor=ACCENT_ALT,
            relief="flat",
            focusthickness=0,
            focuscolor=ACCENT_ALT,
            font=("Segoe UI Semibold", 10),
            padding=(16, 11),
        )
        style.map(
            "Alt.TButton",
            background=[("pressed", "#4b8fd2"), ("active", "#8ec8ff"), ("disabled", "#364e66")],
            foreground=[("disabled", "#8aa2b3")],
            bordercolor=[("pressed", "#4b8fd2"), ("active", "#8ec8ff"), ("disabled", "#364e66")],
        )
        style.configure(
            "Ghost.TButton",
            background=SURFACE_ALT,
            foreground=TEXT,
            bordercolor=BORDER,
            darkcolor=SURFACE_ALT,
            lightcolor=SURFACE_ALT,
            relief="solid",
            borderwidth=1,
            focusthickness=0,
            focuscolor=SURFACE_ALT,
            font=("Segoe UI Semibold", 10),
            padding=(16, 11),
        )
        style.map(
            "Ghost.TButton",
            background=[("pressed", "#14273d"), ("active", "#1c3350"), ("disabled", "#101b29")],
            foreground=[("disabled", "#6e8397")],
            bordercolor=[("pressed", "#35587b"), ("active", "#3b648c"), ("disabled", "#213344")],
        )
        style.configure(
            "Danger.TButton",
            background="#6b2831",
            foreground="#ffe9eb",
            bordercolor="#a54c58",
            darkcolor="#6b2831",
            lightcolor="#6b2831",
            relief="flat",
            focusthickness=0,
            focuscolor="#6b2831",
            font=("Segoe UI Semibold", 10),
            padding=(16, 11),
        )
        style.map(
            "Danger.TButton",
            background=[("pressed", "#571f27"), ("active", "#84404a"), ("disabled", "#3b2529")],
            foreground=[("disabled", "#b79aa0")],
            bordercolor=[("pressed", "#7c3843"), ("active", "#bb5d6a"), ("disabled", "#4f3438")],
        )
        style.configure(
            "App.TCheckbutton",
            background=CARD,
            foreground=TEXT,
            font=("Segoe UI", 10),
            padding=(2, 6),
            indicatormargin=(0, 0, 10, 0),
            indicatorcolor=SURFACE_ALT,
            indicatorbackground=SURFACE_ALT,
            indicatorforeground=TEXT,
            relief="flat",
            focusthickness=0,
            focuscolor=CARD,
        )
        style.map(
            "App.TCheckbutton",
            background=[("active", CARD), ("selected", CARD), ("disabled", CARD)],
            foreground=[("disabled", TEXT_MUTED)],
            indicatorcolor=[("selected", ACCENT), ("active", CARD_SOFT), ("disabled", SURFACE_ALT)],
            indicatorbackground=[("selected", ACCENT), ("active", CARD_SOFT), ("disabled", SURFACE_ALT)],
            indicatorforeground=[("selected", INK), ("disabled", TEXT_MUTED)],
        )
        style.configure(
            "App.TRadiobutton",
            background=CARD,
            foreground=TEXT,
            font=("Segoe UI", 10),
            padding=(2, 6),
            indicatormargin=(0, 0, 10, 0),
            indicatorcolor=SURFACE_ALT,
            indicatorbackground=SURFACE_ALT,
            indicatorforeground=TEXT,
            relief="flat",
            focusthickness=0,
            focuscolor=CARD,
        )
        style.map(
            "App.TRadiobutton",
            background=[("active", CARD), ("selected", CARD), ("disabled", CARD)],
            foreground=[("disabled", TEXT_MUTED)],
            indicatorcolor=[("selected", ACCENT_ALT), ("active", CARD_SOFT), ("disabled", SURFACE_ALT)],
            indicatorbackground=[("selected", ACCENT_ALT), ("active", CARD_SOFT), ("disabled", SURFACE_ALT)],
            indicatorforeground=[("selected", INK), ("disabled", TEXT_MUTED)],
        )
        style.configure(
            "App.Treeview",
            background=SURFACE,
            foreground=TEXT,
            fieldbackground=SURFACE,
            bordercolor=BORDER,
            rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure("App.Treeview.Heading", background=CARD_SOFT, foreground=TEXT, font=("Segoe UI", 10, "bold"))
        style.map("App.Treeview", background=[("selected", "#1e3f62")], foreground=[("selected", TEXT)])
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=SURFACE_ALT,
            background=ACCENT,
            bordercolor=BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )

    def build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        hero = ttk.Frame(self.root, style="Card.TFrame", padding=20)
        hero.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 12))
        hero.grid_columnconfigure(0, weight=1)
        hero.grid_columnconfigure(1, weight=0)

        header_left = ttk.Frame(hero, style="Card.TFrame")
        header_left.grid(row=0, column=0, sticky="w")
        ttk.Label(header_left, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header_left,
            text="Built for bigger folders, safer duplicate cleanup, smarter classification, and a calmer workflow.",
            style="Muted.TLabel",
            wraplength=760,
        ).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            header_left,
            text=f"Version {APP_VERSION} • {APP_PUBLISHER}",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 0))
        ttk.Label(header_left, textvariable=self.folder_var, style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(10, 0))

        hero_stats = ttk.Frame(hero, style="Card.TFrame")
        hero_stats.grid(row=0, column=1, sticky="e")
        self.create_hero_badge(hero_stats, self.scan_summary_var).grid(row=0, column=0, padx=6)
        self.create_hero_badge(hero_stats, self.ai_summary_var).grid(row=0, column=1, padx=6)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 18))

        left = ttk.Frame(body, style="Card.TFrame", padding=18)
        right = ttk.Frame(body, style="Card.TFrame", padding=18)
        body.add(left, weight=5)
        body.add(right, weight=6)

        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        self.build_action_card(left).grid(row=0, column=0, sticky="ew")
        self.build_option_card(left).grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self.build_insight_card(left).grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.build_rules_card(left).grid(row=3, column=0, sticky="nsew", pady=(14, 0))

        self.build_status_card(right).grid(row=0, column=0, sticky="ew")
        self.build_duplicate_card(right).grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self.build_preview_card(right).grid(row=2, column=0, sticky="nsew", pady=(14, 0))

    def create_hero_badge(self, parent: ttk.Frame, variable: tk.StringVar) -> ttk.Frame:
        frame = ttk.Frame(parent, style="SoftCard.TFrame", padding=(12, 10))
        ttk.Label(frame, textvariable=variable, style="HeroStat.TLabel").pack()
        return frame

    def build_card_shell(self, parent: ttk.Frame, title: str, subtitle: str) -> tuple[ttk.Frame, ttk.Frame]:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        ttk.Label(card, text=title, style="Section.TLabel").pack(anchor="w")
        ttk.Label(card, text=subtitle, style="Muted.TLabel", wraplength=560).pack(anchor="w", pady=(4, 12))
        content = ttk.Frame(card, style="Card.TFrame")
        content.pack(fill="both", expand=True)
        return card, content

    def build_action_card(self, parent: ttk.Frame) -> ttk.Frame:
        card, content = self.build_card_shell(
            parent,
            "Operations",
            "Preview and run the organizer with scalable planning logic. Large folders stay smoother because metadata and hashing are staged.",
        )
        for column in range(4):
            content.grid_columnconfigure(column, weight=1)

        ttk.Button(content, text="Select Folder", style="Accent.TButton", command=self.select_folder).grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self.btn_ai_scan = ttk.Button(content, text="AI Scan", style="Alt.TButton", command=self.run_ai_scan)
        self.btn_ai_scan.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self.btn_smart_organize = ttk.Button(content, text="Smart Organize", style="Alt.TButton", command=self.smart_organize)
        self.btn_smart_organize.grid(row=0, column=2, sticky="ew", padx=6, pady=6)
        ttk.Button(content, text="About", style="Ghost.TButton", command=self.show_about).grid(row=0, column=3, sticky="ew", padx=6, pady=6)
        ttk.Button(content, text="Preview Changes", style="Ghost.TButton", command=self.preview_changes).grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        ttk.Button(content, text="Start Organizing", style="Accent.TButton", command=self.organize_files).grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(content, text="Undo Last Run", style="Danger.TButton", command=self.undo).grid(row=1, column=2, sticky="ew", padx=6, pady=6)
        return card

    def build_option_card(self, parent: ttk.Frame) -> ttk.Frame:
        card, content = self.build_card_shell(
            parent,
            "Strategy",
            "Use Smart mode for the best default classification flow. It combines type signals, keywords, and timeline grouping.",
        )

        mode_row = ttk.Frame(content, style="SoftCard.TFrame", padding=(14, 10))
        mode_row.pack(fill="x")
        for label, value in [("Smart", "smart"), ("Type", "type"), ("Date", "date"), ("Size", "size")]:
            ttk.Radiobutton(mode_row, text=label, value=value, variable=self.organize_mode_var, style="App.TRadiobutton").pack(side="left", padx=(0, 14))

        options_row = ttk.Frame(content, style="SoftCard.TFrame", padding=(14, 10))
        options_row.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(options_row, text="Clean file names", variable=self.rename_var, style="App.TCheckbutton").pack(anchor="w", pady=4)
        ttk.Checkbutton(options_row, text="Detect duplicates with staged SHA-256 hashing", variable=self.duplicate_var, style="App.TCheckbutton").pack(anchor="w", pady=4)
        ttk.Checkbutton(options_row, text="Watch folder and auto-organize new files", variable=self.auto_mode_var, style="App.TCheckbutton", command=self.toggle_auto_mode).pack(anchor="w", pady=4)
        return card

    def build_insight_card(self, parent: ttk.Frame) -> ttk.Frame:
        card, content = self.build_card_shell(
            parent,
            "AI + Scalability Notes",
            "This panel combines local analysis with optional ChatGPT recommendations and practical scale guidance for 1000+ files.",
        )
        self.ai_text = tk.Text(content, height=14, bg=SURFACE, fg=TEXT, relief="flat", insertbackground=TEXT, wrap="word", font=("Consolas", 10), padx=12, pady=12)
        self.ai_text.pack(fill="both", expand=True)
        return card

    def build_rules_card(self, parent: ttk.Frame) -> ttk.Frame:
        card, content = self.build_card_shell(
            parent,
            "Custom Rules",
            "Map extensions to folders. Example: `.pdf=Work_PDFs`. These rules override every other classification path.",
        )
        self.rules_text = tk.Text(content, height=10, bg=SURFACE, fg=TEXT, relief="flat", insertbackground=TEXT, wrap="none", font=("Consolas", 10), padx=12, pady=12)
        self.rules_text.pack(fill="both", expand=True)
        self.rules_text.insert("1.0", ".pdf=Work_PDFs\n.jpg=Personal_Images\n.png=Personal_Images\n.csv=Data_Sheets")
        return card

    def build_status_card(self, parent: ttk.Frame) -> ttk.Frame:
        card, content = self.build_card_shell(
            parent,
            "Run Status",
            "Progress updates stay focused on the current run and help make large batch operations easier to trust.",
        )
        ttk.Label(content, textvariable=self.status_var, style="App.TLabel", wraplength=620).pack(anchor="w")
        ttk.Label(content, textvariable=self.current_file_var, style="Muted.TLabel", wraplength=620).pack(anchor="w", pady=(8, 0))

        progress_row = ttk.Frame(content, style="Card.TFrame")
        progress_row.pack(fill="x", pady=(14, 0))
        self.progress = ttk.Progressbar(progress_row, orient="horizontal", mode="determinate", maximum=100, style="Horizontal.TProgressbar")
        self.progress.pack(fill="x")

        footer = ttk.Frame(content, style="Card.TFrame")
        footer.pack(fill="x", pady=(8, 0))
        ttk.Label(footer, textvariable=self.progress_var, style="App.TLabel").pack(side="left")
        ttk.Label(footer, textvariable=self.progress_detail_var, style="Muted.TLabel").pack(side="right")
        return card

    def build_duplicate_card(self, parent: ttk.Frame) -> ttk.Frame:
        card, content = self.build_card_shell(
            parent,
            "Duplicate Detection",
            "Duplicate groups are detected by size, then partial hash, then full SHA-256 hash. That keeps the accurate path without hashing every file fully.",
        )
        columns = ("file", "keeper", "status")
        self.duplicate_tree = ttk.Treeview(content, columns=columns, show="headings", style="App.Treeview", height=6)
        self.duplicate_tree.heading("file", text="Duplicate")
        self.duplicate_tree.heading("keeper", text="Kept File")
        self.duplicate_tree.heading("status", text="Status")
        self.duplicate_tree.column("file", width=240, anchor="w")
        self.duplicate_tree.column("keeper", width=240, anchor="w")
        self.duplicate_tree.column("status", width=120, anchor="center")
        self.duplicate_tree.pack(fill="x")
        return card

    def build_preview_card(self, parent: ttk.Frame) -> ttk.Frame:
        card, content = self.build_card_shell(
            parent,
            "Preview Studio",
            "Review every planned action before execution. Classification reasons are shown so the logic is inspectable rather than mysterious.",
        )
        columns = ("source", "target", "category", "reason")
        self.preview_tree = ttk.Treeview(content, columns=columns, show="headings", style="App.Treeview")
        for name, label, width in [
            ("source", "Source", 220),
            ("target", "Target", 250),
            ("category", "Category", 100),
            ("reason", "Reason", 240),
        ]:
            self.preview_tree.heading(name, text=label)
            self.preview_tree.column(name, width=width, anchor="w")
        self.preview_tree.pack(fill="both", expand=True)
        return card

    def build_local_analysis(self) -> dict:
        if not self.folder_path or not os.path.isdir(self.folder_path):
            return {
                "ai_source": "Local AI",
                "total_files": 0,
                "duplicates": 0,
                "suggested_mode": "smart",
                "suggest_rename": True,
                "suggest_duplicates": True,
                "suggested_rules": {},
                "insight_lines": [
                    "Select a folder to unlock analysis.",
                    "The upgraded planner is designed for large batches and avoids unnecessary repeated scans.",
                ],
                "folder_structure": ["Images/2026-04", "Documents/Finance", "Code/Source"],
                "cleanup_ideas": [
                    "Stage duplicate hashing by size and partial hash before full hash.",
                    "Keep custom rules small and focused so classification stays predictable.",
                ],
                "duplicate_handling": "Duplicate detection is ready when you enable it.",
                "thinking_summary": "Waiting for a folder so the local planner can compute categories, naming quality, and duplicate risk.",
                "scalability_notes": [
                    "Use os.scandir metadata instead of repeated listdir/stat loops.",
                    "Hash only likely duplicate candidates instead of every file.",
                    "Keep the UI on summaries and tree views, not giant text redraws.",
                ],
            }

        scan = self.last_scan if self.last_scan.files and self.folder_path else self.engine.scan_root_files(self.folder_path)
        summary = Counter(scan.summary)
        suggested_mode = "smart"
        if summary["Others"] > max(summary["Documents"], summary["Images"], summary["Videos"]):
            suggested_mode = "date"
        if summary["Documents"] >= max(summary["Images"], summary["Videos"], 1):
            suggested_mode = "smart"

        top_extensions = dict(scan.extension_counts.most_common(5))
        suggested_rules: dict[str, str] = {}
        for extension, count in top_extensions.items():
            if count < 4:
                continue
            if extension in {".csv", ".xlsx"}:
                suggested_rules[extension] = "Data_Sheets"
            elif extension in {".jpg", ".jpeg", ".png", ".webp"}:
                suggested_rules[extension] = "Personal_Images"
            elif extension == ".pdf":
                suggested_rules[extension] = "Work_PDFs"

        largest_category = max(summary or {"Others": 0}, key=lambda key: summary[key] if summary else 0)
        return {
            "ai_source": "Local AI",
            "total_files": len(scan.files),
            "duplicates": scan.duplicates,
            "suggested_mode": suggested_mode,
            "suggest_rename": scan.noisy_names > 0,
            "suggest_duplicates": scan.duplicates > 0,
            "suggested_rules": suggested_rules,
            "insight_lines": [
                f"Detected {len(scan.files)} active files and {scan.duplicates} duplicate candidates.",
                f"Largest category is {largest_category}. Smart mode is the best default when categories and dates both matter.",
                f"Naming cleanup is {'recommended' if scan.noisy_names else 'optional'} based on filename quality.",
                f"Top extensions: {', '.join(f'{ext}:{count}' for ext, count in top_extensions.items()) or 'none'}",
            ],
            "folder_structure": [
                f"{largest_category}/{datetime.now().strftime('%Y-%m')}",
                "Documents/Finance",
                "Code/Source",
            ],
            "cleanup_ideas": [
                "Enable duplicate cleanup when repeated exports or downloads exist.",
                "Use custom rules only for stable business folders like PDFs, data sheets, or screenshots.",
            ],
            "duplicate_handling": (
                "Duplicates were detected, so staged SHA-256 cleanup is worth enabling."
                if scan.duplicates
                else "No duplicate pressure right now, but detection remains ready for future bulk imports."
            ),
            "thinking_summary": (
                f"Scanned metadata for {len(scan.files)} files, classified them with extensions, MIME hints, and keywords, "
                f"then used multi-stage hashing only on same-size candidates."
            ),
            "scalability_notes": [
                "Metadata is collected in one scan and reused for planning and analysis.",
                "Duplicate detection hashes only collision candidates, which scales much better for 1000+ files.",
                "Preview data is rendered in table form to avoid expensive full-text repainting.",
            ],
        }

    def try_chatgpt_analysis(self, local_analysis: dict) -> dict | None:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None

        body = {
            "model": os.environ.get("OPENAI_MODEL", "gpt-5"),
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are a senior file automation assistant. Return strict JSON with keys: "
                                "suggested_mode, suggest_rename, suggest_duplicates, suggested_rules, folder_structure, "
                                "cleanup_ideas, duplicate_handling, thinking_summary, insight_lines, scalability_notes."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(local_analysis)}],
                },
            ],
        }

        request = urlrequest.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )

        try:
            with urlrequest.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return None

        output_text = ""
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text += content.get("text", "")

        if not output_text.strip():
            return None

        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError:
            return None

        merged = dict(local_analysis)
        for key in [
            "suggested_mode",
            "suggest_rename",
            "suggest_duplicates",
            "suggested_rules",
            "folder_structure",
            "cleanup_ideas",
            "duplicate_handling",
            "thinking_summary",
            "insight_lines",
            "scalability_notes",
        ]:
            value = parsed.get(key)
            if value not in (None, "", [], {}):
                merged[key] = value
        merged["ai_source"] = "ChatGPT"
        return merged

    def render_ai_insights(self, analysis: dict) -> None:
        self.last_ai_analysis = analysis
        self.ai_summary_var.set(
            f"{analysis['ai_source']} | Files {analysis['total_files']} | Duplicates {analysis['duplicates']} | Mode {analysis['suggested_mode'].title()}"
        )
        self.ai_text.config(state="normal")
        self.ai_text.delete("1.0", tk.END)
        self.ai_text.insert(tk.END, "AI thinking\n")
        self.ai_text.insert(tk.END, f"{analysis['thinking_summary']}\n\n")
        self.ai_text.insert(tk.END, "Recommendations\n")
        for line in analysis["insight_lines"]:
            self.ai_text.insert(tk.END, f"* {line}\n")
        self.ai_text.insert(tk.END, "\nScalability upgrades\n")
        for line in analysis["scalability_notes"]:
            self.ai_text.insert(tk.END, f"* {line}\n")
        self.ai_text.insert(tk.END, "\nFolder structure ideas\n")
        for line in analysis["folder_structure"]:
            self.ai_text.insert(tk.END, f"* {line}\n")
        self.ai_text.insert(tk.END, "\nCleanup ideas\n")
        for line in analysis["cleanup_ideas"]:
            self.ai_text.insert(tk.END, f"* {line}\n")
        self.ai_text.insert(tk.END, f"\nDuplicate handling\n* {analysis['duplicate_handling']}\n")
        self.ai_text.config(state="disabled")

    def snapshot_root_files(self) -> set[tuple[str, int, int]]:
        if not self.folder_path or not os.path.isdir(self.folder_path):
            return set()
        snapshot: set[tuple[str, int, int]] = set()
        try:
            with os.scandir(self.folder_path) as entries:
                for entry in entries:
                    if not entry.is_file() or has_system_attribute(entry.path):
                        continue
                    try:
                        stat_result = entry.stat()
                    except OSError:
                        continue
                    snapshot.add((entry.name, int(stat_result.st_mtime), stat_result.st_size))
        except OSError:
            return set()
        return snapshot

    def run_scan_and_plan(self) -> tuple[list[PlanAction], ScanResult]:
        custom_rules = parse_custom_rules(self.rules_text.get("1.0", tk.END))
        plan, scan = self.engine.build_plan(
            folder_path=self.folder_path,
            organize_mode=self.organize_mode_var.get(),
            rename_enabled=self.rename_var.get(),
            duplicate_enabled=self.duplicate_var.get(),
            custom_rules=custom_rules,
        )
        self.last_plan = plan
        self.last_scan = scan
        return plan, scan

    def render_scan_summary(self) -> None:
        total_files = len(self.last_scan.files)
        summary = ", ".join(f"{name}: {count}" for name, count in self.last_scan.summary.most_common(4)) or "No files"
        self.scan_summary_var.set(f"Files {total_files} | Duplicates {self.last_scan.duplicates} | {summary}")

    def render_preview(self, plan: list[PlanAction]) -> None:
        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        for action in plan:
            source_name = os.path.basename(action.source)
            target_name = os.path.relpath(action.target, self.folder_path) if self.folder_path else action.target
            if action.action == "duplicate":
                target_name = f"_duplicates/{source_name} (duplicate of {os.path.basename(action.target)})"
            self.preview_tree.insert("", "end", values=(source_name, target_name, action.category, action.reason))

    def render_duplicates(self, plan: list[PlanAction]) -> None:
        for item in self.duplicate_tree.get_children():
            self.duplicate_tree.delete(item)
        duplicate_actions = [action for action in plan if action.action == "duplicate"]
        if not duplicate_actions:
            self.duplicate_tree.insert("", "end", values=("No duplicates flagged", "-", "Ready"))
            return
        for action in duplicate_actions:
            self.duplicate_tree.insert(
                "",
                "end",
                values=(os.path.basename(action.source), os.path.basename(action.target), "Flagged"),
            )

    def update_status(self, message: str) -> None:
        self.status_var.set(message)
        self.root.update_idletasks()

    def update_progress(self, processed: int, total: int, current_file: str = "Waiting...") -> None:
        percentage = int((processed / total) * 100) if total else 0
        self.progress["value"] = percentage
        self.progress_var.set(f"{percentage}%")
        self.progress_detail_var.set(f"{processed} / {total}")
        self.current_file_var.set(f"Current file: {current_file}")
        self.root.update_idletasks()

    def load_undo_log(self) -> list[dict[str, str]]:
        if not os.path.exists(self.undo_log_path):
            return []
        try:
            with open(self.undo_log_path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict) and "from" in item and "to" in item]
        except (OSError, json.JSONDecodeError) as error:
            logging.error("Failed to load undo log: %s", error)
        return []

    def save_undo_log(self, entries: list[dict[str, str]]) -> None:
        try:
            with open(self.undo_log_path, "w", encoding="utf-8") as file_handle:
                json.dump(entries, file_handle, indent=2)
        except OSError as error:
            logging.error("Failed to save undo log: %s", error)

    def append_undo_entry(self, original_path: str, new_path: str) -> None:
        entries = self.load_undo_log()
        entries.append({"from": original_path, "to": new_path})
        self.save_undo_log(entries)

    def clear_undo_log(self) -> None:
        self.save_undo_log([])

    def post_status(self, message: str) -> None:
        self.root.after(0, lambda: self.update_status(message))

    def post_progress(self, processed: int, total: int, current_file: str = "Waiting...") -> None:
        self.root.after(0, lambda: self.update_progress(processed, total, current_file))

    def post_refresh_after_run(self, scan: ScanResult, plan: list[PlanAction], analysis: dict, message: str) -> None:
        def callback() -> None:
            self.last_scan = scan
            self.render_scan_summary()
            self.render_preview(plan)
            self.render_duplicates(plan)
            self.render_ai_insights(analysis)
            self.update_progress(len(plan), len(plan), "Completed")
            self.update_status(message)

        self.root.after(0, callback)

    def set_analysis_button_state(self, enabled: bool) -> None:
        if hasattr(self, "btn_ai_scan"):
            self.btn_ai_scan.config(state=("normal" if enabled else "disabled"))
        if hasattr(self, "btn_smart_organize"):
            self.btn_smart_organize.config(state=("normal" if enabled else "disabled"))

    def begin_ai_scan_ui(self, action_label: str = "AI Scan") -> None:
        self.is_ai_scanning = True
        self.set_analysis_button_state(False)
        self.update_progress(0, 0, f"Preparing {action_label}...")
        self.update_status(f"\U0001F50D {action_label} in progress...")

    def post_ai_scan_progress(self, processed: int, total: int, current_file: str, action_label: str = "AI Scan") -> None:
        # UI updates must stay on Tk's main thread.
        def callback() -> None:
            self.update_progress(processed, total, current_file)
            self.status_var.set(f"\U0001F50D {action_label} in progress...")

        self.root.after(0, callback)

    def post_ai_scan_status(self, message: str) -> None:
        self.root.after(0, lambda: self.update_status(message))

    def finish_ai_scan_success(self, analysis: dict, scan: ScanResult, action_label: str = "AI Scan") -> None:
        self.is_ai_scanning = False
        self.set_analysis_button_state(True)
        self.last_scan = scan
        self.render_scan_summary()
        self.render_ai_insights(analysis)
        total_files = len(scan.files)
        if total_files == 0:
            self.update_progress(0, 0, "Folder is empty")
            self.update_status(f"\u2705 {action_label} complete. This folder has no files to analyze.")
            return
        self.update_progress(total_files, total_files, f"{action_label} complete")
        self.update_status(f"\u2705 {action_label} complete")

    def finish_ai_scan_error(self, user_message: str, log_error: Exception | None = None) -> None:
        self.is_ai_scanning = False
        self.set_analysis_button_state(True)
        self.update_progress(0, 0, "AI scan stopped")
        self.update_status(user_message)
        if log_error is not None:
            logging.error("AI scan failed: %s", log_error)

    def show_about(self) -> None:
        messagebox.showinfo(
            f"About {APP_NAME}",
            (
                f"{APP_NAME}\n"
                f"Version: {APP_VERSION}\n"
                f"Publisher: {APP_PUBLISHER}\n\n"
                "Release-ready desktop organizer with smart classification,\n"
                "duplicate detection, persistent undo, and responsive background processing."
            ),
        )

    def validate_current_folder(self) -> bool:
        if not self.folder_path:
            self.update_status("Select a folder first.")
            return False
        is_safe, message = validate_selected_folder(self.folder_path)
        if not is_safe:
            messagebox.showwarning("Safety Shield", message)
            self.update_status(message)
            return False
        return True

    def preview_changes(self) -> None:
        if not self.validate_current_folder():
            return
        try:
            plan, _scan = self.run_scan_and_plan()
        except RuntimeError as error:
            self.update_status(str(error))
            return

        self.render_scan_summary()
        self.render_preview(plan)
        self.render_duplicates(plan)
        self.render_ai_insights(self.build_local_analysis())
        self.update_progress(0, len(plan), "Preview ready")
        self.update_status(f"Preview ready with {len(plan)} planned actions.")

    def organize_files(self, auto_trigger: bool = False) -> None:
        if self.is_busy or not self.validate_current_folder():
            return

        try:
            plan, scan = self.run_scan_and_plan()
        except RuntimeError as error:
            self.update_status(str(error))
            return

        self.render_scan_summary()
        self.render_preview(plan)
        self.render_duplicates(plan)

        if not plan:
            self.update_progress(0, 0, "Nothing to organize")
            self.update_status("Nothing to organize.")
            self.last_snapshot = self.snapshot_root_files()
            return

        if not auto_trigger:
            confirm = messagebox.askyesno("Confirm Organization", f"Run {len(plan)} planned actions?")
            if not confirm:
                self.update_status("Organization cancelled.")
                return

        self.is_busy = True
        self.move_log = []
        self.duplicate_log = []
        self.clear_undo_log()
        self.update_status("Organization started in background...")

        threading.Thread(
            target=self._organize_worker,
            args=(plan, scan, auto_trigger),
            daemon=True,
        ).start()

    def _organize_worker(self, plan: list[PlanAction], scan: ScanResult, auto_trigger: bool) -> None:
        moved = 0
        duplicates = 0
        errors = 0

        try:
            for index, action in enumerate(plan, start=1):
                current_name = os.path.basename(action.source)
                self.post_progress(index - 1, len(plan), current_name)
                self.post_status(f"Processing {index}/{len(plan)}: {current_name}")

                try:
                    if action.action == "move":
                        os.makedirs(os.path.dirname(action.target), exist_ok=True)
                        shutil.move(action.source, action.target)
                        self.move_log.append((action.source, action.target))
                        self.append_undo_entry(action.source, action.target)
                        logging.info("Moved file: %s -> %s", action.source, action.target)
                        moved += 1
                    else:
                        duplicates_dir = os.path.join(self.folder_path, "_duplicates")
                        os.makedirs(duplicates_dir, exist_ok=True)
                        duplicate_target = build_unique_path(duplicates_dir, os.path.basename(action.source))
                        shutil.move(action.source, duplicate_target)
                        self.duplicate_log.append((action.source, duplicate_target))
                        self.append_undo_entry(action.source, duplicate_target)
                        logging.info("Duplicate detected: %s -> %s", action.source, duplicate_target)
                        duplicates += 1
                except Exception as error:
                    errors += 1
                    logging.error("Failed processing %s: %s", action.source, error)
                    self.post_status(f"Skipped {current_name} due to an error. Continuing...")

                self.post_progress(index, len(plan), current_name)
        finally:
            self.is_busy = False

        self.last_snapshot = self.snapshot_root_files()
        self.last_scan = scan
        analysis = self.build_local_analysis()
        if auto_trigger:
            status_message = f"Auto mode completed. Moved {moved} files, isolated {duplicates} duplicates, errors {errors}."
        else:
            status_message = f"Completed. Moved {moved} files, isolated {duplicates} duplicates, errors {errors}."
        self.post_refresh_after_run(scan, plan, analysis, status_message)

    def undo(self) -> None:
        undo_entries = self.load_undo_log()
        if not undo_entries and not self.move_log and not self.duplicate_log:
            self.update_status("Nothing to undo.")
            return

        for entry in reversed(undo_entries):
            original_path = entry["from"]
            moved_path = entry["to"]
            if not os.path.exists(moved_path):
                continue
            try:
                os.makedirs(os.path.dirname(original_path), exist_ok=True)
                shutil.move(moved_path, original_path)
                logging.info("Undo move: %s -> %s", moved_path, original_path)
            except Exception as error:
                logging.error("Undo failed for %s: %s", moved_path, error)

        self.move_log.clear()
        self.duplicate_log.clear()
        self.clear_undo_log()
        self.last_snapshot = self.snapshot_root_files()
        try:
            _, self.last_scan = self.run_scan_and_plan()
        except RuntimeError:
            self.last_scan = ScanResult()
        self.render_scan_summary()
        self.render_preview([])
        self.render_duplicates([])
        self.update_progress(0, 0, "Undo completed")
        self.update_status("Last run has been undone.")

    def run_ai_scan(self) -> None:
        if self.is_ai_scanning:
            self.update_status("\U0001F50D AI Scan is already running...")
            return
        if not self.validate_current_folder():
            return

        self.begin_ai_scan_ui("AI Scan")
        custom_rules = parse_custom_rules(self.rules_text.get("1.0", tk.END))
        organize_mode = self.organize_mode_var.get()
        rename_enabled = self.rename_var.get()
        duplicate_enabled = self.duplicate_var.get()
        folder_path = self.folder_path

        def worker() -> None:
            try:
                scan = self.engine.scan_root_files(
                    folder_path=folder_path,
                    progress_callback=lambda processed, total, current_file: self.post_ai_scan_progress(
                        processed, total, current_file, "AI Scan"
                    ),
                    status_callback=self.post_ai_scan_status,
                )
                if not scan.files:
                    empty_analysis = {
                        "ai_source": "Local AI",
                        "total_files": 0,
                        "duplicates": 0,
                        "suggested_mode": organize_mode,
                        "suggest_rename": rename_enabled,
                        "suggest_duplicates": duplicate_enabled,
                        "suggested_rules": custom_rules,
                        "insight_lines": [
                            "The selected folder is empty.",
                            "Add files to this folder and run AI Scan again.",
                        ],
                        "folder_structure": ["No files yet"],
                        "cleanup_ideas": ["Drop files into the folder and scan again to generate insights."],
                        "duplicate_handling": "No duplicate handling needed because no files were found.",
                        "thinking_summary": "The AI scan finished quickly because the selected folder has no files to inspect.",
                        "scalability_notes": [
                            "Empty folders are handled immediately without blocking the UI.",
                        ],
                    }
                    self.root.after(0, lambda: self.finish_ai_scan_success(empty_analysis, scan, "AI Scan"))
                    return

                self.last_scan = scan
                local_analysis = self.build_local_analysis()
                merged = self.try_chatgpt_analysis(local_analysis) or local_analysis
                self.root.after(0, lambda: self.finish_ai_scan_success(merged, scan, "AI Scan"))
            except RuntimeError as error:
                self.root.after(0, lambda error=error: self.finish_ai_scan_error(f"AI Scan could not read this folder: {error}", error))
            except Exception as error:
                self.root.after(0, lambda error=error: self.finish_ai_scan_error("AI Scan stopped due to an unexpected error.", error))

        threading.Thread(target=worker, daemon=True).start()

    def smart_organize(self) -> None:
        if self.is_ai_scanning:
            self.update_status("\U0001F50D Smart Organize is already running...")
            return
        if not self.validate_current_folder():
            return

        self.begin_ai_scan_ui("Smart Organize")
        custom_rules = parse_custom_rules(self.rules_text.get("1.0", tk.END))
        folder_path = self.folder_path

        def worker() -> None:
            try:
                scan = self.engine.scan_root_files(
                    folder_path=folder_path,
                    progress_callback=lambda processed, total, current_file: self.post_ai_scan_progress(
                        processed, total, current_file, "Smart Organize"
                    ),
                    status_callback=self.post_ai_scan_status,
                )

                if not scan.files:
                    empty_analysis = {
                        "ai_source": "Local AI",
                        "total_files": 0,
                        "duplicates": 0,
                        "suggested_mode": "smart",
                        "suggest_rename": True,
                        "suggest_duplicates": True,
                        "suggested_rules": custom_rules,
                        "insight_lines": [
                            "Smart Organize found an empty folder.",
                            "Add files first, then rerun Smart Organize.",
                        ],
                        "folder_structure": ["No files yet"],
                        "cleanup_ideas": ["Add files to generate recommendations automatically."],
                        "duplicate_handling": "Nothing to organize because the folder is empty.",
                        "thinking_summary": "Smart Organize completed immediately because there were no files to analyze.",
                        "scalability_notes": ["Empty folders are handled safely and instantly."],
                    }
                    self.root.after(0, lambda: self.finish_ai_scan_success(empty_analysis, scan, "Smart Organize"))
                    return

                self.last_scan = scan
                analysis = self.try_chatgpt_analysis(self.build_local_analysis()) or self.build_local_analysis()
                self.root.after(0, lambda analysis=analysis, scan=scan: self.finish_smart_organize(analysis, scan))
            except RuntimeError as error:
                self.root.after(
                    0,
                    lambda error=error: self.finish_ai_scan_error(
                        f"Smart Organize could not read this folder: {error}",
                        error,
                    ),
                )
            except Exception as error:
                self.root.after(
                    0,
                    lambda error=error: self.finish_ai_scan_error(
                        "Smart Organize stopped due to an unexpected error.",
                        error,
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def finish_smart_organize(self, analysis: dict, scan: ScanResult) -> None:
        self.render_ai_insights(analysis)
        self.organize_mode_var.set(analysis.get("suggested_mode", "smart"))
        self.rename_var.set(bool(analysis.get("suggest_rename", True)))
        self.duplicate_var.set(bool(analysis.get("suggest_duplicates", True)))

        suggested_rules = analysis.get("suggested_rules", {})
        if suggested_rules:
            self.rules_text.delete("1.0", tk.END)
            self.rules_text.insert("1.0", "\n".join(f"{extension}={folder}" for extension, folder in suggested_rules.items()))

        self.finish_ai_scan_success(analysis, scan, "Smart Organize")
        self.preview_changes()
        self.update_status("\u2705 Smart Organize complete. Recommended settings applied and preview refreshed.")

    def toggle_auto_mode(self) -> None:
        if self.auto_mode_var.get():
            if not self.folder_path:
                self.update_status("Choose a folder to enable auto mode. Opening folder picker...")
                self.select_folder()
                if not self.folder_path:
                    self.auto_mode_var.set(False)
                    self.update_status("Auto mode was not enabled because no folder was selected.")
                return
            self.start_auto_mode()
        else:
            self.stop_auto_mode("Auto mode disabled.")

    def start_auto_mode(self) -> None:
        if not self.validate_current_folder():
            self.auto_mode_var.set(False)
            return
        self.last_snapshot = self.snapshot_root_files()
        self.update_status("Auto mode is watching for new files.")
        self.schedule_auto_mode()

    def stop_auto_mode(self, message: str = "Auto mode stopped.") -> None:
        if self.auto_mode_job is not None:
            self.root.after_cancel(self.auto_mode_job)
            self.auto_mode_job = None
        self.update_status(message)

    def schedule_auto_mode(self) -> None:
        if self.auto_mode_job is not None:
            self.root.after_cancel(self.auto_mode_job)
        self.auto_mode_job = self.root.after(3000, self.auto_organize_check)

    def auto_organize_check(self) -> None:
        self.auto_mode_job = None
        if not self.auto_mode_var.get():
            return
        if not self.folder_path or self.is_busy:
            self.schedule_auto_mode()
            return

        current_snapshot = self.snapshot_root_files()
        new_files = current_snapshot - self.last_snapshot
        if new_files:
            self.update_status("Auto mode detected new files and is organizing them now.")
            self.organize_files(auto_trigger=True)
        else:
            self.last_snapshot = current_snapshot
        self.schedule_auto_mode()

    def select_folder(self) -> None:
        chosen_folder = filedialog.askdirectory()
        if not chosen_folder:
            return

        is_safe, message = validate_selected_folder(chosen_folder)
        if not is_safe:
            messagebox.showwarning("Safety Shield", message)
            self.update_status(message)
            return

        self.folder_path = chosen_folder
        self.folder_var.set(f"Selected folder: {self.folder_path}")
        self.last_snapshot = self.snapshot_root_files()
        try:
            _, self.last_scan = self.run_scan_and_plan()
        except RuntimeError:
            self.last_scan = ScanResult()
        self.render_scan_summary()
        self.render_preview([])
        self.render_duplicates([])
        self.render_ai_insights(self.build_local_analysis())
        self.update_progress(0, 0, "Waiting...")
        self.update_status("Folder selected and scanned.")
        if self.auto_mode_var.get():
            self.start_auto_mode()

    def on_close(self) -> None:
        self.stop_auto_mode("Closing organizer.")
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    SmartFileOrganizerPro().run()
