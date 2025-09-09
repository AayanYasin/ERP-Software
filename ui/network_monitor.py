# ui/network_monitor.py
from PyQt5.QtCore import QThread, pyqtSignal
import time
import requests
from typing import Tuple

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
