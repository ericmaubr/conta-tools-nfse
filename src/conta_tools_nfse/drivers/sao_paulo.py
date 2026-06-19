"""Driver de emissão de NFS-e para a Prefeitura de São Paulo."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from lxml import etree

from conta_tools_shared.domain.nfse import NfseRequest, NfseResult, PrestadorNfse
from conta_tools_shared.nfse.signer import assinar_rps_sp

from conta_tools_nfse.drivers.base import NfseDriverBase

_NS = "http://www.prefeitura.sp.gov.br/nfe"
_IBGE_SP = "3550308"

_WSDL = {
    "producao":    "https://nfews.prefeitura.sp.gov.br/lotenfe.asmx?WSDL",
    "homologacao": "https://homologacao.prefeitura.sp.gov.br/lotenfe.asmx?WSDL",
}

_SERIE_RPS_SP = "RPS"


class SaoPauloDriver(NfseDriverBase):
    """
    Emite NFS-e via webservice da Prefeitura de São Paulo.

    Fluxo: monta XML → assina string (RSA-SHA1 Base64) → insere <Assinatura>
           → chama EnviarLoteRpsSincrono(VstrXMLlote) → parseia resposta.

    NOTA: Nomes dos parâmetros SOAP e formato exato devem ser validados
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
        xml_lote = self._montar_lote(req)
        resp_str = self._chamar_soap(
            "EnviarLoteRpsSincrono",
            req.prestador.cert_path,
            req.prestador.cert_senha,
            VstrXMLlote=xml_lote,
        )
        return self._parsear_resposta(resp_str, req.numero_rps, req.competencia)

    def cancelar(
        self,
        numero_nota: str,
        prestador: PrestadorNfse,
        codigo_cancelamento: str = "2",
    ) -> None:
        raise NotImplementedError(
            "Cancelamento SP requer o código de verificação da NFS-e. "
            "Use cancelar_com_verificacao(numero_nota, prestador, codigo_verificacao)."
        )

    def cancelar_com_verificacao(
        self,
        numero_nota: str,
        prestador: PrestadorNfse,
        codigo_verificacao: str,
        motivo: str = "Emitida com erro",
    ) -> None:
        xml_cancel = self._montar_cancelamento(
            numero_nota, prestador, codigo_verificacao, motivo
        )
        resp_str = self._chamar_soap(
            "CancelarNFe",
            prestador.cert_path,
            prestador.cert_senha,
            VstrXMLlote=xml_cancel,
        )
        resp_xml = self._resposta_para_xml(resp_str)
        sucesso = resp_xml.findtext(".//{*}Sucesso") or resp_xml.findtext(".//Sucesso") or ""
        if sucesso.lower() != "true":
            num_erro = resp_xml.findtext(".//{*}NumeroErro") or "?"
            msg_erro = resp_xml.findtext(".//{*}MensagemErro") or "Erro desconhecido"
            raise RuntimeError(f"Cancelamento SP retornou erro {num_erro}: {msg_erro}")

    # ------------------------------------------------------------------ #
    # XML builders                                                         #
    # ------------------------------------------------------------------ #

    def _montar_lote(self, req: NfseRequest) -> str:
        data_emissao = req.data_emissao or date.today().isoformat()
        ano, mes = int(req.competencia[:4]), int(req.competencia[5:7])
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        dt_inicio = f"{req.competencia}-01"
        dt_fim = f"{req.competencia}-{ultimo_dia:02d}"

        serie = _SERIE_RPS_SP
        trib = req.tributacao_rps or "T"
        val_serv = f"{req.valor_servico:.2f}"
        val_ded = f"{req.deducoes:.2f}"
        aliquota = req.aliquota_servicos if req.aliquota_servicos is not None else Decimal("0")
        cnpj_cpf_tom = req.tomador.cnpj or req.tomador.cpf or ""

        assinatura = assinar_rps_sp(
            inscricao_prestador=req.prestador.inscricao_municipal,
            serie_rps=serie,
            numero_rps=req.numero_rps,
            data_emissao=data_emissao,
            tributacao_rps=trib,
            status_rps="N",
            iss_retido=req.iss_retido,
            valor_servicos=val_serv,
            valor_deducoes=val_ded,
            codigo_servico=req.codigo_servico,
            cnpj_cpf_tomador=cnpj_cpf_tom,
            cert_path=req.prestador.cert_path,
            cert_senha=req.prestador.cert_senha,
        )

        sub = etree.SubElement

        # Root com namespace default; filhos sem namespace recebem xmlns="" automaticamente
        root = etree.Element("PedidoEnvioLoteRPS", nsmap={None: _NS})

        cab = sub(root, "Cabecalho", Versao="1")
        rem = sub(cab, "CPFCNPJRemetente")
        sub(rem, "CNPJ").text = req.prestador.cnpj
        sub(cab, "transacao").text = "true"
        sub(cab, "dtInicio").text = dt_inicio
        sub(cab, "dtFim").text = dt_fim
        sub(cab, "QtdRPS").text = "1"
        sub(cab, "ValorTotalServicos").text = val_serv
        sub(cab, "ValorTotalDeducoes").text = val_ded

        rps = sub(root, "RPS")
        sub(rps, "Assinatura").text = assinatura
        chave = sub(rps, "ChaveRPS")
        sub(chave, "InscricaoPrestador").text = req.prestador.inscricao_municipal
        sub(chave, "SerieRPS").text = serie
        sub(chave, "NumeroRPS").text = req.numero_rps
        sub(rps, "TipoRPS").text = "RPS"
        sub(rps, "DataEmissao").text = data_emissao
        sub(rps, "StatusRPS").text = "N"
        sub(rps, "TributacaoRPS").text = trib
        sub(rps, "ValorServicos").text = val_serv
        sub(rps, "ValorDeducoes").text = val_ded
        sub(rps, "ValorPIS").text = "0.00"
        sub(rps, "ValorCOFINS").text = "0.00"
        sub(rps, "ValorINSS").text = "0.00"
        sub(rps, "ValorIR").text = "0.00"
        sub(rps, "ValorCSLL").text = "0.00"
        sub(rps, "CodigoServico").text = req.codigo_servico.zfill(5)[:5]
        sub(rps, "AliquotaServicos").text = f"{aliquota:.4f}"
        sub(rps, "ISSRetido").text = "true" if req.iss_retido else "false"

        cpf_cnpj_tom = sub(rps, "CPFCNPJTomador")
        if req.tomador.cnpj:
            sub(cpf_cnpj_tom, "CNPJ").text = req.tomador.cnpj
        elif req.tomador.cpf:
            sub(cpf_cnpj_tom, "CPF").text = req.tomador.cpf

        sub(rps, "InscricaoMunicipalTomador").text = req.tomador.inscricao_municipal or "0"
        sub(rps, "RazaoSocialTomador").text = req.tomador.razao_social

        if req.tomador.logradouro:
            end = sub(rps, "EnderecoTomador")
            sub(end, "TipoLogradouro").text = ""
            sub(end, "Logradouro").text = req.tomador.logradouro
            sub(end, "NumeroEndereco").text = req.tomador.numero or "S/N"
            if req.tomador.complemento:
                sub(end, "ComplementoEndereco").text = req.tomador.complemento
            sub(end, "Bairro").text = req.tomador.bairro or ""
            sub(end, "Cidade").text = req.tomador.municipio_ibge or _IBGE_SP
            sub(end, "UF").text = req.tomador.uf or "SP"
            sub(end, "CEP").text = req.tomador.cep or ""

        if req.tomador.email:
            sub(rps, "EmailTomador").text = req.tomador.email

        sub(rps, "Discriminacao").text = req.discriminacao

        return etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode()

    def _montar_cancelamento(
        self,
        numero_nota: str,
        prestador: PrestadorNfse,
        codigo_verificacao: str,
        motivo: str,
    ) -> str:
        sub = etree.SubElement
        root = etree.Element("PedidoCancelamentoNFe", nsmap={None: _NS})

        cab = sub(root, "Cabecalho", Versao="1")
        rem = sub(cab, "CPFCNPJRemetente")
        sub(rem, "CNPJ").text = prestador.cnpj

        detalhe = sub(root, "Detalhe")
        chave = sub(detalhe, "ChaveNFe")
        sub(chave, "InscricaoPrestador").text = prestador.inscricao_municipal
        sub(chave, "NumeroNFe").text = numero_nota
        sub(chave, "CodigoVerificacao").text = codigo_verificacao
        sub(detalhe, "MotivoCancelamento").text = motivo

        return etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode()

    # ------------------------------------------------------------------ #
    # Parser de resposta                                                   #
    # ------------------------------------------------------------------ #

    def _parsear_resposta(
        self, resp_str: str, numero_rps: str, competencia: str
    ) -> NfseResult:
        resp_xml = self._resposta_para_xml(resp_str)

        # SP responde com <Sucesso>true/false</Sucesso> no cabeçalho
        sucesso = (
            resp_xml.findtext(".//{*}Sucesso")
            or resp_xml.findtext(".//Sucesso")
            or ""
        )
        if sucesso.lower() != "true":
            num_erro = (
                resp_xml.findtext(".//{*}NumeroErro")
                or resp_xml.findtext(".//NumeroErro")
                or "?"
            )
            msg_erro = (
                resp_xml.findtext(".//{*}MensagemErro")
                or resp_xml.findtext(".//MensagemErro")
                or "Erro desconhecido"
            )
            raise RuntimeError(f"Webservice SP retornou erro {num_erro}: {msg_erro}")

        numero = (
            resp_xml.findtext(".//{*}NumeroNFe")
            or resp_xml.findtext(".//NumeroNFe")
            or ""
        )
        if not numero:
            raise RuntimeError("Resposta do webservice SP não contém número da NFS-e.")

        return NfseResult(
            numero_nota=numero,
            codigo_verificacao=(
                resp_xml.findtext(".//{*}CodigoVerificacao")
                or resp_xml.findtext(".//CodigoVerificacao")
                or ""
            ),
            competencia=competencia,
            xml_retorno=resp_str.encode(),
            numero_rps_origem=str(numero_rps),
        )
