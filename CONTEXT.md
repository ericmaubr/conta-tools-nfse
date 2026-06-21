# conta-tools-nfse — Catálogo de Código

**Consultar este arquivo antes de implementar qualquer coisa neste repo.**

---

## Configuração (`conta_tools_nfse.conf`)

### `conf.py` — Leitura do arquivo .conf do prestador
- `NfseConf(cert_path, inscricao_municipal, cert_senha, ambiente, optante_simples, serie_rps, nome, municipio, output_dir)`
- `carregar_conf(caminho: Path) -> NfseConf`
- Prioridade da senha: campo `senha` no conf > env `CONTA_TOOLS_CERT_PASSWORD`
- Valida obrigatoriedade de `cert` e `inscricao_municipal`; valida valor de `ambiente`
- Suporta comentários inline com `;` (ex: `serie_rps = 1 ; comentário`)

Formato do arquivo `.conf`:
```ini
[prestador]
cert                = C:\certs\empresa.pfx
inscricao_municipal = 123456
optante_simples     = S          ; S = Simples Nacional, N = Não Optante
serie_rps           = 1          ; série do RPS (ex: 1, NFSE)
nome                = Empresa ABC ; label na UI da API (opcional)
municipio           = campinas    ; qual driver usar na API (campinas | sao_paulo)
output_dir          = Z:\saida    ; diretório de saída para XMLs (API)
senha               = ...         ; opcional se CONTA_TOOLS_CERT_PASSWORD estiver definida

[nfse]
ambiente = producao              ; ou homologacao
```

---

## CLI (`conta_tools_nfse`)

### `__main__.py` — Entry point
- `python -m conta_tools_nfse campinas emitir ...`
- `python -m conta_tools_nfse campinas template ...`
- `python -m conta_tools_nfse campinas ultimo-rps ...`
- `python -m conta_tools_nfse sao_paulo emitir ...`  (alias: `sp`)
- `python -m conta_tools_nfse sao_paulo template ...`
- `python -m conta_tools_nfse serve --conf api.conf` — inicia servidor FastAPI
- `--version` / `--about` via `conta_tools_shared.version.handle_version_flags`

---

## CLI Campinas (`conta_tools_nfse.cli.campinas`)

### `cli/campinas.py`
- `main_campinas(argv)` — subcomandos `template`, `emitir` e `ultimo-rps`
- `template`: gera `template_nfse_campinas.xlsx` via `criar_template_campinas`
- `emitir`: lê planilha → chama `CampinasDriver` para cada linha → salva resultado
- `ultimo-rps`: retroage mês a mês consultando `CampinasDriver.consultar_nfse_periodo`;
  exibe `{série → último RPS, NFS-e, data}` para todas as séries do prestador

## CLI São Paulo (`conta_tools_nfse.cli.sao_paulo`)

### `cli/sao_paulo.py`
- `main_sao_paulo(argv)` — subcomandos `emitir` e `template`
- `emitir`: lê planilha SP → chama `SaoPauloDriver` para cada linha → salva resultado
- `template`: gera `template_nfse_sp.xlsx` via `criar_template_sp`

---

## API REST (`conta_tools_nfse.api`)

### `api/conf.py` — Configuração do servidor
- `ApiConf(host, port, bearer_token, prestadores_dir)`
- `carregar_api_conf(caminho: Path) -> ApiConf`
- Seções `[api]` e `[prestadores]` no arquivo `api.conf`

### `api/app.py` — FastAPI
- `create_app(api_conf: ApiConf) -> FastAPI` — factory chamada pelo `serve` command
- `GET /` — serve `api/static/index.html` (UI sem autenticação)
- `GET /prestadores` — lista prestadores do diretório (auth Bearer)
- `GET /prestadores/{id}` — schema estático: municipio, serie_rps, campos_extras, campos_obrigatorios
- `GET /prestadores/{id}/proximo-rps` — consulta SOAP (com cache de sessão) → próximo RPS
- `POST /nfse` — emissão com auto-heal E10 e salvamento de XML em output_dir
- Cache `_rps_cache: dict[str, int]` — proximo_rps por prestador, atualizado após emissão
- E10 auto-heal: detecta "E10" no RuntimeError → limpa cache → recomputa → retenta
- Resposta inclui `rps_ajustado: {de, para}` quando RPS foi corrigido

### `api/static/index.html` — UI web
- Token Bearer armazenado em `localStorage` (inserido manualmente pelo usuário)
- Dropdown de prestadores carregado via `GET /prestadores`
- `GET /prestadores/{id}/proximo-rps` chamado assincronamente ao selecionar prestador
- Após sucesso: limpa tomador, valor, discriminação; incrementa RPS; mostra aviso de ajuste se houve

---

## Drivers (`conta_tools_nfse.drivers`)

Contrato completo de implementação: [`docs/DRIVERS.md`](docs/DRIVERS.md)

### `drivers/base.py` — Classe base com helpers compartilhados
- `NfseDriver(ABC)`: `emitir(req: NfseRequest) -> NfseResult`, `cancelar(...) -> None`
- `NfseDriverBase(NfseDriver)`: `_chamar_soap`, `_resposta_para_xml`, `_levantar_se_erro`, `_sub`, `_cnpj_element`

### `drivers/campinas.py` — Campinas ABRASF 2.03
- `CampinasDriver(ambiente="producao")`
- WSDL homologação: `https://homol-rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl`
- WSDL produção: `https://novanfse.campinas.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl`
- Binding: `document/literal`, `elementFormDefault="unqualified"` — **todos os elementos sem namespace**
- Operação `RecepcionarLoteRpsSincrono`: `EnviarLoteRpsSincronoEnvio` embutido como XML real no SOAP body
- Assinatura de emissão: `assinar_elemento()` no `LoteRps` (Id="lote1"); `Signature` fica como irmão
- Assinatura de consultas: `assinar_consulta()` com `Reference URI=""` (padrão dos templates oficiais)
- Link de consulta: construído programaticamente — Campinas não retorna `LinkConsultaNfse` na resposta
- **CNAE com 9 dígitos**: driver normaliza automaticamente (7 dígitos → adiciona `"00"`)
- **`OptanteSimplesNacional`**: lido de `conf.optante_simples`; deve bater com cadastro IMA
- **`serie_rps`**: lido de `conf.serie_rps` (default `"1"`); sistema legado usava `"NFSE"`
- `consultar_nfse_periodo(prestador, data_ini, data_fim)` → `dict[str, tuple[str,str,str]]`
- Debug: `NFSE_DEBUG_SOAP=<dir>` grava request/response XML no diretório indicado

### `drivers/sao_paulo.py` — São Paulo formato SP
- `SaoPauloDriver(ambiente="producao")`
- WSDL produção: `https://nfews.prefeitura.sp.gov.br/lotenfe.asmx?WSDL`
- Operação: `EnviarLoteRpsSincrono(VstrXMLlote)`
- Namespace root: `http://www.prefeitura.sp.gov.br/nfe`; filhos sem namespace (xmlns="")
- Assinatura: `assinar_rps_sp()` (RSA-SHA1 Base64 de string concatenada) em `<Assinatura>`
- `serie_rps` sempre `"RPS"` (fixo); `codigo_servico` 5 dígitos
- `cancelar_com_verificacao(numero_nota, prestador, codigo_verificacao, motivo)`
- `consultar_nfse_periodo` **não implementado** — `ultimo-rps` não disponível para SP

---

## Excel (`conta_tools_nfse.excel`)

### `excel/columns.py` — Definição das colunas
- `COLUNAS_OBRIGATORIAS`, `COLUNAS_TOMADOR_ID`, `COLUNAS_OPCIONAIS` — Campinas (backward compat)
- `TODAS_COLUNAS` — Campinas completo
- `COLUNAS_SP_OBRIGATORIAS = ["aliquota_servicos"]`
- `COLUNAS_SP_OPCIONAIS = ["tributacao_rps"]`
- `TODAS_COLUNAS_SP` — SP completo
- `DESCRICOES`, `EXEMPLO`, `EXEMPLO_SP` — para templates
- `optante_simples` **não está nas colunas** — vem do `.conf`

### `excel/template.py` — Gerador de template
- `criar_template_campinas(caminho: Path) -> None` — gera template para Campinas
- `criar_template_sp(caminho: Path) -> None` — gera template para SP
- `_preencher_aba(ws, colunas, exemplo, larguras_extra)` — helper compartilhado

### `excel/reader.py` — Leitura da planilha
- `ler_planilha_campinas(path, prestador_cnpj, inscricao_municipal, cert_path, cert_senha, optante_simples=False, serie_rps="1")`
- `ler_planilha_sp(path, prestador_cnpj, inscricao_municipal, cert_path, cert_senha, optante_simples=False)`
- Ambas retornam `(list[NfseRequest], list[str])` — pedidos + erros por linha
- `salvar_resultado(caminho_original, caminho_saida, resultados)`:
  - Acrescenta colunas `status`, `numero_nfse`, `codigo_verificacao`, `link_consulta`, `erro`
  - Detecta colunas de resultado de run anterior (pelo header `"status"`) e sobrescreve em vez de duplicar
- `_mapear_colunas(ws, colunas_busca)` — helper de mapeamento de cabeçalhos
