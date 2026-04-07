# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['c:\\Users\\ravis\\automation_practice\\Smart_file_Organizer_Pro.py'],
    pathex=[],
    binaries=[],
    datas=[('c:\\Users\\ravis\\automation_practice\\assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Smart_File_Organizer_Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['c:\\Users\\ravis\\automation_practice\\assets\\smart_file_organizer_pro.ico'],
    version='c:\\Users\\ravis\\automation_practice\\build\\version_info.txt',
)
