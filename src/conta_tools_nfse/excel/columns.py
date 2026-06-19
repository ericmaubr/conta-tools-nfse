"""Definição das colunas da planilha de emissão de NFS-e."""

from __future__ import annotations

COLUNAS_OBRIGATORIAS = [
    "numero_rps",
    "competencia",
    "discriminacao",
    "codigo_servico",
    "valor_servico",
    "tomador_razao_social",
]

# Pelo menos uma das duas deve estar preenchida por linha
COLUNAS_TOMADOR_ID = ["tomador_cnpj", "tomador_cpf"]

COLUNAS_OPCIONAIS = [
    "data_emissao",
    "tomador_inscricao_municipal",
    "tomador_email",
    "tomador_logradouro",
    "tomador_numero",
    "tomador_complemento",
    "tomador_bairro",
    "tomador_cep",
    "tomador_municipio_ibge",
    "tomador_uf",
    "deducoes",
    "iss_retido",
    "optante_simples",
    "natureza_operacao",
    "codigo_cnae",
]

TODAS_COLUNAS = (
    COLUNAS_OBRIGATORIAS + COLUNAS_TOMADOR_ID + COLUNAS_OPCIONAIS
)

# Cabeçalhos legíveis para o template
DESCRICOES: dict[str, str] = {
    "numero_rps": "Número RPS *",
    "competencia": "Competência (MM/AAAA) *",
    "discriminacao": "Discriminação do Serviço *",
    "codigo_servico": "Código do Serviço LC116 *",
    "valor_servico": "Valor dos Serviços (R$) *",
    "tomador_razao_social": "Razão Social do Tomador *",
    "tomador_cnpj": "CNPJ do Tomador *",
    "tomador_cpf": "CPF do Tomador (PF) *",
    "data_emissao": "Data de Emissão (DD/MM/AAAA)",
    "tomador_inscricao_municipal": "Inscrição Municipal do Tomador",
    "tomador_email": "E-mail do Tomador",
    "tomador_logradouro": "Logradouro do Tomador",
    "tomador_numero": "Número do Endereço",
    "tomador_complemento": "Complemento",
    "tomador_bairro": "Bairro do Tomador",
    "tomador_cep": "CEP do Tomador (somente dígitos)",
    "tomador_municipio_ibge": "Código IBGE do Município do Tomador",
    "tomador_uf": "UF do Tomador",
    "deducoes": "Deduções (R$)",
    "iss_retido": "ISS Retido? (S/N)",
    "optante_simples": "Optante Simples Nacional? (S/N)",
    "natureza_operacao": "Natureza Operação (1=Município, 2=Fora)",
    "codigo_cnae": "Código CNAE",
}

EXEMPLO: dict[str, object] = {
    "numero_rps": 1,
    "competencia": "01/2026",
    "discriminacao": "Serviços de consultoria em tecnologia da informação",
    "codigo_servico": "1.07",
    "valor_servico": 3500.00,
    "tomador_razao_social": "Empresa Tomadora Ltda",
    "tomador_cnpj": "12.345.678/0001-90",
    "tomador_cpf": "",
    "data_emissao": "",
    "tomador_inscricao_municipal": "",
    "tomador_email": "financeiro@empresa.com.br",
    "tomador_logradouro": "Rua Exemplo",
    "tomador_numero": "100",
    "tomador_complemento": "Sala 5",
    "tomador_bairro": "Centro",
    "tomador_cep": "13010100",
    "tomador_municipio_ibge": "3509502",
    "tomador_uf": "SP",
    "deducoes": 0.00,
    "iss_retido": "N",
    "optante_simples": "N",
    "natureza_operacao": 1,
    "codigo_cnae": "",
}
