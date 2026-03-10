#!/usr/bin/env python3
"""Push segments to Liquidsoap via telnet API."""

import socket
import logging
from pathlib import Path
import config

log = logging.getLogger(__name__)


HOST_SEGMENTS_DIR = "/home/morpheus/Hackstuff/drift-radio/segments"
CONTAINER_SEGMENTS_DIR = "/segments"


def _telnet_cmd(cmd: str) -> str:
    """Send a single telnet command to Liquidsoap and return response."""
    host, port = config.LIQUIDSOAP_TELNET
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(f"{cmd}\n".encode())
        response = b""
        sock.settimeout(3)
        try:
            while b"\n" not in response:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                response += chunk
        except socket.timeout:
            pass
        sock.sendall(b"quit\n")
    return response.decode().strip()


def push_segment(path: str | Path, priority: bool = False) -> bool:
    """Push a segment file to Liquidsoap's request queue.
    If priority=True, pushes to the urgent queue which interrupts immediately.
    Returns True on success."""
    path = Path(path).resolve()
    # Remap host path to container path
    path_str = str(path).replace(HOST_SEGMENTS_DIR, CONTAINER_SEGMENTS_DIR)
    queue_name = "urgent" if priority else "segments"
    try:
        resp = _telnet_cmd(f"{queue_name}.push {path_str}")
        log.info(f"[liq] {'URGENT' if priority else 'queued'} {path.name} → {resp}")
        return True
    except Exception as e:
        log.error(f"[liq] telnet push failed: {e}")
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: liquidsoap_queue.py <segment.mp3>")
        sys.exit(1)

    ok = push_segment(sys.argv[1])
    sys.exit(0 if ok else 1)
