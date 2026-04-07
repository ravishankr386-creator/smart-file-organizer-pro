# Smart File Organizer Pro

AI-powered Windows desktop app for organizing messy folders, sorting files by smart rules, detecting duplicates, previewing changes, and undoing the last run safely.

![Smart File Organizer Pro](assets/smart_file_organizer_pro.png)

## Why People Will Like It

- Organizes cluttered folders in a few clicks
- Detects duplicates with staged SHA-256 hashing
- Shows a preview before moving anything
- Supports undo for the last run
- Includes a polished desktop UI
- Can watch a folder and auto-organize new files
- Works well for mixed folders with documents, images, videos, code, archives, and more

## Best For

- Downloads folders
- Desktop cleanup
- Student project folders
- Office documents
- Creator assets
- Bulk screenshots and exports
- Mixed personal and work files

## Features

- Smart classification using type signals, keywords, and date-aware grouping
- Multiple organize modes: `Smart`, `Type`, `Date`, and `Size`
- Duplicate isolation into `_duplicates`
- File name cleanup option for noisy names
- AI-style insights panel with local analysis and optional ChatGPT recommendations
- Preview table for planned moves before execution
- Duplicate review panel that shows which file is kept
- Auto mode that watches for new files and organizes them automatically
- Desktop executable packaging for easy sharing

## Supported File Categories

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
2. Review the recommended strategy.
3. Preview the planned changes.
4. Start organizing.
5. Undo the last run if needed.

## Download And Run

If you just want the app:

1. Open the `release` or `dist` output from this project.
2. Run `Smart_File_Organizer_Pro.exe`.

If you want to build it yourself:

```powershell
python -m py_compile Smart_file_Organizer_Pro.py
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

Build output:

- `dist/Smart_File_Organizer_Pro.exe`
- `release/Smart_File_Organizer_Pro_Portable/Smart_File_Organizer_Pro.exe`
- `release/Smart_File_Organizer_Pro_Portable_v1.0.1.zip`

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
- Windows desktop packaging

## Safety Notes

- Protected system folders are blocked
- Preview is available before execution
- Duplicate handling keeps one file and moves extras to `_duplicates`
- Undo log is stored so the last run can be reversed

## Version

Current version: `1.0.1`

## Keywords

file organizer, duplicate file finder, desktop cleaner, folder organizer, download folder organizer, Windows file management, Python desktop app, AI file organizer, file sorting app, clutter cleanup tool

## Contributing

Ideas, bug reports, UI improvements, packaging help, and feature requests are welcome.

## Author

Built by Ravis Automation Lab.
