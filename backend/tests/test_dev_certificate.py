from datetime import UTC, datetime, timedelta
import ipaddress
from pathlib import Path
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import scripts.generate_lan_dev_certificate as certificate_setup


def test_lan_certificate_refresh_keeps_existing_ca_and_updates_dynamic_ip(monkeypatch) -> None:
    with tempfile.TemporaryDirectory(prefix=".pytest-dev-cert-", dir=Path.cwd()) as temporary:
        output = Path(temporary)
        monkeypatch.setattr(certificate_setup, "OUTPUT", output)

        ca_path, server_path, ca_created, server_created = certificate_setup.prepare_certificates("10.84.2.18")
        assert ca_created is True
        assert server_created is True
        first_ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
        first_server = x509.load_pem_x509_certificate(server_path.read_bytes())
        first_ca_fingerprint = first_ca.fingerprint(hashes.SHA256())
        first_san = first_server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert x509.IPAddress(ipaddress.ip_address("10.84.2.18")) in first_san
        assert x509.DNSName("localhost") in first_san
        assert first_server.issuer == first_ca.subject
        assert certificate_setup._verify_rsa_signature(first_server, first_ca)

        ca_path, server_path, ca_created, server_created = certificate_setup.prepare_certificates("10.84.2.19")
        second_ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
        second_server = x509.load_pem_x509_certificate(server_path.read_bytes())
        second_san = second_server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert ca_created is False
        assert server_created is True
        assert second_ca.fingerprint(hashes.SHA256()) == first_ca_fingerprint
        assert x509.IPAddress(ipaddress.ip_address("10.84.2.19")) in second_san
        assert x509.DNSName("localhost") in second_san
        assert second_server.issuer == second_ca.subject
        assert certificate_setup._verify_rsa_signature(second_server, second_ca)


def test_trusted_ca_is_not_added_a_second_time(monkeypatch) -> None:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KYRA Local Development CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    with tempfile.TemporaryDirectory(prefix=".pytest-dev-cert-", dir=Path.cwd()) as temporary:
        certificate_path = Path(temporary) / "kyra-dev-ca.crt"
        certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        monkeypatch.setattr(certificate_setup, "current_user_trusts_ca", lambda _certificate: True)
        monkeypatch.setattr(certificate_setup.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("already-trusted CA must not be re-added")))

        assert certificate_setup.install_ca_for_current_user(certificate_path, certificate) is False
