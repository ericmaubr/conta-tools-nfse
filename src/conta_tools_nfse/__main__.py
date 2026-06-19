"""Entry point: python -m conta_tools_nfse <municipio> <subcomando> ..."""

from __future__ import annotations

import sys

from conta_tools_shared.version import handle_version_flags


def main() -> None:
    code = handle_version_flags("conta-tools-nfse", "conta_tools_nfse")
    if code is not None:
        sys.exit(code)

    argv = sys.argv[1:]
    if not argv:
        _uso()
        sys.exit(1)

    municipio = argv[0].lower()
    resto = argv[1:]

    if municipio == "campinas":
        from conta_tools_nfse.cli.campinas import main_campinas

        sys.exit(main_campinas(resto))
    else:
        print(f"Município não suportado: {municipio}")
        print("Disponíveis: campinas")
        sys.exit(1)


def _uso() -> None:
    print("Uso: python -m conta_tools_nfse <municipio> <subcomando> [opcoes]")
    print()
    print("Municípios:")
    print("  campinas    Prefeitura de Campinas (ABRASF 2.03)")
    print()
    print("Subcomandos:")
    print("  template    Gera planilha Excel de exemplo")
    print("  emitir      Emite notas a partir da planilha")
    print()
    print("Flags globais: --version, --about")


if __name__ == "__main__":
    main()
