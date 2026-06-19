# conta-tools-nfse — Catálogo de Código

**Consultar este arquivo antes de implementar qualquer coisa neste repo.**

---

## Configuração (`conta_tools_nfse.conf`)

### `conf.py` — Leitura do arquivo .conf do prestador
- `NfseConf(cert_path, inscricao_municipal, cert_senha, ambiente)`
- `carregar_conf(caminho: Path) -> NfseConf`
- Prioridade da senha: campo `senha` no conf > env `CONTA_TOOLS_CERT_PASSWORD`
- Valida obrigatoriedade de `cert` e `inscricao_municipal`; valida valor de `ambiente`

Formato do arquivo `.conf`:
```ini
[prestador]
cert                = C:\certs\empresa.pfx
inscricao_municipal = 123456
senha               = ...       ; opcional se CONTA_TOOLS_CERT_PASSWORD estiver definida

[nfse]
ambiente = producao             ; ou homologacao
```

---

## CLI (`conta_tools_nfse`)

### `__main__.py` — Entry point
- `python -m conta_tools_nfse campinas emitir ...`
- `python -m conta_tools_nfse campinas template ...`
- `--version` / `--about` via `conta_tools_shared.version.handle_version_flags`

---

## CLI Campinas (`conta_tools_nfse.cli.campinas`)

### `cli/campinas.py`
- `main_campinas(argv)` — subcomandos `emitir` e `template`
- `emitir`: lê planilha → chama `CampinasDriver` para cada linha → salva resultado
- `template`: gera `template_nfse_campinas.xlsx` via `criar_template_campinas`

---

## Drivers (`conta_tools_nfse.drivers`)

### `drivers/base.py` — Interface abstrata
- `NfseDriver(ABC)`: `emitir(req: NfseRequest) -> NfseResult`, `cancelar(...) -> None`

### `drivers/campinas.py` — Campinas ABRASF 2.03
- `CampinasDriver(ambiente="producao")`
- `emitir(req)`: monta XML → assina → envia SOAP → parseia retorno
- `_montar_inf_rps(req) -> bytes`: XML do `InfDeclaracaoPrestacaoServico` (Id="rps1")
- `_montar_envelope(inf_assinado, req) -> str`: envolve em `LoteRps`
- `_cabecalho() -> str`: header ABRASF 2.03
- `_parsear_resposta(response, numero_rps) -> NfseResult`

---

## Excel (`conta_tools_nfse.excel`)

### `excel/columns.py` — Definição das colunas
- `COLUNAS_OBRIGATORIAS`: lista de colunas obrigatórias
- `COLUNAS_OPCIONAIS`: lista de colunas opcionais
- `DESCRICOES`: dict coluna → descrição para cabeçalho do template

### `excel/template.py` — Gerador de template
- `criar_template_campinas(caminho: Path) -> None`
- Gera `.xlsx` com cabeçalhos, linha de exemplo, formatação, freeze pane

### `excel/reader.py` — Leitura da planilha
- `ler_planilha_campinas(path, prestador_cnpj, inscricao_municipal, cert_path, cert_senha)`
- Retorna `(list[NfseRequest], list[str])` — pedidos + lista de erros por linha
- Valida colunas obrigatórias, CNPJ/CPF, formato de competência, valores numéricos
