# OSInt Tracker - Copyright (C) 2024-2026 Andrea Cumini <andrea@osintinfo.net>
# SPDX-License-Identifier: GPL-3.0-only
# GNU GPL v3 with additional terms (author attribution): see LICENSE and NOTICE.
import os
import sys
import sqlite3
import logging
import queue
import threading
from datetime import datetime
from urllib.parse import urlsplit
from flask import Flask, request, jsonify, send_file, abort

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# In ascolto solo su questo computer: l'API espone la chiave Google e le
# registrazioni senza autenticazione. HOST=0.0.0.0 la apre alla rete locale.
HOST = os.environ.get('HOST', '127.0.0.1')

DB_NAME = 'osint.db'
KEY_FILE = 'key.txt'

# Versione dell'API: la pagina la confronta per accorgersi di un server non riavviato
API_VERSION = 3

# Avviso legale (DISCLAIMER.txt): va accettato a ogni avvio del programma, prima
# che l'API risponda. Se viene rifiutato il server termina con questo codice
# d'uscita, che il launcher riconosce per chiudersi a sua volta.
DISCLAIMER_FILE = 'DISCLAIMER.txt'
TERMS_DECLINED_EXIT = 3
terms_accepted = False

# Queue per serializzare operazioni DB
db_queue = queue.Queue()

LOOPBACK = ('127.0.0.1', 'localhost', '::1')


@app.before_request
def same_origin_only():
    """Accetta solo le richieste che arrivano dalla pagina dell'app.

    Niente CORS: nessun altro sito deve poter leggere la chiave Google o le
    registrazioni, ne' modificarle, anche se e' aperto nello stesso browser.
    """
    # Host diverso da loopback mentre ascoltiamo solo in locale: DNS rebinding
    # (un sito che fa puntare il proprio dominio a 127.0.0.1)
    if HOST in LOOPBACK and urlsplit('//' + request.host).hostname not in LOOPBACK:
        abort(403)

    if request.path.startswith('/api/'):
        # Chiamata partita da un'altra origine (altro sito, o altra porta locale)
        if request.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
            abort(403)
        origin = request.headers.get('Origin')
        if origin and urlsplit(origin).netloc != request.host:
            abort(403)

        # Finche' l'avviso legale non e' stato accettato l'API non risponde
        if not terms_accepted and request.path not in ('/api/disclaimer', '/api/health'):
            return jsonify({'success': False, 'error': 'Terms of use not accepted'}), 403


def set_aside_old_db():
    """Un database delle versioni precedenti (step salvati con le coordinate)
    non e' compatibile: viene rinominato in osint.db.old e si riparte da uno vuoto"""
    if not os.path.exists(DB_NAME):
        return
    conn = sqlite3.connect(DB_NAME, timeout=30)
    cols = {row[1] for row in conn.execute('PRAGMA table_info(points)')}
    conn.close()
    if not cols or 'pano' in cols:
        return

    old = DB_NAME + '.old'
    n = 1
    while os.path.exists(old):
        n += 1
        old = f'{DB_NAME}.old{n}'
    logger.warning(f"Database di una versione precedente: messo da parte come {old}")
    os.replace(DB_NAME, old)
    for ext in ('-wal', '-shm'):
        if os.path.exists(DB_NAME + ext):
            os.remove(DB_NAME + ext)


def init_db():
    """Inizializza database con tabelle e indici"""
    try:
        logger.info("Inizializzazione database...")
        set_aside_old_db()
        conn = sqlite3.connect(DB_NAME, timeout=30)
        conn.execute('PRAGMA journal_mode=WAL')
        cursor = conn.cursor()

        logger.info("Creazione tabella sessions...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Di ogni step si conserva l'ID del panorama Google (pano), che i termini
        # di Google Maps permettono di tenere, piu' inquadratura e nota. Le
        # coordinate NON vengono salvate: la pagina le chiede a Google quando
        # apre una sessione e le tiene solo in memoria.
        logger.info("Creazione tabella points...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                pano TEXT NOT NULL,
                note TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                heading REAL,
                pitch REAL,
                zoom REAL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        ''')

        logger.info("Creazione indici...")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_session_id ON points(session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON points(timestamp)')

        conn.commit()
        conn.close()
        logger.info("✓ Database inizializzato con successo")
    except Exception as e:
        logger.error(f"❌ Errore inizializzazione database: {e}", exc_info=True)
        raise


def db_worker():
    """Worker thread per operazioni DB serializzate"""
    while True:
        try:
            task = db_queue.get()
            if task is None:
                break

            func, args, result_queue = task
            try:
                result = func(*args)
                result_queue.put(('success', result))
            except Exception as e:
                logger.error(f"Errore DB worker: {e}")
                result_queue.put(('error', str(e)))
        except Exception as e:
            logger.error(f"Errore critico DB worker: {e}")


def execute_db_operation(func, *args):
    """Esegue operazione DB tramite worker thread"""
    result_queue = queue.Queue()
    db_queue.put((func, args, result_queue))
    status, result = result_queue.get(timeout=30)
    if status == 'error':
        raise Exception(result)
    return result


# API Endpoints

@app.route('/')
def index():
    """Serve frontend HTML"""
    return send_file('osint.html')


@app.route('/manual')
def manual():
    """Manuale utente (EN/IT)"""
    return send_file('manual.html')


def send_asset(name, mimetype):
    """File accanto a osint.html (nell'eseguibile: dentro il bundle)"""
    path = os.path.join(app.root_path, name)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype=mimetype)


@app.route('/icon.svg')
def icon_svg():
    """Icona "OT" della scheda del browser"""
    return send_asset('icon.svg', 'image/svg+xml')


@app.route('/gui-manual.png')
def gui_png():
    """Schermata dell'interfaccia mostrata nel manuale (al posto del panorama Street
    View c'e' un riquadro: Google non permette di pubblicarne screenshot)"""
    return send_asset('gui-manual.png', 'image/png')


@app.route('/favicon.ico')
def favicon():
    """Stessa icona per i browser che chiedono il file classico"""
    return send_asset('osint.ico', 'image/x-icon')


# Testi di licenza mostrati nel popup "Licenses" del pannello
LEGAL_DOCS = {
    'disclaimer': DISCLAIMER_FILE,
    'notice': 'NOTICE',
    'license': 'LICENSE',
    'third-party': 'THIRD-PARTY-NOTICES.txt',   # generato da build.py: c'e' solo nell'eseguibile
}


@app.route('/legal/<doc>')
def legal(doc):
    """Testo di una licenza"""
    name = LEGAL_DOCS.get(doc)
    path = os.path.join(app.root_path, name) if name else None
    if not path or not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype='text/plain')


def read_disclaimer():
    """Testo dell'avviso legale; se il file manca resta comunque un avviso minimo"""
    try:
        with open(os.path.join(app.root_path, DISCLAIMER_FILE), encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ('This program is provided "AS IS", without warranty of any kind. To the maximum extent '
                'permitted by applicable law the author is not liable for any damage or consequence '
                'arising from its use. You alone are responsible for how you use it.')


@app.route('/api/disclaimer', methods=['GET'])
def get_disclaimer():
    """Avviso legale da mostrare all'apertura, e se e' gia' stato accettato in questo avvio"""
    return jsonify({'accepted': terms_accepted, 'text': read_disclaimer()})


@app.route('/api/disclaimer', methods=['POST'])
def answer_disclaimer():
    """Risposta all'avviso legale: accettato → il programma si apre; rifiutato → si chiude"""
    global terms_accepted
    if (request.json or {}).get('accept') is True:
        terms_accepted = True
        logger.info("Avviso legale accettato")
        return jsonify({'success': True, 'accepted': True})

    logger.info("Avviso legale rifiutato: chiusura del programma")
    # Il tempo di consegnare la risposta alla pagina, poi il server termina
    threading.Timer(0.7, lambda: os._exit(TERMS_DECLINED_EXIT)).start()
    return jsonify({'success': True, 'accepted': False})


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint per verificare che il server funzioni"""
    try:
        # Test database
        conn = sqlite3.connect(DB_NAME, timeout=5)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM sessions')
        session_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM points')
        point_count = cursor.fetchone()[0]
        conn.close()

        return jsonify({
            'status': 'OK',
            'api': API_VERSION,
            'database': 'connected',
            'sessions': session_count,
            'points': point_count
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return jsonify({
            'status': 'ERROR',
            'error': str(e)
        }), 500


@app.route('/api/key', methods=['GET'])
def get_api_key():
    """Recupera API key salvata"""
    try:
        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, 'r') as f:
                key = f.read().strip()
                return jsonify({'key': key})
        return jsonify({'key': ''})
    except Exception as e:
        logger.error(f"Errore in /api/key GET: {e}", exc_info=True)
        return jsonify({'key': '', 'error': str(e)}), 500


@app.route('/api/key', methods=['POST'])
def save_api_key():
    """Salva API key"""
    try:
        data = request.json
        key = data.get('key', '').strip()

        with open(KEY_FILE, 'w') as f:
            f.write(key)

        logger.info("API key salvata")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore in /api/key POST: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session', methods=['POST'])
def create_session():
    """Crea nuova sessione"""
    data = request.json
    name = data.get('name', 'Sessione senza nome')

    def _create():
        conn = sqlite3.connect(DB_NAME, timeout=30)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO sessions (name) VALUES (?)', (name,))
        session_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return session_id

    try:
        session_id = execute_db_operation(_create)
        logger.info(f"Sessione creata: {session_id} - {name}")
        return jsonify({'success': True, 'id': session_id})
    except Exception as e:
        logger.error(f"Errore creazione sessione: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    """Lista tutte le sessioni con statistiche"""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT 
            s.id,
            s.name,
            s.created_at,
            COUNT(p.id) as point_count
        FROM sessions s
        LEFT JOIN points p ON s.id = p.session_id
        GROUP BY s.id
        ORDER BY s.created_at DESC
    ''')

    sessions = []
    for row in cursor.fetchall():
        sessions.append({
            'id': row['id'],
            'name': row['name'],
            'created_at': row['created_at'],
            'point_count': row['point_count']
        })

    conn.close()
    return jsonify(sessions)


@app.route('/api/session/<int:session_id>', methods=['DELETE'])
def delete_session(session_id):
    """Elimina sessione e tutti i suoi punti"""

    def _delete():
        conn = sqlite3.connect(DB_NAME, timeout=30)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM points WHERE session_id = ?', (session_id,))
        cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
        conn.commit()
        conn.close()

    try:
        execute_db_operation(_delete)
        logger.info(f"Sessione eliminata: {session_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Errore eliminazione sessione: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<int:session_id>/points', methods=['GET'])
def get_points(session_id):
    """Recupera tutti i punti di una sessione"""
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # timestamp ha risoluzione di 1 secondo: più step nello stesso secondo
    # (es. rotazioni) mantengono l'ordine di inserimento grazie all'id
    cursor.execute('''
        SELECT id, pano, note, timestamp, heading, pitch, zoom
        FROM points
        WHERE session_id = ?
        ORDER BY timestamp ASC, id ASC
    ''', (session_id,))

    points = []
    for row in cursor.fetchall():
        points.append({
            'id': row['id'],
            'pano': row['pano'],
            'note': row['note'],
            'timestamp': row['timestamp'],
            'heading': row['heading'],
            'pitch': row['pitch'],
            'zoom': row['zoom']
        })

    conn.close()
    return jsonify(points)


@app.route('/api/point', methods=['POST'])
def add_point():
    """Aggiunge un nuovo step: panorama Google (ID) + inquadratura"""
    data = request.json
    session_id = data.get('session_id')
    pano = str(data.get('pano') or '').strip()
    note = data.get('note', '')

    if not session_id or not pano:
        # Una pagina rimasta aperta dalla versione precedente manda ancora le coordinate
        return jsonify({'success': False, 'error': 'Missing panorama ID: reload the page (F5)'}), 400

    # Inquadratura Street View (opzionale): heading/pitch in gradi, zoom
    pov = {}
    for key in ('heading', 'pitch', 'zoom'):
        try:
            pov[key] = float(data[key]) if data.get(key) is not None else None
        except (TypeError, ValueError):
            pov[key] = None

    def _insert():
        conn = sqlite3.connect(DB_NAME, timeout=30)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO points (session_id, pano, note, heading, pitch, zoom)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session_id, pano, note, pov['heading'], pov['pitch'], pov['zoom']))
        point_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return point_id

    try:
        point_id = execute_db_operation(_insert)
        logger.info(f"Punto aggiunto: {point_id} - Session: {session_id}")
        return jsonify({'success': True, 'id': point_id})
    except Exception as e:
        logger.error(f"Errore inserimento punto: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<int:session_id>/last-point/note', methods=['PUT'])
def update_last_point_note(session_id):
    """Aggiorna nota dell'ultimo punto di una sessione"""
    data = request.json
    note = data.get('note', '')

    def _update():
        conn = sqlite3.connect(DB_NAME, timeout=30)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id FROM points
            WHERE session_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
        ''', (session_id,))

        result = cursor.fetchone()
        if not result:
            conn.close()
            return None

        point_id = result[0]
        cursor.execute('UPDATE points SET note = ? WHERE id = ?', (note, point_id))
        conn.commit()
        conn.close()
        return point_id

    try:
        point_id = execute_db_operation(_update)
        if point_id:
            logger.info(f"Nota aggiornata punto: {point_id} - Session: {session_id}")
            return jsonify({'success': True, 'id': point_id})
        else:
            return jsonify({'success': False, 'error': 'No points in session'}), 404
    except Exception as e:
        logger.error(f"Errore aggiornamento nota: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/point/<int:point_id>/note', methods=['PUT'])
def update_point_note(point_id):
    """Aggiorna nota di un punto specifico per ID"""
    data = request.json or {}
    note = data.get('note', '')

    def _update():
        conn = sqlite3.connect(DB_NAME, timeout=30)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM points WHERE id = ?', (point_id,))
        if not cursor.fetchone():
            conn.close()
            return None
        cursor.execute('UPDATE points SET note = ? WHERE id = ?', (note, point_id))
        conn.commit()
        conn.close()
        return point_id

    try:
        result = execute_db_operation(_update)
        if result:
            logger.info(f"Nota aggiornata punto: {point_id}")
            return jsonify({'success': True, 'id': point_id})
        else:
            return jsonify({'success': False, 'error': 'Point not found'}), 404
    except Exception as e:
        logger.error(f"Errore aggiornamento nota punto {point_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/point/<int:point_id>', methods=['DELETE'])
def delete_point(point_id):
    """Elimina un punto specifico"""

    def _delete():
        conn = sqlite3.connect(DB_NAME, timeout=30)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM points WHERE id = ?', (point_id,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted

    try:
        deleted = execute_db_operation(_delete)
        if deleted:
            logger.info(f"Punto eliminato: {point_id}")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Point not found'}), 404
    except Exception as e:
        logger.error(f"Errore eliminazione punto {point_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("AVVIO OSINT TRACKER")
    logger.info("=" * 60)

    try:
        logger.info("Step 1: Inizializzazione database...")
        init_db()

        logger.info("Step 2: Avvio worker thread DB...")
        worker_thread = threading.Thread(target=db_worker, daemon=True)
        worker_thread.start()
        logger.info("✓ Worker thread avviato")

        port = int(os.environ.get('PORT', 5000))   # il launcher la passa via ambiente
        logger.info("=" * 60)
        logger.info(f"✓ Server Flask pronto su http://localhost:{port}")
        logger.info("=" * 60)

        app.run(host=HOST, port=port, debug=False)

    except Exception as e:
        logger.error("=" * 60)
        logger.error("❌ ERRORE CRITICO DURANTE L'AVVIO")
        logger.error("=" * 60)
        logger.error(str(e), exc_info=True)
        sys.exit(1)