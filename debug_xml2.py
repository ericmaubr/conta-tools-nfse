"""
Gera o XML assinado SEM enviar ao webservice.
Dumpa o XML completo e verifica a assinatura localmente.
"""
import sys, base64, hashlib
sys.path.insert(0, r"c:\dev\conta-tools-nfse\src")
sys.path.insert(0, r"c:\dev\conta-tools-shared\src")

from pathlib import Path
from lxml import etree
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import warnings

from conta_tools_nfse.conf import carregar_conf
from conta_tools_nfse.drivers.campinas import CampinasDriver
from conta_tools_nfse.excel.reader import ler_planilha_campinas

from conta_tools_shared.auth.certificate import cnpj_from_certificate, load_pfx_data

conf_path = Path(r"c:\dev\conta-tools-nfse\contabnew_asses.conf")
conf = carregar_conf(conf_path)

cert_data = load_pfx_data(conf.cert_path, conf.cert_senha)
cnpj = cnpj_from_certificate(cert_data)
planilha = Path(r"c:\dev\conta-tools-nfse\examples\edm_teste_campinas.xlsx")
reqs, erros = ler_planilha_campinas(planilha, cnpj, conf.inscricao_municipal, conf.cert_path, conf.cert_senha)
if erros:
    print("ERROS:", erros); sys.exit(1)

req = reqs[0]
drv = CampinasDriver(ambiente="homologacao")

# --- Montar XML completo (sem enviar) ---
envio_el = drv._montar_envio_el(req)
_NS = "http://www.abrasf.org.br/nfse.xsd"
lote_el = envio_el.find(f"{{{_NS}}}LoteRps")

from conta_tools_shared.nfse.signer import assinar_elemento

# Assina LoteRps (sibling em EnviarLoteRpsSincronoEnvio)
# Conforme template oficial Campinas: LoteRps Id="lote1" + Signature irmão
assinar_elemento(envio_el, lote_el, req.prestador.cert_path, req.prestador.cert_senha, "lote1")

xml_str = etree.tostring(envio_el, pretty_print=True, encoding="unicode")
print("=== XML GERADO ===")
print(xml_str[:6000])
Path("debug_envio2.xml").write_text(xml_str, encoding="utf-8")
print("\n--- Salvo: debug_envio2.xml ---\n")

# --- Verificar assinatura localmente ---
_XMLDSIG = "http://www.w3.org/2000/09/xmldsig#"
_C14N_10 = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"

pfx = Path(req.prestador.cert_path).read_bytes()
senha = req.prestador.cert_senha.encode() if req.prestador.cert_senha else b""
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    _, cert, _ = pkcs12.load_key_and_certificates(pfx, senha)
pub_key = cert.public_key()

def verificar_sig(label, signed_el, sig_el_parent, ref_elem):
    sig_el     = sig_el_parent.find(f"{{{_XMLDSIG}}}Signature")
    digest_b64 = sig_el.findtext(f".//{{{_XMLDSIG}}}DigestValue")
    sig_b64    = sig_el.findtext(f".//{{{_XMLDSIG}}}SignatureValue")

    ref_standalone = etree.fromstring(etree.tostring(ref_elem, encoding="unicode").encode())
    canon_ref = etree.tostring(ref_standalone, method="c14n", with_comments=False)
    recomputed = base64.b64encode(hashlib.sha1(canon_ref).digest()).decode()
    digest_ok = (recomputed == digest_b64)
    print(f"[{label}] DigestValue no XML : {digest_b64}")
    print(f"[{label}] DigestValue local  : {recomputed}")
    print(f"[{label}] Digest match       : {'OK' if digest_ok else 'FALHOU'}")

    si_el = sig_el.find(f"{{{_XMLDSIG}}}SignedInfo")
    si_standalone = etree.fromstring(etree.tostring(si_el, encoding="unicode").encode())
    canon_si = etree.tostring(si_standalone, method="c14n", with_comments=False)
    sig_bytes = base64.b64decode(sig_b64)
    try:
        pub_key.verify(sig_bytes, canon_si, padding.PKCS1v15(), hashes.SHA1())
        print(f"[{label}] RSA verify: VALIDO\n")
    except Exception as e:
        print(f"[{label}] RSA verify: INVALIDO — {e}\n")

verificar_sig("LoteRps", lote_el, envio_el, lote_el)

# Mostrar estrutura
print("\n=== ESTRUTURA EnviarLoteRpsSincronoEnvio ===")
for child in envio_el:
    tag = child.tag.split('}')[1] if '}' in child.tag else child.tag
    print(f"  {tag} id={child.get('Id', '')!r}")
