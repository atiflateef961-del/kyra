from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import ipaddress
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dev-certs"
CA_KEY_NAME = "kyra-dev-ca-key.pem"
CA_CERT_NAME = "kyra-dev-ca.crt"
TLS_KEY_NAME = "kyra-lan-key.pem"
TLS_CERT_NAME = "kyra-lan-cert.pem"


def private_key_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def current_lan_ip() -> str:
    """Resolve the IPv4 address selected by the current default LAN route."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 80))
        address = probe.getsockname()[0]
    parsed = ipaddress.ip_address(address)
    if not isinstance(parsed, ipaddress.IPv4Address) or not parsed.is_private or parsed.is_loopback:
        raise RuntimeError("No private, non-loopback LAN IPv4 address was found.")
    return address


def _public_key_bytes(key) -> bytes:
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def _verify_rsa_signature(certificate: x509.Certificate, issuer: x509.Certificate) -> bool:
    try:
        public_key = issuer.public_key()
        if not isinstance(public_key, rsa.RSAPublicKey):
            return False
        public_key.verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            padding.PKCS1v15(),
            certificate.signature_hash_algorithm,
        )
        return True
    except Exception:
        return False


def _load_or_create_ca(now: datetime) -> tuple[rsa.RSAPrivateKey, x509.Certificate, bool]:
    OUTPUT.mkdir(exist_ok=True)
    ca_key_path = OUTPUT / CA_KEY_NAME
    ca_cert_path = OUTPUT / CA_CERT_NAME
    key_exists, cert_exists = ca_key_path.exists(), ca_cert_path.exists()
    if key_exists != cert_exists:
        raise RuntimeError("The development CA files are incomplete. Restore both CA files; KYRA will not silently replace a trusted CA.")
    if key_exists:
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        ca_certificate = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
        if not isinstance(ca_key, rsa.RSAPrivateKey):
            raise RuntimeError("The existing development CA key is not an RSA key supported by this setup.")
        try:
            is_ca = ca_certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
        except x509.ExtensionNotFound:
            is_ca = False
        if (
            ca_certificate.subject != ca_certificate.issuer
            or not is_ca
            or _public_key_bytes(ca_key.public_key()) != _public_key_bytes(ca_certificate.public_key())
            or not _verify_rsa_signature(ca_certificate, ca_certificate)
            or not ca_certificate.not_valid_before_utc <= now <= ca_certificate.not_valid_after_utc
        ):
            raise RuntimeError("The existing KYRA development CA is invalid or expired; it was left unchanged.")
        print("Reusing the existing KYRA development CA.")
        return ca_key, ca_certificate, False

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KYRA Local Development CA")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1825))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_key_path.write_bytes(private_key_pem(ca_key))
    ca_cert_path.write_bytes(ca_certificate.public_bytes(serialization.Encoding.PEM))
    print("Created the KYRA local development CA.")
    return ca_key, ca_certificate, True


def _existing_server_certificate_is_valid(address: ipaddress.IPv4Address, ca_certificate: x509.Certificate) -> bool:
    key_path, cert_path = OUTPUT / TLS_KEY_NAME, OUTPUT / TLS_CERT_NAME
    if not key_path.exists() or not cert_path.exists():
        return False
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        extended_usage = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        return (
            isinstance(key, rsa.RSAPrivateKey)
            and certificate.issuer == ca_certificate.subject
            and _public_key_bytes(key.public_key()) == _public_key_bytes(certificate.public_key())
            and _verify_rsa_signature(certificate, ca_certificate)
            and certificate.not_valid_before_utc <= datetime.now(UTC) <= certificate.not_valid_after_utc
            and x509.IPAddress(address) in san
            and x509.DNSName("localhost") in san
            and ExtendedKeyUsageOID.SERVER_AUTH in extended_usage
        )
    except (OSError, ValueError, TypeError, x509.ExtensionNotFound):
        return False


def _write_server_certificate(address: ipaddress.IPv4Address, ca_key: rsa.RSAPrivateKey, ca_certificate: x509.Certificate, now: datetime) -> None:
    tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tls_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(address))])
    tls_certificate = (
        x509.CertificateBuilder()
        .subject_name(tls_name)
        .issuer_name(ca_certificate.subject)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=397))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(address), x509.DNSName("localhost")]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    (OUTPUT / TLS_KEY_NAME).write_bytes(private_key_pem(tls_key))
    (OUTPUT / TLS_CERT_NAME).write_bytes(
        tls_certificate.public_bytes(serialization.Encoding.PEM)
        + ca_certificate.public_bytes(serialization.Encoding.PEM)
    )
    print(f"Created a KYRA LAN server certificate for {address}, localhost, signed by the existing development CA.")


def _normalized_hex(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", value.casefold())


def current_user_trusts_ca(certificate: x509.Certificate) -> bool:
    """Check only the current user's Windows Trusted Root store."""
    if os.name != "nt":
        raise RuntimeError("The KYRA CA installer is available only on Windows.")
    certutil = shutil.which("certutil")
    if certutil is None:
        raise RuntimeError("Windows certutil.exe was not found; no certificate-store changes were made.")
    thumbprint = certificate.fingerprint(hashes.SHA1()).hex()
    result = subprocess.run(
        [certutil, "-user", "-store", "Root", thumbprint],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and _normalized_hex(thumbprint) in _normalized_hex(result.stdout + result.stderr)


def install_ca_for_current_user(certificate_path: Path, certificate: x509.Certificate) -> bool:
    r"""Install the public development CA into CurrentUser\Root; never the machine store."""
    if current_user_trusts_ca(certificate):
        print("KYRA development CA is already trusted in the current user's Windows Root store; no change made.")
        return False
    certutil = shutil.which("certutil")
    if os.name != "nt" or certutil is None:
        raise RuntimeError("Cannot install the KYRA development CA: Windows certutil.exe is unavailable.")
    result = subprocess.run(
        [certutil, "-user", "-addstore", "-f", "Root", str(certificate_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            "Could not install the public KYRA development CA in the current user's Root store. "
            f"No machine-wide store was modified. Windows reported: {detail or 'certutil failed'}."
        )
    if not current_user_trusts_ca(certificate):
        raise RuntimeError(r"certutil returned success, but the KYRA CA was not found in CurrentUser\Root afterward.")
    print("Installed the public KYRA development CA in the current user's Windows Root store.")
    return True


def prepare_certificates(lan_ip: str, *, force_server: bool = False) -> tuple[Path, Path, bool, bool]:
    address = ipaddress.ip_address(lan_ip)
    if not isinstance(address, ipaddress.IPv4Address) or not address.is_private or address.is_loopback:
        raise ValueError("lan_ip must be a private, non-loopback IPv4 address")
    now = datetime.now(UTC)
    ca_key, ca_certificate, ca_created = _load_or_create_ca(now)
    server_created = ca_created or force_server or not _existing_server_certificate_is_valid(address, ca_certificate)
    if server_created:
        _write_server_certificate(address, ca_key, ca_certificate, now)
    else:
        print(f"Reusing the existing KYRA LAN certificate for {address} and localhost.")
    return OUTPUT / CA_CERT_NAME, OUTPUT / TLS_CERT_NAME, ca_created, server_created


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and optionally trust KYRA's local LAN development CA and TLS certificate.")
    parser.add_argument("lan_ip", nargs="?", help="Private IPv4 address; defaults to the current LAN route address")
    parser.add_argument("--force", action="store_true", help="Reissue the LAN server certificate while retaining the existing CA")
    parser.add_argument("--install-ca", action="store_true", help="Trust the public CA in this Windows user's Root store")
    args = parser.parse_args()

    try:
        lan_ip = args.lan_ip or current_lan_ip()
        ca_path, _server_path, _ca_created, _server_created = prepare_certificates(lan_ip, force_server=args.force)
        if args.install_ca:
            ca_certificate = x509.load_pem_x509_certificate(ca_path.read_bytes())
            install_ca_for_current_user(ca_path, ca_certificate)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as cause:
        parser.error(str(cause))


if __name__ == "__main__":
    main()
