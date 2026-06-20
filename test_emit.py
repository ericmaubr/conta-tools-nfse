"""Envia UMA nota ao webservice de homologação de Campinas."""
import sys
sys.path.insert(0, r"c:\dev\conta-tools-nfse\src")
sys.path.insert(0, r"c:\dev\conta-tools-shared\src")

from pathlib import Path
from conta_tools_nfse.conf import carregar_conf
from conta_tools_nfse.drivers.campinas import CampinasDriver
from conta_tools_nfse.excel.reader import ler_planilha_campinas
from conta_tools_shared.auth.certificate import cnpj_from_certificate, load_pfx_data

conf = carregar_conf(Path(r"c:\dev\conta-tools-nfse\contabnew_asses.conf"))
cert_data = load_pfx_data(conf.cert_path, conf.cert_senha)
cnpj = cnpj_from_certificate(cert_data)
print(f"CNPJ prestador: {cnpj}")

reqs, erros = ler_planilha_campinas(
    Path(r"c:\dev\conta-tools-nfse\examples\edm_teste_campinas.xlsx"),
    cnpj, conf.inscricao_municipal, conf.cert_path, conf.cert_senha,
)
if erros:
    print("ERROS leitura:", erros); sys.exit(1)

req = reqs[0]
print(f"RPS {req.numero_rps} — {req.discriminacao} — R$ {req.valor_servico:.2f}")
print(f"Tomador: {req.tomador.razao_social} ({req.tomador.cnpj})")
print("Enviando ao webservice de HOMOLOGAÇÃO de Campinas...")

drv = CampinasDriver(ambiente="homologacao")
try:
    result = drv.emitir(req)
    print(f"\n>>> SUCESSO!")
    print(f"    NFS-e número  : {result.numero_nota}")
    print(f"    Cod. verific. : {result.codigo_verificacao}")
    print(f"    Link consulta : {result.link_consulta}")
except Exception as e:
    print(f"\n>>> ERRO: {e}")
    sys.exit(1)
