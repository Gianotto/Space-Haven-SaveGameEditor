# -*- mode: python ; coding: utf-8 -*-
"""Empacotamento com PyInstaller: um executável só, por sistema.

    pyinstaller --clean --noconfirm SpaceHavenEditor.spec

Os caminhos em `datas` são relativos ao .spec, então o mesmo arquivo serve para
Windows e Linux — usar `--add-data` na linha de comando exigiria trocar o
separador (`;` no Windows, `:` no resto).

O console fica visível de propósito: é onde aparece o endereço do editor e é
por ali que se encerra o servidor (Ctrl+C).
"""

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("shedit/data", "shedit/data"),   # gamedata.json e i18n.json
        ("shedit/web", "shedit/web"),     # interface
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # O editor só usa a biblioteca padrão; fora o que o PyInstaller puxa
    # sozinho, nada de tkinter/testes inflando o binário.
    excludes=["tkinter", "unittest", "pydoc", "doctest", "test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SpaceHavenEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
