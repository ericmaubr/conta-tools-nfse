"""Classe base para drivers de emissão de NFS-e."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from lxml import etree

from conta_tools_shared.domain.nfse import NfseRequest, NfseResult, PrestadorNfse
from conta_tools_shared.nfse.transport import chamar_soap


class NfseDriver(ABC):
    @abstractmethod
    def emitir(self, req: NfseRequest) -> NfseResult: ...

    @abstractmethod
    def cancelar(self, numero_nota: str, prestador: PrestadorNfse, codigo_cancelamento: str = "2") -> None: ...


class NfseDriverBase(NfseDriver):
    """
    Base concreta com helpers compartilhados entre todos os drivers municipais.

    Subclasses devem implementar:
        emitir(), cancelar()
        e os métodos XML específicos do formato do município.
    """

    wsdl: str  # definido pela subclasse

    # ------------------------------------------------------------------ #
    # SOAP                                                                 #
    # ------------------------------------------------------------------ #

    def _chamar_soap(self, operacao: str, cert_path: Path, cert_senha: str, **params: str) -> str:
        return chamar_soap(
            wsdl=self.wsdl,
            operacao=operacao,
            cert_path=cert_path,
            cert_senha=cert_senha,
            **params,
        )

    # ------------------------------------------------------------------ #
    # Parsers de resposta genéricos                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resposta_para_xml(response: Any) -> etree._Element:
        raw = response if isinstance(response, (bytes, str)) else str(response)
        if isinstance(raw, str):
            raw = raw.encode()
        return etree.fromstring(raw)

    @staticmethod
    def _levantar_se_erro(
        resp_xml: etree._Element,
        ns: str,
        container_tag: str = "MensagemRetorno",
        codigo_tag: str = "Codigo",
        mensagem_tag: str = "Mensagem",
    ) -> None:
        """Levanta RuntimeError se o XML de resposta contiver mensagens de erro."""
        prefixo = f"{{{ns}}}" if ns else ""
        erros = resp_xml.findall(f".//{prefixo}{container_tag}")
        if erros:
            msgs = [
                f"{e.findtext(f'{prefixo}{codigo_tag}', '')}: "
                f"{e.findtext(f'{prefixo}{mensagem_tag}', '')}"
                for e in erros
            ]
            raise RuntimeError(f"Webservice retornou erro(s): {' | '.join(msgs)}")

    # ------------------------------------------------------------------ #
    # Helpers XML compartilhados                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _sub(
        parent: etree._Element, ns: str, tag: str, **attrib: str
    ) -> etree._Element:
        return etree.SubElement(parent, f"{{{ns}}}{tag}" if ns else tag, attrib=attrib)

    @staticmethod
    def _cnpj_element(parent: etree._Element, ns: str, cnpj: str) -> None:
        """Insere <CpfCnpj><Cnpj>...</Cnpj></CpfCnpj> (padrão ABRASF)."""
        sub = NfseDriverBase._sub
        cpf_cnpj = sub(parent, ns, "CpfCnpj")
        sub(cpf_cnpj, ns, "Cnpj").text = cnpj
