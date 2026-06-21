# Contrato de implementação de drivers de prefeitura

Este documento define o que cada driver de município deve implementar para ser
considerado completo e integrado ao CLI `conta-tools-nfse`.

---

## Interface obrigatória (`NfseDriver`)

Todo driver herda de `NfseDriverBase` e deve implementar dois métodos abstratos:

| Método | Assinatura | O que faz |
|--------|-----------|-----------|
| `emitir` | `(req: NfseRequest) -> NfseResult` | Emite uma NFS-e e retorna o resultado |
| `cancelar` | `(numero_nota, prestador, codigo_cancelamento) -> None` | Cancela uma NFS-e emitida |

`NfseDriverBase` fornece os helpers: `_chamar_soap`, `_resposta_para_xml`,
`_levantar_se_erro`, `_sub`, `_cnpj_element`.

---

## Método recomendado para consulta

Habilita o subcomando `ultimo-rps` do CLI:

| Método | Assinatura | O que faz |
|--------|-----------|-----------|
| `consultar_nfse_periodo` | `(prestador, data_ini, data_fim) -> dict[str, tuple[str, str, str]]` | Retorna `{serie: (ultimo_rps, numero_nfse, data_emissao)}` para o período |

O CLI chama esse método mês a mês (do atual para o passado) até encontrar resultados.
Se o driver não implementar esse método, o subcomando `ultimo-rps` não funciona para
esse município.

---

## Configuração no `.conf`

Todo driver deve documentar quais chaves lê do `.conf`. As obrigatórias (comuns a todos):

```ini
[prestador]
cert                = C:\certs\empresa.pfx   ; caminho para o certificado A1 (PFX/P12)
inscricao_municipal = 000000                  ; inscrição municipal do prestador
senha               = ...                     ; senha do PFX (ou usar CONTA_TOOLS_CERT_PASSWORD)

[nfse]
ambiente = producao                           ; producao | homologacao
```

Chaves opcionais são definidas por cada município (ver seções abaixo).

---

## Subcomandos CLI obrigatórios

Cada município deve ter ao menos:

| Subcomando | O que faz |
|-----------|-----------|
| `template` | Gera a planilha Excel de exemplo para preenchimento |
| `emitir --planilha XLSX --conf CONF` | Lê a planilha e emite as notas |
| `ultimo-rps --conf CONF` | Consulta o último RPS por série *(requer `consultar_nfse_periodo`)* |

---

## Municípios implementados

### Campinas — ABRASF 2.03

| Item | Valor |
|------|-------|
| Padrão | ABRASF 2.03 |
| WSDL produção | `https://novanfse.campinas.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl` |
| WSDL homologação | `https://homol-rps.ima.sp.gov.br/notafiscal-abrasfv203-ws/NotaFiscalSoap?wsdl` |
| Binding SOAP | `document/literal`, `elementFormDefault="unqualified"` |
| Namespace | `http://www.abrasf.org.br/nfse.xsd` |
| Código IBGE | `3509502` |
| mTLS | Obrigatório (certificado A1 do prestador) |

**Operação de emissão (`RecepcionarLoteRpsSincrono`):**
- `EnviarLoteRpsSincronoEnvio` é embutido diretamente no SOAP body como elemento XML
  (não como string em `nfseDadosMsg`)
- `LoteRps` (Id="lote1") é assinado com `assinar_elemento()` — Signature fica como irmão
  dentro de `EnviarLoteRpsSincronoEnvio`

**Operações de consulta (`ConsultarNfseServicoPrestado`, etc.):**
- Mesma estrutura document/literal
- XML assinado com `assinar_consulta()` — `Reference URI=""` (enveloped, sem Id no elemento)
- Conforme templates XML oficiais da prefeitura

**Link de consulta da NFS-e:**
- Campinas não retorna `LinkConsultaNfse` na resposta SOAP
- O driver constrói o link programaticamente:
  `{base_wsdl}/notafiscal-ws/servico/notafiscal/autenticacao/cpfCnpj/{cnpj}/inscricaoMunicipal/{im}/numeroNota/{num}/codigoVerificacao/{cod}`

**Quirks obrigatórios:**
- **CNAE 9 dígitos**: o padrão ABRASF especifica N(7), mas Campinas exige 9 dígitos.
  O driver normaliza automaticamente: 7 dígitos → adiciona `"00"` (ex: `6920601` → `692060100`).
  Erro sem isso: `L999 — Atividade não informada`.
- **`OptanteSimplesNacional`**: deve bater com o cadastro da prefeitura.
  Erro se divergir: `E188`. Configurado no `.conf` (`optante_simples = S|N`).
- **Assinatura de consultas**: Campinas rejeita qualquer operação sem assinatura XMLDSig,
  incluindo consultas. Usar `assinar_consulta()` que gera `Reference URI=""`.

**Chaves extras no `.conf`:**
```ini
[prestador]
optante_simples = S    ; S = Simples Nacional, N = Não Optante (deve bater com cadastro IMA)
serie_rps       = 1    ; série do RPS; sistema legado usava "NFSE"
```

**Debug:**
- `NFSE_DEBUG_SOAP=<diretório>` grava request/response XML no diretório indicado.

---

### São Paulo — Formato SP (layout v2)

| Item | Valor |
|------|-------|
| Padrão | Proprietário SP (não-ABRASF) |
| WSDL produção | `https://nfews.prefeitura.sp.gov.br/lotenfe.asmx?WSDL` |
| Binding SOAP | `document/literal` via zeep |
| Namespace root | `http://www.prefeitura.sp.gov.br/nfe` |
| mTLS | Obrigatório |

**Diferenças em relação a Campinas:**
- Assinatura: `assinar_rps_sp()` — RSA-SHA1 de string concatenada de campos, resultado
  vai no elemento `<Assinatura>` do XML (não é XMLDSig)
- `serie_rps` sempre `"RPS"` (fixo, não configurável)
- Código de serviço: 5 dígitos (ex: `07498`)
- Cancelamento exige código de verificação da nota:
  `cancelar_com_verificacao(numero_nota, prestador, codigo_verificacao, motivo)`
- `consultar_nfse_periodo` **não implementado** — `ultimo-rps` não disponível para SP

**Chaves extras no `.conf`:**
```ini
[prestador]
optante_simples = S    ; S = Simples Nacional, N = Não Optante
; serie_rps não se aplica — sempre "RPS"
```

---

## Adicionando um novo município

1. Criar `drivers/<municipio>.py` herdando de `NfseDriverBase`
2. Implementar `emitir()` e `cancelar()`
3. Implementar `consultar_nfse_periodo()` se o webservice oferecer consulta por período
4. Criar `cli/<municipio>.py` com subcomandos `template`, `emitir` e `ultimo-rps`
5. Registrar no `__main__.py`
6. Documentar quirks neste arquivo (seção acima)
7. Atualizar `CONTEXT.md` e `CLAUDE.md`
