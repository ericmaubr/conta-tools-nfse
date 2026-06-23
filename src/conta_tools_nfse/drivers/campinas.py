"""Driver de emissão de NFS-e para a Prefeitura de Campinas (ABRASF 2.03)."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from lxml import etree

from conta_tools_shared.domain.nfse import NfseRequest, NfseResult, PrestadorNfse
from conta_tools_shared.nfse.signer import assinar_consulta, assinar_elemento, assinar_xml
from conta_tools_shared.nfse.transport import soap_transport

from conta_tools_nfse.drivers.base import NfseDriverBase

_NS = "http://www.abrasf.org.br/nfse.xsd"
_NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_NS_TNS = "http://nfse.abrasf.org.br"
_IBGE_CAMPINAS = "3509502"

_WSDL = {
    "producao":    "https://novanfse.campinas.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl",
    "homologacao": "https://homol-rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl",
}


class CampinasDriver(NfseDriverBase):
    """
    Emite NFS-e via webservice ABRASF 2.03 da Prefeitura de Campinas.

    Fluxo: monta XML (sem namespace — WSDL elementFormDefault=unqualified) →
           assina LoteRps (Signature como irmão) → monta SOAP com EnviarLoteRpsSincronoEnvio
           embedded como elemento XML real (não como string em nfseDadosMsg) →
           envia com mTLS → parseia resposta.

    Conforme WSDL Campinas (document/literal, elementFormDefault=unqualified):
        <tns:RecepcionarLoteRpsSincrono>
            <EnviarLoteRpsSincronoEnvio>     ← sem namespace (unqualified)
                <LoteRps Id="lote1">          ← sem namespace, ASSINADO
                <Signature>                   ← irmão de LoteRps (XMLDSig ns)
            </EnviarLoteRpsSincronoEnvio>
        </tns:RecepcionarLoteRpsSincrono>
    """

    def __init__(self, ambiente: str = "producao") -> None:
        if ambiente not in _WSDL:
            raise ValueError(f"ambiente deve ser 'producao' ou 'homologacao', não {ambiente!r}")
        self.wsdl = _WSDL[ambiente]

    # ------------------------------------------------------------------ #
    # Interface pública                                                    #
    # ------------------------------------------------------------------ #

    def emitir(self, req: NfseRequest) -> NfseResult:
        # Monta XML sem namespace (WSDL: elementFormDefault=unqualified)
        ##print("Montando XML de envio (sem namespace, conforme WSDL de Campinas).")
        ##print(req)
        ##print("-" * 40)
        envio_el = self._montar_envio_el(req, ns="")
        lote_el = envio_el.find("LoteRps")

        # Assina LoteRps — Signature fica como irmão em EnviarLoteRpsSincronoEnvio
        assinar_elemento(
            envio_el,
            lote_el,
            req.prestador.cert_path,
            req.prestador.cert_senha,
            reference_id="lote1",
        )

        # Embute EnviarLoteRpsSincronoEnvio diretamente no SOAP body (não como texto)
        soap_bytes = self._montar_soap_sincrono(envio_el)
        resp_str = self._enviar_soap_sincrono(soap_bytes, req.prestador.cert_path, req.prestador.cert_senha)
        return self._parsear_resposta(resp_str, req)

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
    # Consultas                                                            #
    # ------------------------------------------------------------------ #

    def consultar_nfse_periodo(
        self,
        prestador: PrestadorNfse,
        data_ini: str,
        data_fim: str,
    ) -> dict[str, tuple[str, str, str]]:
        """
        Retorna {serie: (ultimo_rps, numero_nfse, data_emissao)} para o período.

        Varre todas as páginas de ConsultarNfseServicoPrestado e guarda o maior
        número de RPS por série. Retorna dict vazio se não houver NFS-e no período.
        """
        por_serie: dict[str, tuple[int, str, str, str]] = {}
        pagina = 1

        while True:
            envio = etree.Element("ConsultarNfseServicoPrestadoEnvio")
            p_el = etree.SubElement(envio, "Prestador")
            cc = etree.SubElement(p_el, "CpfCnpj")
            etree.SubElement(cc, "Cnpj").text = prestador.cnpj
            etree.SubElement(p_el, "InscricaoMunicipal").text = prestador.inscricao_municipal
            periodo = etree.SubElement(envio, "PeriodoEmissao")
            etree.SubElement(periodo, "DataInicial").text = data_ini
            etree.SubElement(periodo, "DataFinal").text = data_fim
            etree.SubElement(envio, "Pagina").text = str(pagina)

            assinar_consulta(envio, prestador.cert_path, prestador.cert_senha)

            soap_bytes = self._montar_soap_op(envio, "ConsultarNfseServicoPrestado")
            resp_str = self._enviar_soap_sincrono(soap_bytes, prestador.cert_path, prestador.cert_senha)
            resp_xml = self._resposta_para_xml(resp_str)

            self._levantar_se_erro(resp_xml, _NS)
            self._levantar_se_erro(resp_xml, "")

            notas = resp_xml.findall(".//InfNfse")
            if not notas:
                break

            for nota in notas:
                def _f(tag: str) -> str:
                    return nota.findtext(f"{{{_NS}}}{tag}") or nota.findtext(tag) or ""

                num_nfse = _f("Numero")
                data_emissao = _f("DataEmissao")[:10]

                rps_el = (
                    nota.find(f".//{{{_NS}}}IdentificacaoRps")
                    or nota.find(".//IdentificacaoRps")
                )
                if rps_el is None:
                    continue

                def _r(tag: str) -> str:
                    return rps_el.findtext(f"{{{_NS}}}{tag}") or rps_el.findtext(tag) or ""

                serie = _r("Serie")
                num_rps = _r("Numero")
                if not serie or not num_rps:
                    continue

                try:
                    num_rps_int = int(num_rps)
                except ValueError:
                    num_rps_int = 0

                if serie not in por_serie or num_rps_int > por_serie[serie][0]:
                    por_serie[serie] = (num_rps_int, num_rps, num_nfse, data_emissao)

            if len(notas) < 50:
                break
            pagina += 1

        return {
            serie: (rps, nfse, data)
            for serie, (_, rps, nfse, data) in por_serie.items()
        }

    # ------------------------------------------------------------------ #
    # SOAP direto (Campinas: document/literal, sem nfseDadosMsg)          #
    # ------------------------------------------------------------------ #

    def _montar_soap_op(self, envio_el: etree._Element, operacao: str) -> bytes:
        """Monta SOAP 1.1 document/literal genérico (consultas e outros ops)."""
        nsmap = {"soapenv": _NS_SOAP, "tns": _NS_TNS}
        env = etree.Element(f"{{{_NS_SOAP}}}Envelope", nsmap=nsmap)
        etree.SubElement(env, f"{{{_NS_SOAP}}}Header")
        body = etree.SubElement(env, f"{{{_NS_SOAP}}}Body")
        op = etree.SubElement(body, f"{{{_NS_TNS}}}{operacao}")
        op.append(envio_el)
        return etree.tostring(env, xml_declaration=True, encoding="UTF-8")

    def _montar_soap_sincrono(self, envio_el: etree._Element) -> bytes:
        """
        Monta SOAP 1.1 com EnviarLoteRpsSincronoEnvio embedded como XML real.

        O WSDL de Campinas (document/literal) não usa nfseDadosMsg — o parâmetro
        EnviarLoteRpsSincronoEnvio é filho direto de tns:RecepcionarLoteRpsSincrono.
        """
        nsmap = {"soapenv": _NS_SOAP, "tns": _NS_TNS}
        env = etree.Element(f"{{{_NS_SOAP}}}Envelope", nsmap=nsmap)
        etree.SubElement(env, f"{{{_NS_SOAP}}}Header")
        body = etree.SubElement(env, f"{{{_NS_SOAP}}}Body")
        op = etree.SubElement(body, f"{{{_NS_TNS}}}RecepcionarLoteRpsSincrono")
        op.append(envio_el)
        return etree.tostring(env, xml_declaration=True, encoding="UTF-8")

    def _enviar_soap_sincrono(self, soap_bytes: bytes, cert_path: Path, cert_senha: str) -> str:
        """Envia SOAP bytes pré-montados via mTLS e extrai conteúdo do Body."""
        dbg = os.environ.get("NFSE_DEBUG_SOAP")
        if dbg:
            with open(os.path.join(dbg, "soap_request_RecepcionarLoteRpsSincrono.xml"), "wb") as f:
                f.write(soap_bytes)

        parts = urlsplit(self.wsdl)
        endpoint = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

        with soap_transport(cert_path, cert_senha) as session:
            resp = session.post(
                endpoint,
                data=soap_bytes,
                headers={"Content-Type": "text/xml;charset=UTF-8", "SOAPAction": '""'},
                timeout=60,
            )

        if dbg:
            with open(os.path.join(dbg, "soap_response_RecepcionarLoteRpsSincrono.xml"), "wb") as f:
                f.write(resp.content)

        resp_root = etree.fromstring(resp.content)
        body = resp_root.find(f"{{{_NS_SOAP}}}Body")
        if body is None or len(body) == 0:
            return resp.text

        first = body[0]

        # SOAP Fault
        if "Fault" in first.tag:
            faultstring = (
                first.findtext("faultstring")
                or first.findtext(f"{{{_NS_SOAP}}}faultstring")
                or "SOAP Fault"
            )
            raise RuntimeError(f"SOAP Fault: {faultstring}")

        # Documento literal: filho direto pode ser o XML de resposta
        text = (first.text or "").strip()
        if text:
            return text
        for child in first:
            t = (child.text or "").strip()
            if t:
                return t
            # Document/literal: retorna o elemento filho completo, não só seu primeiro neto
            return etree.tostring(child, encoding="unicode")
        return etree.tostring(first, encoding="unicode")

    # ------------------------------------------------------------------ #
    # XML builders                                                         #
    # ------------------------------------------------------------------ #

    def _montar_inf_rps(
        self, parent_el: etree._Element, req: NfseRequest, ns: str = _NS
    ) -> etree._Element:
        """
        Cria InfDeclaracaoPrestacaoServico como filho direto de parent_el.

        ns: namespace a usar nos elementos. Passe "" para elementos unqualified
            (necessário para Campinas, que usa elementFormDefault=unqualified).
        """
        sub = self._sub
        data_emissao = req.data_emissao or date.today().isoformat()

        inf = sub(parent_el, ns, "InfDeclaracaoPrestacaoServico")

        rps_inner = sub(inf, ns, "Rps")
        id_rps = sub(rps_inner, ns, "IdentificacaoRps")
        sub(id_rps, ns, "Numero").text = str(req.numero_rps)
        sub(id_rps, ns, "Serie").text = req.serie_rps
        sub(id_rps, ns, "Tipo").text = req.tipo_rps
        sub(rps_inner, ns, "DataEmissao").text = data_emissao
        sub(rps_inner, ns, "Status").text = "1"

        sub(inf, ns, "Competencia").text = f"{req.competencia}-01"

        servico = sub(inf, ns, "Servico")
        valores = sub(servico, ns, "Valores")
        sub(valores, ns, "ValorServicos").text = f"{req.valor_servico:.2f}"
        if req.deducoes:
            sub(valores, ns, "ValorDeducoes").text = f"{req.deducoes:.2f}"
        if req.valor_pis:
            sub(valores, ns, "ValorPis").text = f"{req.valor_pis:.2f}"
        if req.valor_cofins:
            sub(valores, ns, "ValorCofins").text = f"{req.valor_cofins:.2f}"
        if req.valor_inss:
            sub(valores, ns, "ValorInss").text = f"{req.valor_inss:.2f}"
        if req.valor_ir:
            sub(valores, ns, "ValorIr").text = f"{req.valor_ir:.2f}"
        if req.valor_csll:
            sub(valores, ns, "ValorCsll").text = f"{req.valor_csll:.2f}"
        if req.valor_iss is not None:
            sub(valores, ns, "ValorIss").text = f"{req.valor_iss:.2f}"
        if req.valor_outras_retencoes:
            sub(valores, ns, "OutrasRetencoes").text = f"{req.valor_outras_retencoes:.2f}"
        sub(servico, ns, "IssRetido").text = "1" if req.iss_retido else "2"
        if req.codigo_servico:
            sub(servico, ns, "ItemListaServico").text = req.codigo_servico
        if req.codigo_cnae:
            # Campinas usa CNAE de 9 dígitos (ex: 692060100). O padrão ABRASF é 7.
            # Normaliza: remove não-dígitos e, se 7 dígitos, adiciona "00" no final.
            cnae = "".join(c for c in req.codigo_cnae if c.isdigit())
            if len(cnae) == 7:
                cnae += "00"
            sub(servico, ns, "CodigoCnae").text = cnae
        if req.codigo_tributacao_municipio:
            sub(servico, ns, "CodigoTributacaoMunicipio").text = req.codigo_tributacao_municipio
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
            sub(end, ns, "Endereco").text = req.tomador.logradouro
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

        if req.regime_tributacao:
            sub(inf, ns, "RegimeEspecialTributacao").text = str(req.regime_tributacao)
        sub(inf, ns, "OptanteSimplesNacional").text = "1" if req.optante_simples else "2"
        sub(inf, ns, "IncentivoFiscal").text = "2"

        return inf

    def _montar_envio_el(self, req: NfseRequest, ns: str = _NS) -> etree._Element:
        """
        Retorna EnviarLoteRpsSincronoEnvio SEM assinatura.

        ns: namespace dos elementos. Campinas: passe "" (elementFormDefault=unqualified).
        """
        sub = self._sub
        if ns:
            root = etree.Element(f"{{{ns}}}EnviarLoteRpsSincronoEnvio", nsmap={None: ns})
        else:
            root = etree.Element("EnviarLoteRpsSincronoEnvio")
        lote = sub(root, ns, "LoteRps", versao="2.03", Id="lote1")
        sub(lote, ns, "NumeroLote").text = str(req.numero_rps)
        self._cnpj_element(lote, ns, req.prestador.cnpj)
        sub(lote, ns, "InscricaoMunicipal").text = req.prestador.inscricao_municipal
        sub(lote, ns, "QuantidadeRps").text = "1"
        lista = sub(lote, ns, "ListaRps")
        outer_rps = sub(lista, ns, "Rps")
        self._montar_inf_rps(outer_rps, req, ns=ns)
        return root

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

    def _parsear_resposta(self, resp_str: str, req: NfseRequest) -> NfseResult:
        resp_xml = self._resposta_para_xml(resp_str)

        # Verifica erros: tenta com namespace ABRASF e sem namespace
        self._levantar_se_erro(resp_xml, _NS)
        self._levantar_se_erro(resp_xml, "")

        def _find(tag: str) -> str:
            return (
                resp_xml.findtext(f".//{{{_NS}}}{tag}")
                or resp_xml.findtext(f".//{tag}")
                or ""
            )

        numero = _find("Numero")
        if not numero:
            raise RuntimeError("Resposta do webservice não contém número da NFS-e.")

        cod_verif = _find("CodigoVerificacao")

        return NfseResult(
            numero_nota=numero,
            codigo_verificacao=cod_verif,
            competencia=req.competencia,
            xml_retorno=resp_str.encode(),
            link_consulta=self._link_consulta(req, numero, cod_verif),
            numero_rps_origem=str(req.numero_rps),
        )

    def _link_consulta(self, req: NfseRequest, numero: str, codigo_verificacao: str) -> str:
        """Constrói a URL de consulta/impressão da NFS-e no portal de Campinas.

        Campinas não retorna LinkConsultaNfse na resposta SOAP; o link é construído
        com base no padrão REST do portal (mesmo padrão usado pela lib nfse-campinas).
        """
        parts = urlsplit(self.wsdl)
        base = parts.scheme + "://" + parts.netloc
        cnpj = req.prestador.cnpj
        im = req.prestador.inscricao_municipal
        return (
            f"{base}/notafiscal-ws/servico/notafiscal/autenticacao/"
            f"cpfCnpj/{cnpj}/inscricaoMunicipal/{im}/"
            f"numeroNota/{numero}/codigoVerificacao/{codigo_verificacao}"
        )
