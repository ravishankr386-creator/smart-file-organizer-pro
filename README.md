# Smart File Organizer Pro

![Version](https://img.shields.io/badge/version-1.0.1-2cc6b8)
![Platform](https://img.shields.io/badge/platform-Windows-6db5ff)
![Python](https://img.shields.io/badge/python-3.x-13243a)
![UI](https://img.shields.io/badge/UI-Tkinter-102133)

Clean up messy folders, isolate duplicates, preview changes, and undo the last run with a polished Windows desktop app built for real everyday clutter.

![Smart File Organizer Pro](assets/smart_file_organizer_pro.png)

## Why This Project Stands Out

- Built for real mixed folders, not just one file type
- Safer workflow with preview before action
- Duplicate isolation instead of silent deletion
- Undo support for the last run
- Smart mode for practical default organization
- Desktop-friendly UI for non-technical users
- Portable `.exe` packaging for easy sharing

## Perfect For

- Downloads folders
- Desktop cleanup
- Student assignments and project files
- Office and freelance document folders
- Screenshots, exports, and creator assets
- Mixed work and personal file collections

## Core Features

- Smart classification using file type, keyword, and timeline signals
- Organize modes: `Smart`, `Type`, `Date`, and `Size`
- Duplicate detection with staged SHA-256 hashing
- Preview panel for planned actions before execution
- Duplicate review panel showing the kept file
- File name cleanup option for noisy filenames
- Auto-watch mode for organizing newly added files
- Undo log to reverse the last run
- Optional AI-style recommendations with local analysis and ChatGPT-ready flow

## Supported Categories

- Images
- Videos
- Documents
- Audio
- Archives
- Executables
- Code
- Design files
- Others

## How It Works

1. Select a folder.
2. Pick or accept the recommended strategy.
3. Preview all planned moves.
4. Run the organizer.
5. Undo the last run if needed.

## Safety First

- Protected system folders are blocked
- Preview is available before moving files
- Duplicate files are moved into `_duplicates`
- Undo information is stored for the last run

## Download

Portable build outputs:

- `dist/Smart_File_Organizer_Pro.exe`
- `release/Smart_File_Organizer_Pro_Portable/Smart_File_Organizer_Pro.exe`
- `release/Smart_File_Organizer_Pro_Portable_v1.0.1.zip`

## Build Locally

```powershell
python -m py_compile Smart_file_Organizer_Pro.py
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

## Project Structure

```text
Smart_file_Organizer_Pro.py
Smart_File_Organizer_Pro.spec
build_release.ps1
installer.iss
assets/
```

## Tech Stack

- Python
- Tkinter / ttk
- PyInstaller
- Windows packaging

## Search Keywords

file organizer, duplicate finder, folder cleaner, downloads organizer, desktop cleanup app, Windows productivity app, Python desktop app, smart file sorting tool, duplicate file cleanup, clutter management

## Contributing

Bug reports, feature requests, UI improvements, packaging upgrades, and workflow polish are all welcome.

## Author

Built by Ravis Automation Lab.
