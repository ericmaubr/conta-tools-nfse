# Reforma Tributária — IBS e CBS na NFS-e

**Pesquisa realizada em:** 2026-06-23
**Contexto:** Avaliação do impacto da Reforma Tributária (EC 132/2023) no projeto conta-tools-nfse

---

## Estado atual (jun/2026)

O portal de Campinas **não possui campos IBS/CBS**. Confirmado por:

| Fonte | Resultado |
|---|---|
| `pref_campinas_oficial/NFS-e_Manual_de_Integracao_versao_2.03_alteracoes.pdf` (42 pág, fev/2016) | Zero menção a IBS ou CBS |
| WSDL real → `nfse-campinas/src/soap/.../Valores.ts` (gerado automaticamente do endpoint) | Sem `ValorIbs`/`ValorCbs` |
| `nfse-campinas-python/src/` | Sem qualquer referência IBS/CBS |
| NFS-e emitida em produção em 20/06/2026 (PDF em `pref_campinas_oficial/`) | Exibe: ISSQN, IRRF, PIS, COFINS, INSS, CSLL — sem IBS/CBS |
| `conta-tools-shared/domain/nfse.py` — `NfseRequest` | Campos presentes: `valor_pis`, `valor_cofins`, `valor_iss` — sem `valor_ibs`/`valor_cbs` |

**Conclusão:** Campinas segue no ABRASF 2.03 (SOAP), padrão de 2016. Emitir NFS-e hoje não exige IBS/CBS no XML.

---

## Contexto legislativo

| Data | Evento |
|---|---|
| Dez/2023 | EC 132/2023 — aprovação da reforma tributária |
| Jan/2025 | LC 214/2025 — regulamentação de IBS e CBS |
| Jan/2026 | Início do período de teste: CBS a 0,9%; IBS a 0,1% |
| 2026–2032 | Transição gradual — ISS/PIS/COFINS reduzindo; IBS/CBS aumentando |
| 2033 | Extinção do ISS; IBS/CBS em alíquota plena |

**IBS** (Imposto sobre Bens e Serviços): substitui ISS (municipal) e ICMS (estadual).
**CBS** (Contribuição sobre Bens e Serviços): substitui PIS e COFINS (federais).

Durante a transição, municípios continuam emitindo NFS-e nos sistemas legados (ABRASF) enquanto adaptam seus portais internamente para calcular e recolher IBS/CBS.

---

## NFS-e Nacional (novo padrão)

A RFB/SPED criou o padrão **NFS-e Nacional** para substituir os sistemas municipais fragmentados:

- **Autenticação:** REST + mTLS (certificado digital), abandona SOAP/WSDL
- **Campos novos relevantes:** `ValorIbs`, `ValorCbs`, `AliquotaIbs`, `AliquotaCbs`, `BaseCalculoIbs`, `BaseCalculoCbs`
- **Portal de adesão municipal:** `nfse.receita.economia.gov.br`
- **Campinas:** ainda **não aderiu** ao padrão nacional (jun/2026)

---

## O que mudará quando Campinas migrar

### `conta-tools-shared/domain/nfse.py` — `NfseRequest`

Adicionar campos opcionais (não quebram retrocompatibilidade):

```python
valor_ibs: Decimal | None = None       # IBS — substitui ValorIss na NFS-e Nacional
valor_cbs: Decimal | None = None       # CBS — substitui ValorPis + ValorCofins
aliquota_ibs: Decimal | None = None    # informada ou calculada pelo portal
aliquota_cbs: Decimal | None = None
```

Manter `valor_pis`, `valor_cofins`, `valor_iss` para retrocompatibilidade com SP (ainda legado).

### `conta-tools-nfse/drivers/`

Criar `campinas_nacional.py` com driver REST — **não alterar** `campinas.py` (ABRASF 2.03) até confirmação de encerramento do portal legado.

Em `conf.py`, adicionar campo para seleção de driver:
```ini
[nfse]
versao = abrasf203   ; ou: nacional
```

### `conta-tools-nfse/api/static/index.html`

Na seção "Dados da Nota", adicionar linha IBS/CBS visível somente quando o driver for `nacional`.

### `conta-tools-nfse/mcp/server.py`

Adicionar parâmetros opcionais `valor_ibs: str = ""` e `valor_cbs: str = ""` em `montar_emissao` e `confirmar_emissao`.

### `conta-tools-nfse/excel/columns.py`

Colunas opcionais `valor_ibs` e `valor_cbs` no template e reader (sem quebrar planilhas existentes).

---

## Resumo de impacto por arquivo

| Arquivo | Mudança quando migrar |
|---|---|
| `conta-tools-shared/domain/nfse.py` | +4 campos opcionais em `NfseRequest` |
| `conta-tools-nfse/drivers/campinas_nacional.py` | Novo driver REST para NFS-e Nacional (criar do zero) |
| `conta-tools-nfse/drivers/campinas.py` | Preservar sem alteração durante transição |
| `conta-tools-nfse/conf.py` | Campo `versao` para seleção de driver |
| `conta-tools-nfse/api/app.py` | Mapear novos campos no endpoint `POST /nfse` |
| `conta-tools-nfse/api/static/index.html` | Linha IBS/CBS condicional em "Dados da Nota" |
| `conta-tools-nfse/mcp/server.py` | Parâmetros IBS/CBS em `montar_emissao`/`confirmar_emissao` |
| `conta-tools-nfse/excel/columns.py` | Colunas opcionais no template |

---

## Ação recomendada

**Nada a implementar agora.** A próxima ação é monitorar:

1. Comunicados da IMA/Campinas sobre data de adesão ao padrão nacional
2. Publicação de novo WSDL ou endpoint REST para NFS-e Nacional em Campinas
3. Quando o novo schema for publicado, capturar o XSD/OpenAPI e salvar em `pref_campinas_oficial/`

Quando Campinas migrar, executar as fases acima na ordem: domínio → driver → API → UI → MCP → Excel.
