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
- `python -m conta_tools_nfse sao_paulo emitir ...`  (alias: `sp`)
- `python -m conta_tools_nfse sao_paulo template ...`
- `--version` / `--about` via `conta_tools_shared.version.handle_version_flags`

---

## CLI Campinas (`conta_tools_nfse.cli.campinas`)

### `cli/campinas.py`
- `main_campinas(argv)` — subcomandos `emitir` e `template`
- `emitir`: lê planilha → chama `CampinasDriver` para cada linha → salva resultado
- `template`: gera `template_nfse_campinas.xlsx` via `criar_template_campinas`

## CLI São Paulo (`conta_tools_nfse.cli.sao_paulo`)

### `cli/sao_paulo.py`
- `main_sao_paulo(argv)` — subcomandos `emitir` e `template`
- `emitir`: lê planilha SP → chama `SaoPauloDriver` para cada linha → salva resultado
- `template`: gera `template_nfse_sp.xlsx` via `criar_template_sp`

---

## Drivers (`conta_tools_nfse.drivers`)

### `drivers/base.py` — Classe base com helpers compartilhados
- `NfseDriver(ABC)`: `emitir(req: NfseRequest) -> NfseResult`, `cancelar(...) -> None`
- `NfseDriverBase(NfseDriver)`: `_chamar_soap`, `_resposta_para_xml`, `_levantar_se_erro`, `_sub`, `_cnpj_element`

### `drivers/campinas.py` — Campinas ABRASF 2.03
- `CampinasDriver(ambiente="producao")`
- WSDL produção: `https://rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl`
- Operação: `RecepcionarLoteRpsSincrono(nfseCabecMsg, nfseDadosMsg)`
- Assinatura: `assinar_xml()` (enveloped RSA-SHA1) no `InfDeclaracaoPrestacaoServico`

### `drivers/sao_paulo.py` — São Paulo formato SP
- `SaoPauloDriver(ambiente="producao")`
- WSDL produção: `https://nfews.prefeitura.sp.gov.br/lotenfe.asmx?WSDL`
- Operação: `EnviarLoteRpsSincrono(VstrXMLlote)`
- Namespace root: `http://www.prefeitura.sp.gov.br/nfe`; filhos sem namespace (xmlns="")
- Assinatura: `assinar_rps_sp()` (RSA-SHA1 Base64 de string concatenada) em `<Assinatura>`
- `serie_rps` sempre "RPS"; `codigo_servico` 5 dígitos
- `cancelar_com_verificacao(numero_nota, prestador, codigo_verificacao, motivo)` — cancelamento SP exige código de verificação

---

## Excel (`conta_tools_nfse.excel`)

### `excel/columns.py` — Definição das colunas
- `COLUNAS_OBRIGATORIAS`, `COLUNAS_TOMADOR_ID`, `COLUNAS_OPCIONAIS` — Campinas (backward compat)
- `TODAS_COLUNAS` — Campinas completo
- `COLUNAS_SP_OBRIGATORIAS = ["aliquota_servicos"]`
- `COLUNAS_SP_OPCIONAIS = ["tributacao_rps"]`
- `TODAS_COLUNAS_SP` — SP completo
- `DESCRICOES`, `EXEMPLO`, `EXEMPLO_SP` — para templates

### `excel/template.py` — Gerador de template
- `criar_template_campinas(caminho: Path) -> None` — gera template para Campinas
- `criar_template_sp(caminho: Path) -> None` — gera template para SP
- `_preencher_aba(ws, colunas, exemplo, larguras_extra)` — helper compartilhado

### `excel/reader.py` — Leitura da planilha
- `ler_planilha_campinas(path, prestador_cnpj, inscricao_municipal, cert_path, cert_senha)`
- `ler_planilha_sp(path, prestador_cnpj, inscricao_municipal, cert_path, cert_senha)`
- Ambas retornam `(list[NfseRequest], list[str])` — pedidos + erros por linha
- `salvar_resultado(caminho_original, caminho_saida, resultados)` — acrescenta colunas de resultado
- `_mapear_colunas(ws, colunas_busca)` — helper de mapeamento de cabeçalhos
