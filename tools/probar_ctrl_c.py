"""Prueba real del cierre limpio: arranca bootstrap, envía Ctrl+Break (Windows) o SIGINT y
comprueba que Streamlit se cerró (puerto libre) y que un Ollama previo sigue arriba.

Uso:  python tools/probar_ctrl_c.py [carpeta_del_proyecto]
"""

import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
PORT = 8511


def up(url):
    try:
        return urllib.request.urlopen(url, timeout=2).status == 200
    except Exception:
        return False


def listening(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


ollama_before = up("http://127.0.0.1:11434/api/version")
flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
proc = subprocess.Popen([sys.executable, str(root / "bootstrap.py"), "--no-browser", "--port", str(PORT)],
                        cwd=root, creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
t0 = time.monotonic()
while time.monotonic() - t0 < 90 and not up(f"http://127.0.0.1:{PORT}/_stcore/health"):
    time.sleep(0.5)
print(f"app arriba en :{PORT}: {listening(PORT)}")

proc.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT)
code = proc.wait(timeout=30)
time.sleep(1)
print(f"bootstrap terminó con código {code}")
print(f"puerto {PORT} liberado (Streamlit cerrado): {not listening(PORT)}")
print(f"Ollama previo sigue arriba: {up('http://127.0.0.1:11434/api/version')} (antes: {ollama_before})")
