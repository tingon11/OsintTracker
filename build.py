#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# OSInt Tracker - Copyright (C) 2024-2026 Andrea Cumini <andrea@osintinfo.net>
# SPDX-License-Identifier: GPL-3.0-only
# GNU GPL v3 with additional terms (author attribution): see LICENSE and NOTICE.

"""
BUILD OSINT TRACKER - PyInstaller standalone

Crea un eseguibile standalone che include:
  - launcher.py (pannellino tkinter)
  - app.py (Flask server)
  - osint.html (frontend)
  - manual.html (manuale utente)

Accanto all'eseguibile, in dist/, mette LICENSE, NOTICE e
THIRD-PARTY-NOTICES.txt: vanno distribuiti insieme all'exe.

Il launcher avvia il server come sottoprocesso: con PyInstaller
sys.executable è l'exe stesso, quindi l'entry-point generato esegue Flask
quando viene lanciato con --server e il launcher negli altri casi.

Prerequisiti:
    pip install pyinstaller flask

Uso:
    python build.py
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# =============================================================================
# CONFIG
# =============================================================================

SOURCE_DIR = "."
BUILD_DIR = "osint_build"
APP_NAME = "OSINTTracker"
ICON_FILE = "osint.ico"
HAVE_ICON = os.path.exists(os.path.join(SOURCE_DIR, ICON_FILE))

# True = mostra terminale (debug), False = solo GUI (produzione)
SHOW_CONSOLE = False

# File sorgenti richiesti
REQUIRED_FILES = ["launcher.py", "app.py", "osint.html", "manual.html", "gui-manual.png", "icon.svg", ICON_FILE,
                  "LICENSE", "NOTICE", "DISCLAIMER.txt"]

# Pagine servite da Flask, incluse nell'eseguibile, con la schermata del manuale
# (gui-manual.png: lo screenshot con un riquadro al posto del panorama Street
# View) e l'icona "OT" della scheda del browser (osint.ico e' anche l'icona
# dell'eseguibile: vedi ICON_FILE)
HTML_FILES = ["osint.html", "manual.html", "gui-manual.png", "icon.svg", ICON_FILE]

# Testi di licenza: dentro l'eseguibile (popup "Licenses") e accanto ad esso in dist/.
# THIRD-PARTY-NOTICES.txt viene generato a ogni build
THIRD_PARTY_FILE = "THIRD-PARTY-NOTICES.txt"
LEGAL_FILES = ["LICENSE", "NOTICE", "DISCLAIMER.txt", THIRD_PARTY_FILE]

# Pacchetti Python che finiscono nell'eseguibile (per le note di licenza)
BUNDLED_PACKAGES = ["flask", "werkzeug", "jinja2", "markupsafe", "itsdangerous",
                    "click", "blinker", "colorama"]

# Entry-point generato (combina launcher + flask in un unico processo)
ENTRY_POINT = "osint_main.py"

# Questo script
BUILD_SCRIPT_NAME = "build_osint.py"

# =============================================================================
# UTIL
# =============================================================================


def print_header(text: str):
    print("\n" + "=" * 70)
    print(f" {text}")
    print("=" * 70)


def run(cmd, cwd=None, check=True):
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check)


def ensure_clean_dir(d: Path):
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)


# =============================================================================
# VERIFICA DIPENDENZE
# =============================================================================


def check_dependencies() -> bool:
    print_header("VERIFICA DIPENDENZE")
    deps = {
        "PyInstaller":    "pyinstaller",
        "flask":          "flask",
    }
    all_ok = True
    for module, package in deps.items():
        try:
            __import__(module)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package} - MANCANTE  →  pip install {package}")
            all_ok = False
    return all_ok


# =============================================================================
# VERIFICA FILE SORGENTI
# =============================================================================


def check_source_files() -> bool:
    print_header("VERIFICA FILE SORGENTI")
    src = Path(SOURCE_DIR).resolve()
    all_ok = True
    for f in REQUIRED_FILES:
        p = src / f
        if p.exists():
            print(f"  ✅ {f}  ({p.stat().st_size:,} bytes)")
        else:
            print(f"  ❌ {f} - NON TROVATO in {src}")
            all_ok = False
    return all_ok


# =============================================================================
# COPIA SORGENTI
# =============================================================================


def copy_sources():
    print_header("COPIA SORGENTI → BUILD DIR")

    src = Path(SOURCE_DIR).resolve()
    dst = Path(BUILD_DIR).resolve()
    ensure_clean_dir(dst)

    this_name = Path(__file__).name

    # Copia tutti i .py tranne build script
    for p in src.glob("*.py"):
        if p.name == this_name:
            continue
        shutil.copy2(p, dst / p.name)
        print(f"  📄 {p.name}")

    # Copia le pagine HTML
    for name in HTML_FILES:
        shutil.copy2(src / name, dst / name)
        print(f"  📄 {name}")

    # Testi di licenza
    for name in LEGAL_FILES:
        if name != THIRD_PARTY_FILE:
            shutil.copy2(src / name, dst / name)
            print(f"  📄 {name}")
    write_third_party_notices(dst / THIRD_PARTY_FILE)

    # Copia icona se presente
    if HAVE_ICON:
        shutil.copy2(src / ICON_FILE, dst / ICON_FILE)
        print(f"  🎨 {ICON_FILE}")


# =============================================================================
# GENERAZIONE ENTRY-POINT COMBINATO
# =============================================================================


def generate_entry_point():
    """
    Genera un entry-point con due ruoli nello stesso exe:
      - senza argomenti: mostra il launcher (launcher.py)
      - con --server:    esegue Flask (app.py); è il comando che il launcher
                         lancia come sottoprocesso quando è "frozen"
    """
    print_header("GENERAZIONE ENTRY-POINT COMBINATO")

    code = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Auto-generated entry point for frozen build

import os
import sys

# ── Fix paths per PyInstaller --onefile ──
if getattr(sys, 'frozen', False):
    # _MEIPASS = temp dir con i file bundled (osint.html, app.py, ecc.)
    BUNDLE_DIR = sys._MEIPASS
    # EXE_DIR = cartella dove si trova l'exe (qui vanno db e key)
    EXE_DIR = os.path.dirname(sys.executable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = BUNDLE_DIR

os.chdir(EXE_DIR)
os.environ['APP_DIR'] = EXE_DIR
os.environ['BUNDLE_DIR'] = BUNDLE_DIR

# Aggiungi BUNDLE_DIR al path per trovare app.py e launcher.py
if BUNDLE_DIR not in sys.path:
    sys.path.insert(0, BUNDLE_DIR)


def run_server():
    """Flask in questo processo (bloccante)"""
    import threading
    import app as flask_app

    # osint.html è nel bundle
    flask_app.app.root_path = BUNDLE_DIR
    flask_app.app.static_folder = os.path.join(BUNDLE_DIR, 'static')

    # DB e file config nella directory dell exe (persistenti)
    flask_app.DB_NAME = os.path.join(EXE_DIR, 'osint.db')
    flask_app.KEY_FILE = os.path.join(EXE_DIR, 'key.txt')

    flask_app.init_db()
    threading.Thread(target=flask_app.db_worker, daemon=True).start()

    port = int(os.environ.get('PORT', 5000))
    flask_app.app.run(host=flask_app.HOST, port=port, debug=False, use_reloader=False)


def main():
    if '--server' in sys.argv:
        run_server()
    else:
        import launcher
        launcher.main()


if __name__ == "__main__":
    main()
'''

    entry_path = Path(BUILD_DIR) / ENTRY_POINT
    entry_path.write_text(code, encoding="utf-8")
    print(f"  ✅ Entry-point generato: {entry_path}")


# =============================================================================
# CREAZIONE SPEC PYINSTALLER
# =============================================================================


def create_spec():
    print_header("CREAZIONE FILE .spec")

    bdir = Path(BUILD_DIR)

    # Hidden imports necessari
    hidden = [
        # Flask + dipendenze
        'flask', 'flask.json', 'flask.templating',
        'jinja2', 'jinja2.ext', 'markupsafe',
        'werkzeug', 'werkzeug.serving', 'werkzeug.debug',
        'itsdangerous', 'click', 'blinker',

        # Tkinter
        'tkinter',

        # Standard library usati da app.py / launcher.py
        'sqlite3', 'logging', 'queue', 'threading',
        'json', 'datetime', 'socket', 'webbrowser', 'ctypes',

        # App modules
        'app', 'launcher',
    ]

    # Dati da includere accanto all'exe
    datas = [(name, ".") for name in HTML_FILES + LEGAL_FILES] + [
        ("app.py", "."),          # app.py come modulo importabile
        ("launcher.py", "."),     # GUI riusata dall'entry-point
    ]

    # File config opzionali - NON includere, creati dall'utente
    icon_line = ""
    if HAVE_ICON and (bdir / ICON_FILE).exists():
        icon_line = f"    icon='{ICON_FILE}',"

    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

a = Analysis(
    ['{ENTRY_POINT}'],
    pathex=[],
    binaries=[],
    datas={datas},
    hiddenimports={hidden},
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'PIL', 'cv2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{APP_NAME}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console={SHOW_CONSOLE},
    onefile=True,
{icon_line}
)
"""

    spec_path = bdir / f"{APP_NAME.lower()}.spec"
    spec_path.write_text(spec_content, encoding="utf-8")
    print(f"  ✅ Spec scritto: {spec_path}")


# =============================================================================
# BUILD PYINSTALLER
# =============================================================================


def build_pyinstaller():
    print_header("COMPILAZIONE CON PYINSTALLER")
    cmd = [sys.executable, "-m", "PyInstaller",
           "--clean", f"{APP_NAME.lower()}.spec"]
    run(cmd, cwd=BUILD_DIR)


# =============================================================================
# NOTE DI LICENZA DEI COMPONENTI INCLUSI
# =============================================================================


def write_third_party_notices(path: Path):
    """L'eseguibile contiene l'interprete Python e alcune librerie: le loro
    licenze (PSF, BSD, MIT) chiedono di riportarne il testo in ogni
    distribuzione binaria. Lo raccoglie dall'ambiente con cui si compila."""
    from importlib import metadata

    rule = "=" * 78
    parts = [
        "THIRD-PARTY SOFTWARE NOTICES",
        "",
        "This executable was built with PyInstaller and contains the software",
        "listed below, each under its own license. These licenses apply to those",
        "components only; the program itself is licensed under the GNU GPL v3 with",
        "additional terms (see LICENSE and NOTICE).",
        "",
        "The PyInstaller bootloader is distributed under the GPL with a special",
        "exception that allows it to be shipped with programs under any license.",
    ]

    def section(title, text):
        parts.extend(["", rule, title, rule, "", text.strip()])

    # Interprete Python: il suo LICENSE.txt copre anche i componenti inclusi nella
    # distribuzione Windows (Tcl/Tk, SQLite, OpenSSL, zlib, bzip2, libffi, ...)
    py_license = Path(sys.base_prefix) / "LICENSE.txt"
    if py_license.exists():
        section(f"Python {sys.version.split()[0]} and the libraries bundled with it",
                py_license.read_text(encoding="utf-8", errors="replace"))
    else:
        print(f"  ⚠️ Licenza di Python non trovata: {py_license}")

    for name in BUNDLED_PACKAGES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        texts = [f.locate().read_text(encoding="utf-8", errors="replace")
                 for f in (dist.files or [])
                 if ".dist-info" in str(f) and f.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))]
        if not texts:
            texts = [f"License: {dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'see the project page'}"]
            print(f"  ⚠️ Testo della licenza non trovato per {name}")
        section(f"{dist.metadata['Name']} {dist.version}", "\n\n".join(texts))

    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"  ✅ Note di licenza: {path.name}")


# =============================================================================
# POST-BUILD: copia file runtime nella dist
# =============================================================================


def post_build():
    print_header("POST-BUILD")

    dist_dir = Path(BUILD_DIR) / "dist"
    if not dist_dir.exists():
        print(f"  ⚠️ Directory dist non trovata: {dist_dir}")
        return

    exe_name = f"{APP_NAME}.exe" if sys.platform == 'win32' else APP_NAME
    exe_path = dist_dir / exe_name

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"  ✅ Eseguibile: {exe_path} ({size_mb:.1f} MB)")
    else:
        print(f"  ⚠️ Eseguibile non trovato: {exe_path}")
        return

    # La GPL chiede che licenza e note accompagnino l'eseguibile
    for name in LEGAL_FILES:
        shutil.copy2(Path(BUILD_DIR) / name, dist_dir / name)

    print(f"\n  📁 Contenuto dist/:")
    for item in sorted(dist_dir.iterdir()):
        size = item.stat().st_size if item.is_file() else 0
        icon = "📁" if item.is_dir() else "📄"
        print(f"      {icon} {item.name}" + (f"  ({size:,} bytes)" if size else ""))


# =============================================================================
# MAIN
# =============================================================================


def main():
    print_header(f"BUILD {APP_NAME}")
    print(f"  Python:    {sys.version}")
    print(f"  Platform:  {sys.platform}")
    print(f"  Source:    {Path(SOURCE_DIR).resolve()}")
    print(f"  Build:     {Path(BUILD_DIR).resolve()}")
    print(f"  Console:   {'ON (debug)' if SHOW_CONSOLE else 'OFF (produzione)'}")

    if not check_dependencies():
        print("\n❌ Installa le dipendenze mancanti e riprova.")
        sys.exit(1)

    if not check_source_files():
        print("\n❌ File sorgenti mancanti. Assicurati di eseguire lo script")
        print("   nella stessa directory di launcher.py, app.py e osint.html.")
        sys.exit(1)

    copy_sources()
    generate_entry_point()
    create_spec()
    build_pyinstaller()
    post_build()

    print_header("✅ BUILD COMPLETATA")
    exe_name = f"{APP_NAME}.exe" if sys.platform == 'win32' else APP_NAME
    print(f"""
  Eseguibile: ./{BUILD_DIR}/dist/{exe_name}

  Per eseguire:
      ./{BUILD_DIR}/dist/{exe_name}

  Da distribuire insieme (tutti in ./{BUILD_DIR}/dist/):
      {exe_name}, LICENSE, NOTICE, DISCLAIMER.txt, THIRD-PARTY-NOTICES.txt
  La GPL richiede inoltre di rendere disponibile il sorgente di questa versione.

  Note:
    - osint.html e manual.html sono inclusi nell'exe
    - Il DB (osint.db) viene creato al primo avvio accanto all'exe
    - key.txt viene creato dall'app
    - Il launcher resta in primo piano in basso a destra; Flask parte da solo
      (è l'exe stesso lanciato con --server), 🌐 apre il browser, ✕ ferma tutto
    - L'output del server finisce in launcher.log accanto all'exe
""")


if __name__ == "__main__":
    main()