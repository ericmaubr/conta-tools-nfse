"""Entry point: python -m conta_tools_nfse <municipio|serve> <subcomando> ..."""

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

    cmd = argv[0].lower()
    resto = argv[1:]

    if cmd == "campinas":
        from conta_tools_nfse.cli.campinas import main_campinas

        sys.exit(main_campinas(resto))
    elif cmd in ("sao_paulo", "sp"):
        from conta_tools_nfse.cli.sao_paulo import main_sao_paulo

        sys.exit(main_sao_paulo(resto))
    elif cmd == "serve":
        sys.exit(_cmd_serve(resto))
    else:
        print(f"Comando não reconhecido: {cmd}")
        print("Disponíveis: campinas, sao_paulo, serve")
        sys.exit(1)


def _cmd_serve(argv: list[str]) -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="conta-tools-nfse serve",
        description="Inicia o servidor REST para emissão de NFS-e via interface web ou MCP.",
    )
    parser.add_argument(
        "--conf",
        type=Path,
        default=Path("api.conf"),
        metavar="CONF",
        help="Arquivo de configuração da API (default: api.conf)",
    )
    args = parser.parse_args(argv)

    try:
        from conta_tools_nfse.api.conf import carregar_api_conf
        api_conf = carregar_api_conf(args.conf)
    except Exception as e:
        print(f"Erro ao ler {args.conf}: {e}", file=sys.stderr)
        return 1

    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn não instalado. Execute: pip install 'conta-tools-nfse[api]'",
            file=sys.stderr,
        )
        return 1

    from conta_tools_nfse.api.app import create_app
    app = create_app(api_conf)

    print(f"ContaTools NFS-e API — http://{api_conf.host}:{api_conf.port}")
    print(f"Prestadores: {api_conf.prestadores_dir}")
    print("Pressione Ctrl+C para parar.")

    uvicorn.run(app, host=api_conf.host, port=api_conf.port, log_level="warning")
    return 0


def _uso() -> None:
    print("Uso: python -m conta_tools_nfse <municipio|serve> [opcoes]")
    print()
    print("Municípios:")
    print("  campinas    Prefeitura de Campinas (ABRASF 2.03)")
    print("  sao_paulo   Prefeitura de São Paulo (formato SP)")
    print()
    print("Subcomandos (por município):")
    print("  template    Gera planilha Excel de exemplo")
    print("    --saida XLSX        Caminho de saída")
    print()
    print("  emitir      Emite notas a partir da planilha")
    print("    --planilha XLSX     Planilha de entrada (obrigatório)")
    print("    --conf CONF         Arquivo .conf do prestador (obrigatório)")
    print("    --saida XLSX        Planilha de saída (default: <planilha>_resultado.xlsx)")
    print()
    print("  ultimo-rps  Consulta o último RPS emitido por série")
    print("    --conf CONF         Arquivo .conf do prestador (obrigatório)")
    print("    --meses N           Máximo de meses para retroagir (default: 24)")
    print()
    print("Servidor REST:")
    print("  serve       Inicia a API web para emissão via interface gráfica ou MCP")
    print("    --conf CONF         Arquivo api.conf (default: api.conf)")
    print()
    print("Flags globais: --version, --about, --help/-h")


if __name__ == "__main__":
    main()
