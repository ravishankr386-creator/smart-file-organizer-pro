# Smart File Organizer Pro

Version: 1.0.1

## Highlights

- Smart organization by type, date, size, and smart mode
- Duplicate detection with staged SHA-256 hashing
- Persistent undo log
- Background processing to keep the UI responsive
- Modern app icon and packaged Windows executable

## Portable Build

- Run `Smart_File_Organizer_Pro.exe`
- The app creates `app.log` and `undo_log.json` in the same folder as the executable

## Installer Build

- If Inno Setup is installed, compile `installer.iss`
- The installer creates Start Menu and optional desktop shortcuts
