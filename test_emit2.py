"""Testa emissão com SOAP direto (sem nfseDadosMsg, elementos unqualified)."""
import os, sys
from pathlib import Path

os.environ["NFSE_DEBUG_SOAP"] = str(Path(__file__).parent)

sys.path.insert(0, r"c:\dev\conta-tools-nfse\src")
sys.path.insert(0, r"c:\dev\conta-tools-shared\src")

from decimal import Decimal
from conta_tools_shared.domain.nfse import NfseRequest, PrestadorNfse, TomadorNfse
from conta_tools_nfse.drivers.campinas import CampinasDriver

CERT = Path(r"c:\dev\conta-tools-nfse\dados\CONTABNEW_ASSESSORIA_EMPRESARIAL_LTDA_03875717000175.pfx")
SENHA = "1234"

prestador = PrestadorNfse(
    cnpj="03875717000175",
    inscricao_municipal="000710504",
    cert_path=CERT,
    cert_senha=SENHA,
)
# Dados da linha 2 do edm_teste_campinas.xlsx
tomador = TomadorNfse(
    razao_social="EDM ASSESSORIA ADMINISTRATIVA E TECNOLOGICA EIRELI",
    cnpj="18298204000116",
    email="ericmaubr@gmail.com",
    logradouro="R SALDANHA DA GAMA",
    numero="244",
    bairro="LAPA",
    cep="05081000",
    municipio_ibge="3550308",
    uf="SP",
)
req = NfseRequest(
    id="test-campinas-001",
    prestador=prestador,
    tomador=tomador,
    numero_rps="12751",
    serie_rps="1",
    tipo_rps="1",
    competencia="2026-06",
    discriminacao=(
        "Honorarios Contabeis - Prestacao de servico em contabilidade\n"
        "Honorarios Contabeis - Prestacao de servicos de Departamento Pessoal\n"
        "Honorarios Contabeis - Prestacao de servicos Fiscais\n\n"
        "Contrato N. 2025/00103 - Ref. Abr/2026 - Vencto. 15/05/2026"
    ),
    valor_servico=Decimal("450.00"),
    deducoes=Decimal("0.00"),
    codigo_servico="17.19",
    codigo_cnae="6920601",
    iss_retido=False,
    optante_simples=False,  # IMA/Campinas cadastrou como NÃO OPTANTE (verificar no portal)
    municipio_prestacao="campinas",
)

driver = CampinasDriver(ambiente="homologacao")

# Mostra o SOAP gerado para debug
from conta_tools_shared.nfse.signer import assinar_elemento
from lxml import etree

print("=== Gerando SOAP para debug (sem enviar) ===")
print(req)
print("-" * 40)

envio_el = driver._montar_envio_el(req, ns="")
lote_el = envio_el.find("LoteRps")
assinar_elemento(envio_el, lote_el, CERT, SENHA, reference_id="lote1")
soap_bytes = driver._montar_soap_sincrono(envio_el)
print("=== SOAP gerado (primeiros 2000 chars) ===")
print(soap_bytes.decode("utf-8")[:2000])
print("...\n")

print("=== Enviando para homologação ===")
try:
    result = driver.emitir(req)
    print(f"SUCESSO! NFS-e numero={result.numero_nota}, cod_verif={result.codigo_verificacao}")
    if result.link_consulta:
        print(f"Link: {result.link_consulta}")
except RuntimeError as e:
    print(f"ERRO: {e}")
    resp_file = Path("soap_response_RecepcionarLoteRpsSincrono.xml")
    if resp_file.exists():
        print("\n=== Resposta SOAP ===")
        print(resp_file.read_text(encoding="utf-8", errors="replace")[:3000])
