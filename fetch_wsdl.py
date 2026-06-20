"""Fetch e analisa o WSDL do webservice de Campinas."""
import sys, requests, warnings, tempfile, os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

pfx = Path(r"c:\dev\conta-tools-nfse\dados\CONTABNEW_ASSESSORIA_EMPRESARIAL_LTDA_03875717000175.pfx").read_bytes()
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    pk, cert, _ = pkcs12.load_key_and_certificates(pfx, b"1234")

key_pem = pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
cert_pem = cert.public_bytes(serialization.Encoding.PEM)
tf_cert = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
tf_key  = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
tf_cert.write(cert_pem); tf_cert.close()
tf_key.write(key_pem);   tf_key.close()

try:
    s = requests.Session()
    s.cert = (tf_cert.name, tf_key.name)
    r = s.get("https://homol-rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl", timeout=30)
    wsdl = r.text
    Path("wsdl_campinas.xml").write_text(wsdl, encoding="utf-8")
    print("WSDL salvo em wsdl_campinas.xml")

    # Buscar definição do tipo RecepcionarLoteRpsSincrono
    marker = 'complexType name="RecepcionarLoteRpsSincrono"'
    idx = wsdl.find(marker)
    print(f"\n--- complexType RecepcionarLoteRpsSincrono (offset {idx}) ---")
    print(wsdl[idx:idx+2000])
finally:
    os.unlink(tf_cert.name)
    os.unlink(tf_key.name)
