"""
End-to-end latency benchmark for GaiaNet Earth.

Starts the FastAPI server, sends N sequential requests to each endpoint for
a fixed point, and reports the FIRST request (empty in-memory caches) and
the WARM requests (2..N) separately — averaging them together hides both.

Upstream APIs are called live, so results depend on the network and on
free-tier rate limits. Disk caches (e.g. 1991-2020 anomaly baselines) are
NOT cleared, so a point checked before has a faster first request.

Run from the project root (with the backend's virtualenv active):
    python benchmark_latency.py
"""
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

# 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 (::1) first,
# the server listens on IPv4 only, and each refused IPv6 attempt costs ~2 s,
# which would be added to every measured request.
BASE = "http://127.0.0.1:8000"
LAT, LON = 39.80, -122.95
TRIALS = 10
PAUSE_S = 0.5
ENDPOINTS = [
    # No upstream work at all: whatever this costs is client/connection
    # overhead, not GaiaNet.
    ("Baseline (/api/status)", f"{BASE}/api/status"),
    ("Point climate (/climate)", f"{BASE}/climate?lat={LAT}&lon={LON}"),
    ("What-if (/prediction)", f"{BASE}/prediction?lat={LAT}&lon={LON}"),
    ("Environment (/environment)", f"{BASE}/environment?lat={LAT}&lon={LON}"),
]


# Never route local requests through a system/corporate proxy: on Windows
# urllib reads the proxy from the registry, and proxy handling (including the
# proxy-bypass lookup) can add delay to every request.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _server_ms(resp):
    """Server-side processing time from the Server-Timing header, if present."""
    header = resp.headers.get("Server-Timing") or ""
    for part in header.split(";"):
        part = part.strip()
        if part.startswith("dur="):
            try:
                return float(part[4:])
            except ValueError:
                return None
    return None


def wait_for_server(timeout_s: float = 60.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            _OPENER.open(f"{BASE}/api/status", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def time_requests(url: str):
    """Returns (total_ms, server_ms) per trial; None entries for failures."""
    totals, servers, failures = [], [], 0
    for i in range(TRIALS):
        start = time.perf_counter()
        try:
            with _OPENER.open(url, timeout=60) as resp:
                resp.read()
                srv = _server_ms(resp)
            ms = (time.perf_counter() - start) * 1000
            totals.append(ms)
            servers.append(srv)
            srv_s = f"{srv:.1f} ms" if srv is not None else "n/a"
            print(f"  Trial {i + 1}: total {ms:.1f} ms | server {srv_s}")
        except Exception as e:
            failures += 1
            totals.append(None)
            servers.append(None)
            print(f"  Trial {i + 1} failed: {e}")
        time.sleep(PAUSE_S)
    return totals, servers, failures


def _stats(values) -> str:
    v = [x for x in values if x is not None]
    if len(v) >= 2:
        return (f"{statistics.mean(v):,.0f} ± {statistics.stdev(v):,.0f}"
                f" (median {statistics.median(v):,.0f}, max {max(v):,.0f})")
    if v:
        return f"{v[0]:,.0f}"
    return "n/a"


def summarize(name: str, totals, servers, failures: int) -> str:
    def first(xs):
        return f"{xs[0]:,.0f}" if xs and xs[0] is not None else "n/a"
    note = f"  ({failures} failed)" if failures else ""
    return (f"{name}{note}\n"
            f"    first request : total {first(totals)} ms | server {first(servers)} ms\n"
            f"    requests 2-{TRIALS} : total {_stats(totals[1:])} ms\n"
            f"                    server {_stats(servers[1:])} ms")


def run_benchmark():
    backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
    print(f"Starting server in {backend_dir} ...")
    # Server output is discarded: an unread PIPE can fill up and stall the
    # server mid-benchmark.
    server = subprocess.Popen([sys.executable, "main.py"], cwd=backend_dir,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_for_server():
            print("Server did not come up within 60 s.")
            return
        print(f"Server is online. Measuring against {BASE} (no proxy).\n")
        results = []
        for name, url in ENDPOINTS:
            print(f"--- {name}: {TRIALS} sequential requests, {PAUSE_S} s apart ---")
            totals, servers, failures = time_requests(url)
            results.append(summarize(name, totals, servers, failures))
            print()
        print(f"=== RESULTS (ms), point ({LAT}, {LON}), base {BASE} ===")
        print("total = measured by this script; server = time spent inside GaiaNet (Server-Timing header)")
        for line in results:
            print(line)
    finally:
        print("\nShutting down server...")
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    run_benchmark()
