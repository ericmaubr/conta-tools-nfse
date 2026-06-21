# conta-tools-nfse — Emissão de NFS-e

## Antes de qualquer implementação

1. Leia `C:\dev\conta-tools-shared\CLAUDE.md` — regras globais do ecossistema
2. Leia `C:\dev\conta-tools-shared\CONTEXT.md` — o que o shared já oferece
3. Leia `C:\dev\conta-tools-nfse\CONTEXT.md` — o que este repo já tem implementado
4. Leia `C:\dev\conta-tools-shared\docs\IMPLEMENTATION-PLAN-whatsapp-nfse.md` — plano geral

---

## O que esta ferramenta faz

Emite NFS-e (Nota Fiscal de Serviços Eletrônica) via webservices SOAP das prefeituras,
a partir de uma planilha Excel com os dados das notas.

Municípios suportados:
- **Campinas**: padrão ABRASF 2.03
- **São Paulo**: padrão próprio SP, layout v2 com campos IBS/CBS (Reforma Tributária)

---

## CLI

```
# Gerar template da planilha
python -m conta_tools_nfse campinas template --saida template.xlsx

# Emitir notas da planilha
python -m conta_tools_nfse campinas emitir \
    --planilha notas.xlsx \
    --conf empresa.conf \
    [--saida resultado.xlsx]

# Consultar último RPS por série
python -m conta_tools_nfse campinas ultimo-rps --conf empresa.conf

# Iniciar servidor REST/web
python -m conta_tools_nfse serve --conf api.conf
```

### Regras do CLI

- **Senha do certificado**: sempre via env `CONTA_TOOLS_CERT_PASSWORD` — nunca como argumento CLI, nunca em log
- **CNPJ do prestador**: extraído automaticamente do certificado
- **Competência**: obrigatória na planilha (coluna `competencia`, formato `MM/AAAA`) — sem default
- **Ambiente default**: `producao` — precisa passar `--ambiente homologacao` explicitamente para testes

---

## Webservices

### Campinas — ABRASF 2.03
| Ambiente | URL |
|---|---|
| Produção | `https://novanfse.campinas.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl` |
| Homologação | `https://homol-rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl` |

- Binding: `document/literal`, `elementFormDefault="unqualified"` (todos os elementos sem namespace)
- Operação de emissão: `RecepcionarLoteRpsSincrono` — `EnviarLoteRpsSincronoEnvio` embutido como XML real no SOAP body
- Operações de consulta: mesma estrutura; assinadas com `assinar_consulta()` (`Reference URI=""`)
- Namespace XML: `http://www.abrasf.org.br/nfse.xsd`
- Código IBGE Campinas: `3509502`
- Quirks críticos: CNAE 9 dígitos, `optante_simples` deve bater com cadastro IMA, link de consulta construído programaticamente
- Contrato completo: [`docs/DRIVERS.md`](docs/DRIVERS.md)

### São Paulo — Layout v2 (pendente implementação)
| Ambiente | URL |
|---|---|
| Produção síncrono | `https://nfews.prefeitura.sp.gov.br/lotenfe.asmx?WSDL` |

---

## Estrutura dos módulos

```
src/conta_tools_nfse/
  drivers/
    base.py        # NfseDriver (ABC): emitir(), cancelar()
    campinas.py    # CampinasDriver — ABRASF 2.03
    sao_paulo.py   # SaoPauloDriver — layout v2 (futuro)
  excel/
    columns.py     # definição das colunas (compartilhada entre template e reader)
    template.py    # gera o .xlsx template para preenchimento
    reader.py      # lê a planilha e devolve lista de NfseRequest
  cli/
    campinas.py    # parser argparse + orquestração para Campinas
    sao_paulo.py   # parser argparse + orquestração para SP
  api/
    conf.py        # parse de api.conf (host, port, bearer_token, prestadores_dir)
    app.py         # FastAPI — GET /prestadores, GET /prestadores/{id}, POST /nfse
    static/
      index.html   # UI single-page HTML/JS (servida pelo FastAPI em GET /)
```

## Servidor REST (`serve`)

Inicia um servidor FastAPI para emissão via interface web ou ferramenta MCP.

### api.conf

```ini
[api]
host          = 127.0.0.1
port          = 8080
bearer_token  = meu-token-secreto

[prestadores]
dir = Z:\nfse\prestadores
```

### Campos extras no .conf do prestador (para uso com a API)

```ini
[prestador]
nome       = Empresa ABC        ; label no dropdown da UI
municipio  = campinas           ; qual driver usar
output_dir = Z:\saida\empresa   ; onde salvar XML emitidos
```

### Endpoints

| Método | Path | O que faz |
|--------|------|-----------|
| `GET` | `/` | UI web (HTML/JS) |
| `GET` | `/prestadores` | Lista prestadores do diretório |
| `GET` | `/prestadores/{id}` | Schema estático do município (campos, série) |
| `GET` | `/prestadores/{id}/proximo-rps` | Consulta SOAP → próximo RPS (com cache) |
| `POST` | `/nfse` | Emite NFS-e; auto-heal E10 com retry |

- Auth: `Authorization: Bearer <token>` em todas as rotas exceto `GET /`
- E10 auto-heal: detecta "E10" no RuntimeError → busca último RPS → incrementa → retenta
- Output: `NF_{tomador}_{numero_nfse}_{competencia}.xml` em `output_dir` do prestador
- Instalar: `pip install -e ".[api]"`

---

## O que usa do conta-tools-shared

| Necessidade | Módulo shared |
|---|---|
| Tipos de dados | `conta_tools_shared.domain.nfse` |
| Assinatura XML | `conta_tools_shared.nfse.signer.assinar_xml` |
| SOAP transport com cert | `conta_tools_shared.nfse.transport.soap_transport` |
| Senha do cert (env) | `conta_tools_shared.auth.certificate.cert_password_from_env` |
| CNPJ do cert | `conta_tools_shared.auth.certificate.cnpj_from_certificate` |
| Log formatado | `conta_tools_shared.logging.formatter` |
| Flags --version/--about | `conta_tools_shared.version.handle_version_flags` |

Instalação dev: `pip install -e ../conta-tools-shared[nfse]`

---

## Versionamento

Contrato completo: `C:\dev\conta-tools-launcher\docs\VERSIONING.md`

**Regra obrigatória:** a cada round de alteração, incrementar PATCH no `pyproject.toml`.

---

## Servidor MCP (`mcp-server`)

Permite emissão via linguagem natural através do Claude Desktop / Claude Code.

### mcp.conf (na máquina do cliente)

```ini
[api]
url          = http://192.168.1.100:8080   ; endereço do servidor REST
bearer_token = meu-token-secreto
```

### Ferramentas expostas

| Ferramenta | O que faz |
|-----------|-----------|
| `listar_prestadores` | Lista empresas emissoras disponíveis (chame sempre primeiro) |
| `montar_emissao` | Valida dados + busca próximo RPS → retorna resumo para conferência |
| `confirmar_emissao` | Emite a NFS-e (só após confirmação textual do usuário) |

### Guardrails embutidos nas descrições das ferramentas

- `listar_prestadores` deve ser chamada antes de qualquer emissão; usuário escolhe o `id` explicitamente
- `montar_emissao` exige CNPJ ou CPF do tomador; nunca infere por nome
- `confirmar_emissao` só é chamada após o usuário confirmar o resumo de `montar_emissao`
- `FastMCP.instructions` reforça as regras a nível de sistema para o agente

### Registro no Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "conta-tools-nfse": {
      "command": "python",
      "args": ["-m", "conta_tools_nfse", "mcp-server", "--conf", "C:\\caminho\\mcp.conf"]
    }
  }
}
```

### Instalar

```bash
pip install -e ".[mcp]"
```

---

## Convenções específicas deste repo

- O XML de cada RPS é montado manualmente com `lxml.etree` — sem geração automática via WSDL
- Assinatura de emissão: `assinar_elemento()` (LoteRps, Signature como irmão)
- Assinatura de consultas: `assinar_consulta()` com `Reference URI=""` (sem Id no elemento)
- `optante_simples` e `serie_rps` ficam no `.conf`, não na planilha Excel
- Testes de integração contra endpoints de homologação ficam em `tests/integration/` e são marcados com `@pytest.mark.integration`
- Testes unitários não fazem chamadas HTTP — usam XML de exemplo fixo
