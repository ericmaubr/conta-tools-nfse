"""Driver de emissão de NFS-e para a Prefeitura de Campinas (ABRASF 2.03)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from lxml import etree

from conta_tools_shared.domain.nfse import NfseRequest, NfseResult, PrestadorNfse
from conta_tools_shared.nfse.signer import assinar_xml
from conta_tools_shared.nfse.transport import soap_transport

from conta_tools_nfse.drivers.base import NfseDriver

# Namespace ABRASF 2.03
_NS = "http://www.abrasf.org.br/nfse.xsd"
_IBGE_CAMPINAS = "3509502"

_WSDL = {
    "producao": "https://rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl",
    "homologacao": "https://homol-rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl",
}


class CampinasDriver(NfseDriver):
    """
    Emite NFS-e via webservice ABRASF 2.03 da Prefeitura de Campinas.

    Fluxo:
        1. Monta XML do InfDeclaracaoPrestacaoServico
        2. Assina com certificado A1 (enveloped RSA-SHA1)
        3. Envolve em LoteRps > EnviarLoteRpsSincronoEnvio
        4. Chama RecepcionarLoteRpsSincrono via SOAP com mutual TLS
        5. Parseia resposta e retorna NfseResult

    NOTA: Os nomes dos parâmetros SOAP (nfseCabecMsg / nfseDadosMsg) e o
    namespace exato devem ser validados contra o WSDL de homologação antes
    do uso em produção.
    """

    def __init__(self, ambiente: str = "producao") -> None:
        if ambiente not in _WSDL:
            raise ValueError(f"ambiente deve ser 'producao' ou 'homologacao', não {ambiente!r}")
        self.wsdl = _WSDL[ambiente]

    # ------------------------------------------------------------------ #
    # Interface pública                                                    #
    # ------------------------------------------------------------------ #

    def emitir(self, req: NfseRequest) -> NfseResult:
        inf_bytes = self._montar_inf_rps(req)
        inf_assinado = assinar_xml(
            inf_bytes,
            req.prestador.cert_path,
            req.prestador.cert_senha,
            reference_id="rps1",
        )
        dados_xml = self._montar_envelope(inf_assinado, req)
        cabecalho_xml = self._cabecalho()

        import zeep

        with soap_transport(req.prestador.cert_path, req.prestador.cert_senha) as transport:
            client = zeep.Client(wsdl=self.wsdl, transport=transport)
            response = client.service.RecepcionarLoteRpsSincrono(
                nfseCabecMsg=cabecalho_xml,
                nfseDadosMsg=dados_xml,
            )

        return self._parsear_resposta(response, req.numero_rps, req.competencia)

    def cancelar(
        self,
        numero_nota: str,
        prestador: PrestadorNfse,
        codigo_cancelamento: str = "2",
    ) -> None:
        pedido_xml = self._montar_pedido_cancelamento(
            numero_nota, prestador, codigo_cancelamento
        )
        pedido_assinado = assinar_xml(
            pedido_xml,
            prestador.cert_path,
            prestador.cert_senha,
            reference_id="cancelamento1",
        )
        cabecalho_xml = self._cabecalho()

        import zeep

        with soap_transport(prestador.cert_path, prestador.cert_senha) as transport:
            client = zeep.Client(wsdl=self.wsdl, transport=transport)
            response = client.service.CancelarNfse(
                nfseCabecMsg=cabecalho_xml,
                nfseDadosMsg=pedido_assinado.decode(),
            )
        self._verificar_erros_resposta(response)

    # ------------------------------------------------------------------ #
    # XML builders                                                         #
    # ------------------------------------------------------------------ #

    def _montar_inf_rps(self, req: NfseRequest) -> bytes:
        """Monta o elemento InfDeclaracaoPrestacaoServico (sem assinatura)."""
        ns = _NS
        data_emissao = req.data_emissao or date.today().isoformat()
        competencia_dt = f"{req.competencia}-01T00:00:00"
        optante = "1" if req.optante_simples else "2"
        iss_retido_cod = "1" if req.iss_retido else "2"

        inf = etree.Element(f"{{{ns}}}InfDeclaracaoPrestacaoServico", attrib={"Id": "rps1"})

        # Rps
        rps_el = _sub(inf, ns, "Rps")
        id_rps = _sub(rps_el, ns, "IdentificacaoRps")
        _sub(id_rps, ns, "Numero").text = str(req.numero_rps)
        _sub(id_rps, ns, "Serie").text = req.serie_rps
        _sub(id_rps, ns, "Tipo").text = req.tipo_rps
        _sub(rps_el, ns, "DataEmissao").text = data_emissao
        _sub(rps_el, ns, "NaturezaOperacao").text = str(req.natureza_operacao)
        if req.regime_tributacao:
            _sub(rps_el, ns, "RegimeEspecialTributacao").text = str(req.regime_tributacao)
        _sub(rps_el, ns, "OptanteSimplesNacional").text = optante
        _sub(rps_el, ns, "IncentivadorCultural").text = "2"
        _sub(rps_el, ns, "Status").text = "1"

        _sub(inf, ns, "Competencia").text = competencia_dt

        # Serviço
        servico = _sub(inf, ns, "Servico")
        valores = _sub(servico, ns, "Valores")
        _sub(valores, ns, "ValorServicos").text = f"{req.valor_servico:.2f}"
        _sub(valores, ns, "ValorDeducoes").text = f"{req.deducoes:.2f}"
        _sub(valores, ns, "IssRetido").text = iss_retido_cod
        if req.valor_iss is not None:
            _sub(valores, ns, "ValorIss").text = f"{req.valor_iss:.2f}"
        _sub(servico, ns, "ItemListaServico").text = req.codigo_servico
        if req.codigo_cnae:
            _sub(servico, ns, "CodigoCnae").text = req.codigo_cnae
        _sub(servico, ns, "Discriminacao").text = req.discriminacao
        _sub(servico, ns, "CodigoMunicipio").text = _IBGE_CAMPINAS
        _sub(servico, ns, "ExigibilidadeISS").text = "1"
        _sub(servico, ns, "MunicipioIncidencia").text = _IBGE_CAMPINAS

        # Prestador
        prestador_el = _sub(inf, ns, "Prestador")
        _cnpj_element(prestador_el, ns, req.prestador.cnpj)
        _sub(prestador_el, ns, "InscricaoMunicipal").text = req.prestador.inscricao_municipal

        # Tomador
        tomador_el = _sub(inf, ns, "Tomador")
        id_tom = _sub(tomador_el, ns, "IdentificacaoTomador")
        cpf_cnpj_t = _sub(id_tom, ns, "CpfCnpj")
        if req.tomador.cnpj:
            _sub(cpf_cnpj_t, ns, "Cnpj").text = req.tomador.cnpj
        elif req.tomador.cpf:
            _sub(cpf_cnpj_t, ns, "Cpf").text = req.tomador.cpf
        if req.tomador.inscricao_municipal:
            _sub(id_tom, ns, "InscricaoMunicipal").text = req.tomador.inscricao_municipal

        _sub(tomador_el, ns, "RazaoSocial").text = req.tomador.razao_social

        if req.tomador.logradouro:
            end = _sub(tomador_el, ns, "Endereco")
            _sub(end, ns, "Logradouro").text = req.tomador.logradouro
            if req.tomador.numero:
                _sub(end, ns, "Numero").text = req.tomador.numero
            if req.tomador.complemento:
                _sub(end, ns, "Complemento").text = req.tomador.complemento
            if req.tomador.bairro:
                _sub(end, ns, "Bairro").text = req.tomador.bairro
            if req.tomador.municipio_ibge:
                _sub(end, ns, "CodigoMunicipio").text = req.tomador.municipio_ibge
            if req.tomador.uf:
                _sub(end, ns, "Uf").text = req.tomador.uf
            if req.tomador.cep:
                _sub(end, ns, "Cep").text = req.tomador.cep

        if req.tomador.email:
            contato = _sub(tomador_el, ns, "Contato")
            _sub(contato, ns, "Email").text = req.tomador.email

        return etree.tostring(inf, encoding="unicode").encode()

    def _montar_envelope(self, inf_assinado: bytes, req: NfseRequest) -> str:
        """Envolve o RPS assinado no envelope EnviarLoteRpsSincronoEnvio."""
        ns = _NS
        root = etree.Element(f"{{{ns}}}EnviarLoteRpsSincronoEnvio")
        lote = _sub(root, ns, "LoteRps", versao="2.03")
        _sub(lote, ns, "NumeroLote").text = "1"
        prestador_el = _sub(lote, ns, "Prestador")
        _cnpj_element(prestador_el, ns, req.prestador.cnpj)
        _sub(prestador_el, ns, "InscricaoMunicipal").text = req.prestador.inscricao_municipal
        _sub(lote, ns, "QuantidadeRps").text = "1"

        lista = _sub(lote, ns, "ListaRps")
        rps_el = _sub(lista, ns, "Rps")
        rps_el.append(etree.fromstring(inf_assinado))

        return etree.tostring(root, encoding="unicode")

    @staticmethod
    def _cabecalho() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<p:cabecalho versao="2.03" xmlns:p="{_NS}">'
            "<versaoDados>2.03</versaoDados>"
            "</p:cabecalho>"
        )

    def _montar_pedido_cancelamento(
        self,
        numero_nota: str,
        prestador: PrestadorNfse,
        codigo_cancelamento: str,
    ) -> bytes:
        ns = _NS
        inf = etree.Element(f"{{{ns}}}InfPedidoCancelamento", attrib={"Id": "cancelamento1"})
        id_nfse = _sub(inf, ns, "IdentificacaoNfse")
        _sub(id_nfse, ns, "Numero").text = numero_nota
        _cnpj_element(id_nfse, ns, prestador.cnpj)
        _sub(id_nfse, ns, "InscricaoMunicipal").text = prestador.inscricao_municipal
        _sub(id_nfse, ns, "CodigoMunicipio").text = _IBGE_CAMPINAS
        _sub(inf, ns, "CodigoCancelamento").text = codigo_cancelamento
        return etree.tostring(inf, encoding="unicode").encode()

    # ------------------------------------------------------------------ #
    # Parsers de resposta                                                  #
    # ------------------------------------------------------------------ #

    def _parsear_resposta(self, response: Any, numero_rps: str, competencia: str) -> NfseResult:
        """Parseia a resposta SOAP e extrai NfseResult ou levanta exceção com a mensagem de erro."""
        resp_str = response if isinstance(response, str) else str(response)
        resp_xml = etree.fromstring(resp_str.encode() if isinstance(resp_str, str) else resp_str)
        ns = _NS

        # Verificar erros
        erros = resp_xml.findall(f".//{{{ns}}}MensagemRetorno")
        if erros:
            msgs = [
                f"{e.findtext(f'{{{ns}}}Codigo', '')}: {e.findtext(f'{{{ns}}}Mensagem', '')}"
                for e in erros
            ]
            raise RuntimeError(f"Webservice retornou erro(s): {' | '.join(msgs)}")

        # Extrair dados da NFS-e
        numero = resp_xml.findtext(f".//{{{ns}}}Numero") or ""
        codigo_verif = resp_xml.findtext(f".//{{{ns}}}CodigoVerificacao") or ""
        link = resp_xml.findtext(f".//{{{ns}}}LinkConsultaNfse") or ""

        if not numero:
            raise RuntimeError("Resposta do webservice não contém número da NFS-e.")

        return NfseResult(
            numero_nota=numero,
            codigo_verificacao=codigo_verif,
            competencia=competencia,
            xml_retorno=resp_str.encode() if isinstance(resp_str, str) else resp_str,
            link_consulta=link,
            numero_rps_origem=str(numero_rps),
        )

    def _verificar_erros_resposta(self, response: Any) -> None:
        resp_str = response if isinstance(response, str) else str(response)
        resp_xml = etree.fromstring(resp_str.encode() if isinstance(resp_str, str) else resp_str)
        ns = _NS
        erros = resp_xml.findall(f".//{{{ns}}}MensagemRetorno")
        if erros:
            msgs = [
                f"{e.findtext(f'{{{ns}}}Codigo', '')}: {e.findtext(f'{{{ns}}}Mensagem', '')}"
                for e in erros
            ]
            raise RuntimeError(f"Webservice retornou erro(s): {' | '.join(msgs)}")


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _sub(parent: etree._Element, ns: str, tag: str, **attrib: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{ns}}}{tag}", attrib=attrib)


def _cnpj_element(parent: etree._Element, ns: str, cnpj: str) -> None:
    cpf_cnpj = _sub(parent, ns, "CpfCnpj")
    _sub(cpf_cnpj, ns, "Cnpj").text = cnpj
