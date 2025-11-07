# ui/network_monitor.py
from PyQt5.QtCore import QThread, pyqtSignal, QObject
import time
import requests
from typing import Tuple
from firebase.config import db

class NetworkMonitor(QThread):
    """
    Periodically checks internet connectivity and latency without blocking the UI.
    Emits:
      - status_changed(status: str, rtt_ms: int | None)
        where status ∈ {"online", "slow", "offline"} and rtt_ms may be None if offline.
    """
    status_changed = pyqtSignal(str, int)

    def __init__(self, interval_sec: float = 3.0, slow_threshold_ms: int = 800, parent=None):
        super().__init__(parent)
        self.interval_sec = interval_sec
        self.slow_threshold_ms = slow_threshold_ms
        self._running = True
        self._session = requests.Session()

        # Very lightweight “204 No Content” endpoints used by many apps
        self._probe_urls = [
            # tries a Google static endpoint first (fast, cached worldwide)
            "https://www.gstatic.com/generate_204",
            # fallback to another common 204
            "https://clients3.google.com/generate_204",
        ]

    def stop(self):
        """Request stop and wait a bit so the thread actually exits."""
        self._running = False
        # Wait up to 2s for the run() loop to finish (avoid 'QThread destroyed' warning)
        try:
            self.wait(2000)
        except Exception:
            pass

    def _probe_once(self) -> Tuple[str, int]:
        """
        Returns (status, rtt_ms). status in {"online", "slow", "offline"}.
        rtt_ms may be None for offline.
        """
        for url in self._probe_urls:
            t0 = time.perf_counter()
            try:
                # Tight timeouts so we never hang the app waiting on sockets
                # (connect timeout, read timeout)
                r = self._session.get(url, timeout=(1.5, 1.5), allow_redirects=False)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)

                # Most of these endpoints return 204; accept 200 as "online" too (some proxies).
                if 200 <= r.status_code < 400:
                    if elapsed_ms > self.slow_threshold_ms:
                        return "slow", elapsed_ms
                    return "online", elapsed_ms
                # Unusual status – treat as offline and try next URL
            except Exception:
                # try the next probe URL
                pass

        # All probes failed
        return "offline", -1

    def run(self):
        last_status = None
        while self._running:
            status, rtt = self._probe_once()
            if status != last_status:
                self.status_changed.emit(status, rtt if rtt >= 0 else 0)
                last_status = status

            # sleep in small slices so stop() becomes responsive
            total = float(self.interval_sec)
            step = 0.1
            slept = 0.0
            while self._running and slept < total:
                time.sleep(step)
                slept += step

# class MaintenanceMonitor(QThread):
#     """
#     Lightweight, low-frequency checker for Firestore doc: meta/maintenance_mode { status: bool }
#     Emits:
#       - maintenance_changed(is_active: bool)
#     Notes:
#       - Polls at 'interval_sec' (default 300s).
#       - You can call trigger_check_now() (e.g., right after network comes back online)
#         to do an immediate single read, but it self-throttles.
#     """
#     maintenance_changed = pyqtSignal(bool)

#     def __init__(self, interval_sec: float = 100.0, parent=None):
#         super().__init__(parent)
#         self.interval_sec = max(60.0, float(interval_sec))  # be kind to quotas
#         self._running = True
#         self._last_state = None
#         self._force_check = False
#         self._min_gap_sec = 30.0  # throttle forced checks
#         self._last_check_ts = 0.0

#     def stop(self):
#         self._running = False
#         try:
#             self.wait(2000)
#         except Exception:
#             pass

#     def trigger_check_now(self):
#         import time
#         now = time.monotonic()
#         # avoid bursts of reads
#         if now - self._last_check_ts >= self._min_gap_sec:
#             self._force_check = True

#     def _read_flag(self) -> bool:
#         try:
#             doc = db.collection("meta").document("maintenance_mode").get()
#             if doc and doc.exists:
#                 d = doc.to_dict() or {}
#                 return bool(d.get("status", False))
#         except Exception:
#             # Fail-closed (treat as not in maintenance) to avoid locking out admins due to transient errors
#             pass
#         return False

#     def run(self):
#         import time
#         while self._running:
#             should_check = self._force_check
#             self._force_check = False

#             # time-based check
#             now = time.monotonic()
#             if not should_check and (now - self._last_check_ts) >= self.interval_sec:
#                 should_check = True

#             if should_check and self._running:
#                 self._last_check_ts = now
#                 state = self._read_flag()
#                 if state != self._last_state:
#                     self._last_state = state
#                     self.maintenance_changed.emit(state)

#             # tiny sleeps so stop() is responsive
#             step = 0.2
#             total = 1.0
#             slept = 0.0
#             while self._running and slept < total:
#                 time.sleep(step)
#                 slept += step
                
                

class MaintenanceWatcher(QObject):
    """
    Firestore realtime listener for meta/maintenance_mode {status: bool}
    Emits maintenance_changed(bool) immediately on server-side changes.
    Falls back to no-ops if watcher cannot be started; caller can keep a poller as backup.
    """
    maintenance_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unsubscribe = None
        self._last_state = None

    def _coerce_bool(self, val) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            return val.strip().lower() in ("1", "true", "yes", "on")
        return False

    def start(self):
        # avoid double subscribe
        self.stop()

        doc_ref = db.collection("meta").document("maintenance_mode")

        def _on_snapshot(doc_snapshot, changes, read_time):
            try:
                if not doc_snapshot:
                    return
                snap = doc_snapshot[0]
                if not snap.exists:
                    state = False
                else:
                    d = snap.to_dict() or {}
                    state = self._coerce_bool(d.get("status", False))
                if state != self._last_state:
                    self._last_state = state
                    self.maintenance_changed.emit(state)
            except Exception:
                # swallow listener exceptions; keep listener alive
                pass

        try:
            self._unsubscribe = doc_ref.on_snapshot(_on_snapshot)
        except Exception:
            # Listener not available (e.g., transient network). Leave _unsubscribe=None.
            self._unsubscribe = None

    def stop(self):
        try:
            if self._unsubscribe:
                self._unsubscribe()
        except Exception:
            pass
        finally:
            self._unsubscribe = None