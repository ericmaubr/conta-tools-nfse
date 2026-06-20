"""Entry point: python -m conta_tools_nfse <municipio> <subcomando> ..."""

from __future__ import annotations

import sys

from conta_tools_shared.version import handle_version_flags


def main() -> None:
    code = handle_version_flags("conta-tools-nfse", "conta_tools_nfse")
    if code is not None:
        sys.exit(code)

    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        _uso()
        sys.exit(0 if argv else 1)

    municipio = argv[0].lower()
    resto = argv[1:]

    if municipio == "campinas":
        from conta_tools_nfse.cli.campinas import main_campinas

        sys.exit(main_campinas(resto))
    elif municipio in ("sao_paulo", "sp"):
        from conta_tools_nfse.cli.sao_paulo import main_sao_paulo

        sys.exit(main_sao_paulo(resto))
    else:
        print(f"Município não suportado: {municipio}")
        print("Disponíveis: campinas, sao_paulo")
        sys.exit(1)


def _uso() -> None:
    print("Uso: python -m conta_tools_nfse <municipio> <subcomando> [opcoes]")
    print()
    print("Municípios:")
    print("  campinas    Prefeitura de Campinas (ABRASF 2.03)")
    print("  sao_paulo   Prefeitura de São Paulo (formato SP)")
    print()
    print("Subcomandos:")
    print("  template    Gera planilha Excel de exemplo")
    print("    --saida XLSX        Caminho de saída (default: template_nfse_<municipio>.xlsx)")
    print()
    print("  emitir      Emite notas a partir da planilha")
    print("    --planilha XLSX     Planilha de entrada (obrigatório)")
    print("    --conf CONF         Arquivo .conf do prestador (obrigatório)")
    print("    --saida XLSX        Planilha de saída (default: <planilha>_resultado.xlsx)")
    print()
    print("Flags globais: --version, --about, --help/-h")


if __name__ == "__main__":
    main()
