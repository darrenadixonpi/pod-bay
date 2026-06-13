"""Serve the Pod Bay backend over HTTPS on the local network.

The PWA service worker (sw.js) only registers over a *secure* origin — HTTPS or
localhost. To install Pod Bay on a phone in the garage you therefore need the
backend reachable over HTTPS at the machine's LAN address, not plain HTTP.

This launcher does three things:
  1. Detects this machine's LAN IP (override with --host-ip or PODBAY_LAN_IP).
  2. Ensures a self-signed certificate exists for that IP (generates one with
     the `cryptography` package, caching it under .certs/ and regenerating only
     when the IP changes).
  3. Starts uvicorn bound to 0.0.0.0 over TLS, so any device on the same wifi
     can reach https://<lan-ip>:<port>/.

Usage (from app/backend/, with the venv active):
    python run_lan.py                 # auto-detect IP, port 8000
    python run_lan.py --port 8443
    python run_lan.py --host-ip 192.168.1.50 --reload

A self-signed cert will show a browser warning the first time; see
docs/MOBILE_ACCESS.md for trusting it on a phone, and for the Tailscale
alternative (which gives a real, warning-free certificate).
"""
import argparse
import datetime as dt
import ipaddress
import os
import socket
import sys
from pathlib import Path

CERT_DIR = Path(__file__).with_name(".certs")
CERT_FILE = CERT_DIR / "podbay.crt"
KEY_FILE = CERT_DIR / "podbay.key"
IP_SIDECAR = CERT_DIR / "issued_for.txt"  # the IP the cached cert was made for


def detect_lan_ip() -> str:
    """Best-effort LAN IPv4 of this machine.

    Opens a UDP socket toward a public address (no packets are actually sent)
    and reads back the local address the OS would route through — this yields
    the real LAN interface IP rather than 127.0.0.1.
    """
    override = os.environ.get("PODBAY_LAN_IP")
    if override:
        return override
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def generate_cert(ip: str) -> None:
    """Write a self-signed cert+key for `ip` (+localhost) into CERT_DIR.

    Requires the `cryptography` package. The IP and DNS names go in the Subject
    Alternative Name extension — modern browsers ignore the legacy CN field, so
    SAN is what actually makes https://<ip>/ validate against this cert.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        sys.exit(
            "This launcher needs the 'cryptography' package to generate a TLS "
            "certificate.\n\n    pip install cryptography\n\n"
            "(It is intentionally not in requirements.txt — only LAN HTTPS "
            "serving needs it.) Alternatively, see docs/MOBILE_ACCESS.md for the "
            "Tailscale path, which provides a real certificate and no warnings."
        )

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    san = [x509.DNSName("localhost")]
    # 127.0.0.1 always; the LAN IP when it parses as one.
    san.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    try:
        san.append(x509.IPAddress(ipaddress.ip_address(ip)))
    except ValueError:
        san.append(x509.DNSName(ip))  # hostname rather than a literal IP

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Pod Bay (self-signed)")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=825))  # max browsers accept
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    IP_SIDECAR.write_text(ip, encoding="utf-8")


def ensure_cert(ip: str) -> None:
    """Generate the cert only when missing or when the LAN IP has changed."""
    have_all = CERT_FILE.exists() and KEY_FILE.exists() and IP_SIDECAR.exists()
    issued_for = IP_SIDECAR.read_text(encoding="utf-8").strip() if IP_SIDECAR.exists() else None
    if have_all and issued_for == ip:
        return
    reason = "no certificate cached" if not have_all else f"LAN IP changed ({issued_for} → {ip})"
    print(f"[run_lan] Generating self-signed certificate ({reason})…", file=sys.stderr)
    generate_cert(ip)


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve Pod Bay over HTTPS on the LAN.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PODBAY_PORT", "8000")))
    ap.add_argument("--host-ip", default=None,
                    help="Override the detected LAN IP used in the certificate.")
    ap.add_argument("--reload", action="store_true",
                    help="Auto-reload on code changes (development).")
    args = ap.parse_args()

    ip = args.host_ip or detect_lan_ip()
    ensure_cert(ip)

    import uvicorn

    print(
        f"\n  Pod Bay is serving over HTTPS.\n"
        f"  On this machine:  https://localhost:{args.port}/\n"
        f"  On your phone:    https://{ip}:{args.port}/   (same wifi)\n\n"
        f"  First visit shows a certificate warning — accept it (or trust the\n"
        f"  cert per docs/MOBILE_ACCESS.md so the PWA can be installed).\n",
        file=sys.stderr,
    )

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=args.port,
        reload=args.reload,
        ssl_certfile=str(CERT_FILE),
        ssl_keyfile=str(KEY_FILE),
    )


if __name__ == "__main__":
    main()
