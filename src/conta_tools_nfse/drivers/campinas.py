"""Driver de emissão de NFS-e para a Prefeitura de Campinas (ABRASF 2.03)."""

from __future__ import annotations

from datetime import date

from lxml import etree

from conta_tools_shared.domain.nfse import NfseRequest, NfseResult, PrestadorNfse
from conta_tools_shared.nfse.signer import assinar_xml

from conta_tools_nfse.drivers.base import NfseDriverBase

_NS = "http://www.abrasf.org.br/nfse.xsd"
_IBGE_CAMPINAS = "3509502"

_WSDL = {
    "producao":    "https://rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl",
    "homologacao": "https://homol-rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl",
}


class CampinasDriver(NfseDriverBase):
    """
    Emite NFS-e via webservice ABRASF 2.03 da Prefeitura de Campinas.

    Fluxo: monta XML → assina (enveloped RSA-SHA1) → envolve em LoteRps
           → chama RecepcionarLoteRpsSincrono → parseia resposta.

    NOTA: Nomes dos parâmetros SOAP e namespace exato devem ser validados
    contra o WSDL de homologação antes do uso em produção.
    """

    def __init__(self, ambiente: str = "producao") -> None:
        if ambiente not in _WSDL:
            raise ValueError(f"ambiente deve ser 'producao' ou 'homologacao', não {ambiente!r}")
        self.wsdl = _WSDL[ambiente]

    # ------------------------------------------------------------------ #
    # Interface pública                                                    #
    # ------------------------------------------------------------------ #

    def emitir(self, req: NfseRequest) -> NfseResult:
        inf_assinado = assinar_xml(
            self._montar_inf_rps(req),
            req.prestador.cert_path,
            req.prestador.cert_senha,
            reference_id="rps1",
        )
        resp_str = self._chamar_soap(
            "RecepcionarLoteRpsSincrono",
            req.prestador.cert_path,
            req.prestador.cert_senha,
            nfseCabecMsg=self._cabecalho(),
            nfseDadosMsg=self._montar_envelope(inf_assinado, req),
        )
        return self._parsear_resposta(resp_str, req.numero_rps, req.competencia)

    def cancelar(
        self,
        numero_nota: str,
        prestador: PrestadorNfse,
        codigo_cancelamento: str = "2",
    ) -> None:
        pedido_assinado = assinar_xml(
            self._montar_pedido_cancelamento(numero_nota, prestador, codigo_cancelamento),
            prestador.cert_path,
            prestador.cert_senha,
            reference_id="cancelamento1",
        )
        resp_str = self._chamar_soap(
            "CancelarNfse",
            prestador.cert_path,
            prestador.cert_senha,
            nfseCabecMsg=self._cabecalho(),
            nfseDadosMsg=pedido_assinado.decode(),
        )
        resp_xml = self._resposta_para_xml(resp_str)
        self._levantar_se_erro(resp_xml, _NS)

    # ------------------------------------------------------------------ #
    # XML builders                                                         #
    # ------------------------------------------------------------------ #

    def _montar_inf_rps(self, req: NfseRequest) -> bytes:
        ns = _NS
        sub = self._sub
        data_emissao = req.data_emissao or date.today().isoformat()

        inf = etree.Element(f"{{{ns}}}InfDeclaracaoPrestacaoServico", attrib={"Id": "rps1"})

        rps_el = sub(inf, ns, "Rps")
        id_rps = sub(rps_el, ns, "IdentificacaoRps")
        sub(id_rps, ns, "Numero").text = str(req.numero_rps)
        sub(id_rps, ns, "Serie").text = req.serie_rps
        sub(id_rps, ns, "Tipo").text = req.tipo_rps
        sub(rps_el, ns, "DataEmissao").text = data_emissao
        sub(rps_el, ns, "NaturezaOperacao").text = str(req.natureza_operacao)
        if req.regime_tributacao:
            sub(rps_el, ns, "RegimeEspecialTributacao").text = str(req.regime_tributacao)
        sub(rps_el, ns, "OptanteSimplesNacional").text = "1" if req.optante_simples else "2"
        sub(rps_el, ns, "IncentivadorCultural").text = "2"
        sub(rps_el, ns, "Status").text = "1"

        sub(inf, ns, "Competencia").text = f"{req.competencia}-01T00:00:00"

        servico = sub(inf, ns, "Servico")
        valores = sub(servico, ns, "Valores")
        sub(valores, ns, "ValorServicos").text = f"{req.valor_servico:.2f}"
        sub(valores, ns, "ValorDeducoes").text = f"{req.deducoes:.2f}"
        sub(valores, ns, "IssRetido").text = "1" if req.iss_retido else "2"
        if req.valor_iss is not None:
            sub(valores, ns, "ValorIss").text = f"{req.valor_iss:.2f}"
        sub(servico, ns, "ItemListaServico").text = req.codigo_servico
        if req.codigo_cnae:
            sub(servico, ns, "CodigoCnae").text = req.codigo_cnae
        sub(servico, ns, "Discriminacao").text = req.discriminacao
        sub(servico, ns, "CodigoMunicipio").text = _IBGE_CAMPINAS
        sub(servico, ns, "ExigibilidadeISS").text = "1"
        sub(servico, ns, "MunicipioIncidencia").text = _IBGE_CAMPINAS

        prestador_el = sub(inf, ns, "Prestador")
        self._cnpj_element(prestador_el, ns, req.prestador.cnpj)
        sub(prestador_el, ns, "InscricaoMunicipal").text = req.prestador.inscricao_municipal

        tomador_el = sub(inf, ns, "Tomador")
        id_tom = sub(tomador_el, ns, "IdentificacaoTomador")
        cpf_cnpj_t = sub(id_tom, ns, "CpfCnpj")
        if req.tomador.cnpj:
            sub(cpf_cnpj_t, ns, "Cnpj").text = req.tomador.cnpj
        elif req.tomador.cpf:
            sub(cpf_cnpj_t, ns, "Cpf").text = req.tomador.cpf
        if req.tomador.inscricao_municipal:
            sub(id_tom, ns, "InscricaoMunicipal").text = req.tomador.inscricao_municipal
        sub(tomador_el, ns, "RazaoSocial").text = req.tomador.razao_social
        if req.tomador.logradouro:
            end = sub(tomador_el, ns, "Endereco")
            sub(end, ns, "Logradouro").text = req.tomador.logradouro
            if req.tomador.numero:
                sub(end, ns, "Numero").text = req.tomador.numero
            if req.tomador.complemento:
                sub(end, ns, "Complemento").text = req.tomador.complemento
            if req.tomador.bairro:
                sub(end, ns, "Bairro").text = req.tomador.bairro
            if req.tomador.municipio_ibge:
                sub(end, ns, "CodigoMunicipio").text = req.tomador.municipio_ibge
            if req.tomador.uf:
                sub(end, ns, "Uf").text = req.tomador.uf
            if req.tomador.cep:
                sub(end, ns, "Cep").text = req.tomador.cep
        if req.tomador.email:
            contato = sub(tomador_el, ns, "Contato")
            sub(contato, ns, "Email").text = req.tomador.email

        return etree.tostring(inf, encoding="unicode").encode()

    def _montar_envelope(self, inf_assinado: bytes, req: NfseRequest) -> str:
        ns = _NS
        sub = self._sub
        root = etree.Element(f"{{{ns}}}EnviarLoteRpsSincronoEnvio")
        lote = sub(root, ns, "LoteRps", versao="2.03")
        sub(lote, ns, "NumeroLote").text = "1"
        prestador_el = sub(lote, ns, "Prestador")
        self._cnpj_element(prestador_el, ns, req.prestador.cnpj)
        sub(prestador_el, ns, "InscricaoMunicipal").text = req.prestador.inscricao_municipal
        sub(lote, ns, "QuantidadeRps").text = "1"
        lista = sub(lote, ns, "ListaRps")
        sub(lista, ns, "Rps").append(etree.fromstring(inf_assinado))
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
        self, numero_nota: str, prestador: PrestadorNfse, codigo_cancelamento: str
    ) -> bytes:
        ns = _NS
        sub = self._sub
        inf = etree.Element(f"{{{ns}}}InfPedidoCancelamento", attrib={"Id": "cancelamento1"})
        id_nfse = sub(inf, ns, "IdentificacaoNfse")
        sub(id_nfse, ns, "Numero").text = numero_nota
        self._cnpj_element(id_nfse, ns, prestador.cnpj)
        sub(id_nfse, ns, "InscricaoMunicipal").text = prestador.inscricao_municipal
        sub(id_nfse, ns, "CodigoMunicipio").text = _IBGE_CAMPINAS
        sub(inf, ns, "CodigoCancelamento").text = codigo_cancelamento
        return etree.tostring(inf, encoding="unicode").encode()

    # ------------------------------------------------------------------ #
    # Parser de resposta                                                   #
    # ------------------------------------------------------------------ #

    def _parsear_resposta(self, resp_str: str, numero_rps: str, competencia: str) -> NfseResult:
        resp_xml = self._resposta_para_xml(resp_str)
        self._levantar_se_erro(resp_xml, _NS)

        ns = _NS
        numero = resp_xml.findtext(f".//{{{ns}}}Numero") or ""
        if not numero:
            raise RuntimeError("Resposta do webservice não contém número da NFS-e.")

        return NfseResult(
            numero_nota=numero,
            codigo_verificacao=resp_xml.findtext(f".//{{{ns}}}CodigoVerificacao") or "",
            competencia=competencia,
            xml_retorno=resp_str.encode(),
            link_consulta=resp_xml.findtext(f".//{{{ns}}}LinkConsultaNfse") or "",
            numero_rps_origem=str(numero_rps),
        )
