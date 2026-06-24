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
    elif cmd == "mcp-server":
        sys.exit(_cmd_mcp_server(resto))
    else:
        print(f"Comando não reconhecido: {cmd}")
        print("Disponíveis: campinas, sao_paulo, serve, mcp-server")
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
    from conta_tools_nfse.conf import carregar_conf
    app = create_app(api_conf)

    print(f"ContaTools NFS-e API — http://{api_conf.host}:{api_conf.port}")
    print(f"Prestadores: {api_conf.prestadores_dir}")

    confs = sorted(api_conf.prestadores_dir.glob("*.conf"))
    if not confs:
        print("  (nenhum arquivo .conf encontrado)")
    else:
        ok = []
        falhas = []
        for p in confs:
            try:
                conf = carregar_conf(p)
                nome = conf.nome or p.stem
                ok.append(f"  + {nome}  ({p.stem})")
            except Exception as e:
                falhas.append(f"  ! {p.name}: {e}")
        for linha in ok:
            print(linha)
        for linha in falhas:
            print(linha, file=sys.stderr)

    from conta_tools_nfse.chat import _LOG_FILE
    print(f"Log do agente:  {_LOG_FILE}")
    print(f"  monitorar:    Get-Content '{_LOG_FILE}' -Wait -Tail 50 -Encoding utf8")
    print("Pressione Ctrl+C para parar.")

    uvicorn.run(app, host=api_conf.host, port=api_conf.port, log_level="warning")
    return 0


def _cmd_mcp_server(argv: list[str]) -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="conta-tools-nfse mcp-server",
        description="Inicia o servidor MCP para emissão de NFS-e via linguagem natural.",
    )
    parser.add_argument(
        "--conf",
        type=Path,
        default=Path("mcp.conf"),
        metavar="CONF",
        help="Arquivo de configuração do MCP (default: mcp.conf)",
    )
    args = parser.parse_args(argv)

    try:
        from conta_tools_nfse.mcp.conf import carregar_mcp_conf
        mcp_conf = carregar_mcp_conf(args.conf)
    except Exception as e:
        print(f"Erro ao ler {args.conf}: {e}", file=sys.stderr)
        return 1

    try:
        from conta_tools_nfse.mcp.server import inicializar, run
    except ImportError:
        print(
            "mcp não instalado. Execute: pip install 'conta-tools-nfse[mcp]'",
            file=sys.stderr,
        )
        return 1

    inicializar(mcp_conf.api_url, mcp_conf.bearer_token)
    run()
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
    print("Servidor MCP (linguagem natural):")
    print("  mcp-server  Inicia o servidor MCP para uso com Claude Desktop / Claude Code")
    print("    --conf CONF         Arquivo mcp.conf (default: mcp.conf)")
    print()
    print("Flags globais: --version, --about, --help/-h")


if __name__ == "__main__":
    main()
