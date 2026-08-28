import os
import sys
import time
import threading
import webbrowser

from config import BASE_DIR

os.chdir(BASE_DIR)

# Redirect stdout/stderr to a log file (needed when running with pythonw.exe)
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'server.log')

if sys.stdout is None:
    try:
        sys.stdout = open(LOG_FILE, 'a', encoding='utf-8')
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = sys.stdout
    except Exception:
        pass


def log(msg):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass


def write_pid():
    try:
        with open(os.path.join(BASE_DIR, 'server.pid'), 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        log(f"PID write error: {e}")


def cleanup_pid():
    try:
        pid_file = os.path.join(BASE_DIR, 'server.pid')
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception:
        pass


def open_browser_after_start(url, delay=2.5):
    time.sleep(delay)
    try:
        webbrowser.open(url)
        log(f"Opened browser: {url}")
    except Exception as e:
        log(f"Could not open browser: {e}")


BROWSER_OPENED = threading.Event()


def ensure_server_running(app, host, port):
    """Wait until Flask is actually listening, then open the browser."""
    import socket
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            break
        except OSError:
            time.sleep(0.5)


def main():
    from config import Config
    demo = bool(getattr(Config, 'DEMO_MODE', False))
    port = int(os.environ.get('PORT', '8080'))
    host = os.environ.get('HOST', '0.0.0.0')
    log("Starting HR System...")
    write_pid()

    try:
        from app import app
        from models import db
        from init_db import seed_default_data, add_sample_employee, seed_demo_data

        with app.app_context():
            db.create_all()
            seed_default_data()
            add_sample_employee()
            seed_demo_data()
        log("Database ready.")

        # Auto-open browser (local desktop only)
        if not demo:
            url = f"http://127.0.0.1:{port}"
            threading.Thread(target=open_browser_after_start, args=(url,), daemon=True).start()

        # Start background tasks (auto backup + auto absence / demo reset)
        from modules import scheduler
        scheduler.start_scheduler()
        log("Scheduler started.")

        log(f"Serving on http://{host}:{port}")
        import atexit
        atexit.register(cleanup_pid)
        app.run(host=host, port=port, debug=False, use_reloader=False)
    except Exception as e:
        log(f"FATAL: {e}")
        import traceback
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                traceback.print_exc(file=f)
        except Exception:
            pass


if __name__ == '__main__':
    main()