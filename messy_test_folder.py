from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import string
from datetime import datetime, timedelta
from pathlib import Path


TEXT_EXTENSIONS = [".txt", ".md", ".csv", ".log", ".json", ".rtf"]
BINARY_EXTENSIONS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".zip",
    ".rar",
    ".7z",
    ".mp3",
    ".wav",
    ".mp4",
    ".avi",
    ".mkv",
    ".exe",
    ".msi",
    ".ps1",
    ".py",
    ".js",
    ".html",
    ".css",
]

NOISY_NAMES = [
    "FINAL final FINAL report",
    "Screenshot 2026-04-06 at 10.14.22 PM",
    "IMG_0001",
    "New Microsoft Word Document",
    "invoice paid urgent",
    "resume latest latest",
    "Project Backup copy copy",
    "setup installer cracked notvirus",
    "Meeting Notes   April",
    "random___file__name",
    "very important data",
    "family_photo_edited_final",
    "podcast clip draft",
    "source code old",
    "archive backup temp",
]

KEYWORD_NAMES = [
    "invoice_april",
    "receipt_mega_store",
    "bank_statement",
    "vacation_photo",
    "camera_roll_export",
    "movie_trailer",
    "podcast_mix",
    "driver_installer",
    "project_source",
    "report_summary",
]

WEIRD_PREFIXES = [
    "  ",
    "__",
    "###",
    "copy of ",
    "NEW_",
    "OLD_",
    "zzz_",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an intentionally chaotic folder to test Smart File Organizer Pro."
    )
    parser.add_argument(
        "--target",
        default="extreme_messy_folder",
        help="Folder to create or refresh. Default: ./extreme_messy_folder",
    )
    parser.add_argument(
        "--files",
        type=int,
        default=100_000,
        help="How many messy root files to create. Default: 100000",
    )
    parser.add_argument(
        "--duplicates",
        type=int,
        default=5_000,
        help="How many duplicate files to create from existing files. Default: 5000",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for repeatable results. Default: 42",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the existing target folder instead of deleting it first.",
    )
    parser.add_argument(
        "--manifest-limit",
        type=int,
        default=250,
        help="How many files to include in the JSON manifest sample. Default: 250",
    )
    return parser.parse_args()


def random_name(rng: random.Random, extension: str) -> str:
    if rng.random() < 0.55:
        base = rng.choice(NOISY_NAMES)
    else:
        base = rng.choice(KEYWORD_NAMES)

    if rng.random() < 0.6:
        base = f"{rng.choice(WEIRD_PREFIXES)}{base}"
    if rng.random() < 0.75:
        base += rng.choice(["", " final", " FINAL", " copy", " v2", " (1)", "!!!"])
    if rng.random() < 0.5:
        base += f" {rng.randint(1, 9999)}"

    if rng.random() < 0.3:
        base = base.replace(" ", rng.choice([" ", "  ", "_", "-", "..."]))

    return f"{base}{extension}"


def safe_unique_path(folder: Path, desired_name: str) -> Path:
    candidate = folder / desired_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        updated = folder / f"{stem}_{counter}{suffix}"
        if not updated.exists():
            return updated
        counter += 1


def write_text_file(path: Path, rng: random.Random) -> None:
    lines = [
        f"Generated at: {datetime.now().isoformat()}",
        f"Noise token: {rng.randint(100000, 999999)}",
        f"Owner: user_{rng.randint(10, 99)}",
        f"Tag: {rng.choice(['invoice', 'report', 'photo', 'clip', 'setup', 'script', 'archive'])}",
        "This file exists only to stress-test automatic organization.",
    ]
    extra_lines = rng.randint(4, 20)
    for _ in range(extra_lines):
        junk = "".join(rng.choices(string.ascii_letters + string.digits + " _-#", k=rng.randint(30, 90)))
        lines.append(junk)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_binary_file(path: Path, rng: random.Random) -> None:
    size = rng.randint(64, 4096)
    path.write_bytes(os.urandom(size))


def set_random_modified_time(path: Path, rng: random.Random) -> None:
    days_back = rng.randint(0, 540)
    seconds_back = rng.randint(0, 86_400)
    modified = datetime.now() - timedelta(days=days_back, seconds=seconds_back)
    timestamp = modified.timestamp()
    os.utime(path, (timestamp, timestamp))


def create_file(path: Path, rng: random.Random) -> None:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        write_text_file(path, rng)
    else:
        write_binary_file(path, rng)
    set_random_modified_time(path, rng)


def create_root_files(target: Path, file_count: int, rng: random.Random) -> list[Path]:
    created_files: list[Path] = []
    all_extensions = TEXT_EXTENSIONS + BINARY_EXTENSIONS

    for index in range(1, file_count + 1):
        extension = rng.choice(all_extensions)
        file_path = safe_unique_path(target, random_name(rng, extension))
        create_file(file_path, rng)
        created_files.append(file_path)
        if index % 10_000 == 0:
            print(f"Created {index} root files...")

    return created_files


def create_duplicates(target: Path, source_files: list[Path], duplicate_count: int, rng: random.Random) -> list[Path]:
    duplicates: list[Path] = []
    if not source_files:
        return duplicates

    picks = [rng.choice(source_files) for _ in range(duplicate_count)]
    for index, original in enumerate(picks, start=1):
        duplicate_name = random_name(rng, original.suffix)
        duplicate_path = safe_unique_path(target, duplicate_name)
        shutil.copy2(original, duplicate_path)
        duplicates.append(duplicate_path)
        if index % 1_000 == 0:
            print(f"Created {index} duplicate files...")

    return duplicates


def create_noise_folders(target: Path, rng: random.Random) -> None:
    # These nested items are useful visual clutter, but the organizer mostly acts on root files.
    folder_names = [
        "old_stuff",
        "sort_me_later",
        "mixed downloads",
        "random_backup_2025",
        "DO_NOT_TOUCH maybe",
    ]
    for folder_name in folder_names:
        folder = target / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        note = safe_unique_path(folder, f"readme_{rng.randint(1, 99)}.txt")
        write_text_file(note, rng)


def build_manifest(target: Path, created_files: list[Path], duplicates: list[Path], manifest_limit: int) -> None:
    sample_files = (created_files + duplicates)[: max(0, manifest_limit)]
    sample_hashes = {}
    for file_path in sample_files:
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        sample_hashes[str(file_path.name)] = digest

    manifest = {
        "generated_at": datetime.now().isoformat(),
        "target": str(target.resolve()),
        "total_root_files": len(created_files) + len(duplicates),
        "original_files": len(created_files),
        "duplicate_files": len(duplicates),
        "examples": sorted(path.name for path in sample_files[:15]),
        "sampled_hash_count": len(sample_files),
        "sample_hashes": sample_hashes,
    }
    (target / "_mess_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def prepare_target(target: Path, keep_existing: bool) -> None:
    if target.exists() and not keep_existing:
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    target = Path(args.target).resolve()

    prepare_target(target, args.keep)
    created_files = create_root_files(target, args.files, rng)
    duplicate_files = create_duplicates(target, created_files, args.duplicates, rng)
    create_noise_folders(target, rng)
    build_manifest(target, created_files, duplicate_files, args.manifest_limit)

    print(f"Messy folder created at: {target}")
    print(f"Root files created: {len(created_files)}")
    print(f"Duplicate files created: {len(duplicate_files)}")
    print("Tip: Select this folder in Smart File Organizer Pro and try Preview, AI Scan, Smart Organize, and Undo.")


if __name__ == "__main__":
    main()
