"""Serve a LiveTranslate release directory over read-only HTTP or HTTPS."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MAX_MANIFEST = 64 * 1024
MAX_PACKAGE = 16 * 1024 * 1024
MAX_CONNECTIONS = 8
SOCKET_TIMEOUT = 10
COMPONENT = r"(?:0|[1-9][0-9]{0,4})"
PACKAGE_PATH = re.compile(rf"/LiveTranslate-{COMPONENT}(?:\.{COMPONENT}){{2,3}}\.json", re.ASCII)


def route(raw):
    if raw == "/latest.json":
        return "latest.json", MAX_MANIFEST
    if PACKAGE_PATH.fullmatch(raw):
        return raw[1:], MAX_PACKAGE
    return None


def regular(entry):
    return (stat.S_ISREG(entry.st_mode)
            and not (getattr(entry, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


class ChangingRelease(Exception):
    pass


def load_file(root, name, limit, include_body):
    """Read one complete bounded snapshot and close it before sending any response."""
    path = root / name
    for _ in range(3):
        before = path.lstat()
        if not regular(before):
            raise FileNotFoundError(name)
        flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not regular(opened) or not os.path.samestat(before, opened):
                continue
            if not 0 < opened.st_size <= limit:
                raise ChangingRelease("Size is outside the release limits.")
            if not include_body:
                return opened.st_size, b""
            data = stream.read(opened.st_size + 1)
            after = os.fstat(stream.fileno())
            if (len(data) == opened.st_size == after.st_size and
                    after.st_mtime_ns == opened.st_mtime_ns):
                return len(data), data
    raise ChangingRelease("File was replaced during publication.")


class ReleaseHandler(BaseHTTPRequestHandler):
    # Each request is completed and releases its bounded connection slot.
    protocol_version = "HTTP/1.0"

    def version_string(self):
        return "LiveTranslate"

    def endpoint(self):
        # Inspect the request target before the HTTP parser normalizes a leading //.
        fields = getattr(self, "requestline", "").split()
        return route(fields[1]) if len(fields) in (2, 3) else None

    def log_message(self, format, *args):
        # Never print headers, arbitrary paths, query strings or request bodies.
        pass

    def log_request(self, code="-", size="-"):
        endpoint = self.endpoint()
        name = endpoint[0] if endpoint else "unknown resource"
        if self.server.access_log:
            method = getattr(self, "command", "")
            if method not in {"GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "CONNECT"}:
                method = "unknown method"
            print(f"{self.log_date_time_string()} {self.client_address[0]} {method} {name} {code}",
                  file=sys.stderr, flush=True)

    def response(self, status, body=b"", size=None, allow=False):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body) if size is None else size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        if allow:
            self.send_header("Allow", "GET, HEAD")
        if status == 503:
            self.send_header("Retry-After", "1")
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)
        self.close_connection = True

    def read_release(self):
        endpoint = self.endpoint()
        if not endpoint:
            self.response(404, b'{"error":"Release file not found."}\n')
            return
        name, limit = endpoint
        try:
            size, data = load_file(self.server.release_dir, name, limit, self.command == "GET")
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            self.response(404, b'{"error":"Release file not found."}\n')
            return
        except (ChangingRelease, OSError):
            self.response(503, b'{"error":"Release file temporarily unavailable."}\n')
            return
        self.response(200, data, size)

    do_GET = read_release
    do_HEAD = read_release

    def reject_write(self):
        self.response(405, b'{"error":"The release server only accepts GET and HEAD."}\n', allow=True)

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = reject_write


class ReleaseServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    allow_reuse_address = os.name != "nt"

    def __init__(self, root, address, tls_context=None, access_log=True):
        self.release_dir = root.resolve(strict=True)
        if not self.release_dir.is_dir():
            raise ValueError("The release root must be a directory.")
        host = ipaddress.ip_address(address[0])
        if not host.is_loopback and tls_context is None:
            raise ValueError("Provide --cert and --key to serve updates beyond loopback.")
        self.address_family = socket.AF_INET6 if host.version == 6 else socket.AF_INET
        self.tls_context = tls_context
        self.access_log = access_log
        self.connection_slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(address, ReleaseHandler)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def get_request(self):
        client, peer = super().get_request()
        client.settimeout(SOCKET_TIMEOUT)
        return client, peer

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(blocking=False):
            self.close_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()

    def finish_request(self, request, client_address):
        # A slow TLS handshake occupies only its own bounded worker.
        try:
            if self.tls_context is not None:
                with self.tls_context.wrap_socket(request, server_side=True) as secure:
                    super().finish_request(secure, client_address)
            else:
                super().finish_request(request, client_address)
        except (ssl.SSLError, ConnectionError, socket.timeout):
            pass


def tls_context(cert, key):
    if bool(cert) != bool(key):
        raise ValueError("--cert and --key must be provided together.")
    if not cert:
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    return context


def parent_lifetime(server):
    try:
        while sys.stdin.buffer.read(4096):
            pass
    except OSError:
        pass
    finally:
        server.shutdown()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Folder containing latest.json and release packages")
    parser.add_argument("--bind", default="127.0.0.1", help="Listening IP address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8763, help="Listening TCP port; 0 selects an available port")
    parser.add_argument("--cert", type=Path, help="PEM server certificate chain for HTTPS")
    parser.add_argument("--key", type=Path, help="PEM private key matching the certificate")
    parser.add_argument("--parent-pipe", action="store_true", help="Exit automatically when standard input closes")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-request logs")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535.")
    host = "127.0.0.1" if args.bind == "localhost" else args.bind
    try:
        context = tls_context(args.cert, args.key)
        with ReleaseServer(args.root, (host, args.port), context, not args.quiet) as server:
            port = server.server_address[1]
            bound = ipaddress.ip_address(host)
            url_host = f"[{host}]" if bound.version == 6 else host
            scheme = "https" if context else "http"
            print(json.dumps({"ready": True, "url": f"{scheme}://{url_host}:{port}/latest.json"},
                             separators=(",", ":")), flush=True)
            if args.parent_pipe:
                threading.Thread(target=parent_lifetime, args=(server,), daemon=True).start()
            try:
                server.serve_forever(poll_interval=.1)
            except KeyboardInterrupt:
                pass
    except (ValueError, OSError) as exc:
        print("LiveTranslate release server: " + str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
