"""Interface abstrata para drivers de emissão de NFS-e."""

from __future__ import annotations

from abc import ABC, abstractmethod

from conta_tools_shared.domain.nfse import NfseRequest, NfseResult, PrestadorNfse


class NfseDriver(ABC):
    @abstractmethod
    def emitir(self, req: NfseRequest) -> NfseResult:
        """Emite a NFS-e e retorna o resultado com número e PDF."""
        ...

    @abstractmethod
    def cancelar(self, numero_nota: str, prestador: PrestadorNfse, codigo_cancelamento: str = "2") -> None:
        """
        Cancela uma NFS-e já emitida.
        codigo_cancelamento: 1=Erro na emissão, 2=Serviço não prestado, 4=Duplicidade.
        """
        ...
