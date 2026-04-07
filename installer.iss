#define MyAppName "Smart File Organizer Pro"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Ravis Automation Lab"
#define MyAppExeName "Smart_File_Organizer_Pro.exe"

[Setup]
AppId={{4C9A65F7-0C6B-4E1D-B5D8-C71E2BEE9D2D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=release
OutputBaseFilename=Smart_File_Organizer_Pro_Setup_v1.0.1
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\smart_file_organizer_pro.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\Smart_File_Organizer_Pro.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "RELEASE_NOTES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
