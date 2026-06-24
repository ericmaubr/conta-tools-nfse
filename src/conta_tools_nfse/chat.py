"""Agente conversacional para emissão de NFS-e via linguagem natural."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_MODELO_PADRAO = "gemini/gemini-2.5-flash"
_MAX_TURNS = 12
_MAX_TOKENS = 2048

# Logger dedicado — grava em arquivo e no stderr mesmo com uvicorn log_level="warning".
import tempfile
from pathlib import Path

_LOG_FILE = Path(tempfile.gettempdir()) / "conta-tools-nfse-chat.log"

_log = logging.getLogger("conta_tools_nfse.chat")
if not _log.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    _fh = logging.FileHandler(_LOG_FILE, encoding="utf-8-sig")
    _fh.setFormatter(_fmt)
    _log.addHandler(_fh)

    _sh = logging.StreamHandler(sys.stderr)
    _sh.setFormatter(logging.Formatter("\033[36m[CHAT %(levelname)s]\033[0m %(message)s"))
    _log.addHandler(_sh)

    _log.setLevel(logging.DEBUG)
    _log.propagate = False

_RESULT_MAX = 600  # caracteres máximos do resultado das ferramentas no log

_SYSTEM_PROMPT = (
    "Você é um assistente para emissão de NFS-e (Nota Fiscal de Serviços Eletrônica). "
    "REGRAS INVIOLÁVEIS:\n"
    "1. Sempre chame listar_prestadores primeiro. Nunca assuma a empresa emissora.\n"
    "2. Nunca assuma dados do tomador. CNPJ ou CPF é obrigatório — nome sozinho não identifica.\n"
    "3. Quando o tomador for pessoa física (CPF), sempre chame buscar_pessoa_fisica antes de "
    "montar_emissao. Se retornar encontrado=false, colete os dados com o usuário e chame "
    "cadastrar_pessoa_fisica antes de prosseguir.\n"
    "4. Sempre chame montar_emissao e apresente o resumo completo ao usuário. "
    "Só chame confirmar_emissao após confirmação textual explícita do usuário "
    "(ex: 'sim', 'confirmar', 'pode emitir', 'ok').\n"
    "5. Nunca altere valores monetários, RPS ou dados do tomador sem nova confirmação.\n"
    "Responda em português brasileiro. Seja conciso e objetivo."
)

_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "listar_prestadores",
            "description": (
                "Lista as empresas emissoras de NFS-e disponíveis no sistema. "
                "DEVE ser a primeira ferramenta chamada em qualquer fluxo de emissão. "
                "Apresente a lista ao usuário e aguarde seleção explícita pelo campo 'id'. "
                "Nunca assuma qual empresa usar sem confirmação do usuário."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_pessoa_fisica",
            "description": (
                "Consulta o cadastro de pessoas físicas pelo CPF. "
                "DEVE ser chamada sempre que o tomador for pessoa física, antes de montar_emissao. "
                "Retorna encontrado=true com dados cadastrais, ou encontrado=false — "
                "nesse caso colete os dados com o usuário e chame cadastrar_pessoa_fisica."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cpf": {"type": "string", "description": "CPF com ou sem pontuação"},
                },
                "required": ["cpf"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cadastrar_pessoa_fisica",
            "description": (
                "Cadastra ou atualiza uma pessoa física no cadastro. "
                "Use após buscar_pessoa_fisica retornar encontrado=false. "
                "Colete todos os dados com o usuário antes de chamar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cpf":            {"type": "string"},
                    "nome":           {"type": "string"},
                    "logradouro":     {"type": "string", "default": ""},
                    "numero":         {"type": "string", "default": ""},
                    "complemento":    {"type": "string", "default": ""},
                    "bairro":         {"type": "string", "default": ""},
                    "cep":            {"type": "string", "default": ""},
                    "municipio":      {"type": "string", "default": ""},
                    "municipio_ibge": {"type": "string", "default": ""},
                    "uf":             {"type": "string", "default": ""},
                    "email":          {"type": "string", "default": ""},
                    "celular":        {"type": "string", "default": ""},
                    "fixo":           {"type": "string", "default": ""},
                },
                "required": ["cpf", "nome"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "montar_emissao",
            "description": (
                "Valida os dados da NFS-e e monta um resumo para conferência. "
                "NÃO emite a nota. Apresente o resumo ao usuário e aguarde confirmação "
                "explícita antes de chamar confirmar_emissao. "
                "REGRAS: prestador_id deve ser exatamente o 'id' de listar_prestadores; "
                "tomador_cnpj ou tomador_cpf é obrigatório; "
                "competencia no formato AAAA-MM; valor_servico com ponto decimal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prestador_id":         {"type": "string", "description": "ID exato de listar_prestadores."},
                    "tomador_cnpj":         {"type": "string", "description": "CNPJ 14 dígitos. Obrigatório se tomador_cpf ausente."},
                    "tomador_razao_social": {"type": "string"},
                    "competencia":          {"type": "string", "description": "Formato AAAA-MM, ex: 2026-06"},
                    "discriminacao":        {"type": "string"},
                    "codigo_servico":       {"type": "string"},
                    "valor_servico":        {"type": "string", "description": "Valor em reais com ponto decimal, ex: '450.00'"},
                    "tomador_cpf":          {"type": "string", "default": ""},
                    "codigo_cnae":          {"type": "string", "default": ""},
                    "iss_retido":           {"type": "boolean", "default": False},
                    "valor_iss":            {"type": "string", "default": ""},
                    "tomador_email":        {"type": "string", "default": ""},
                    "tomador_logradouro":   {"type": "string", "default": ""},
                    "tomador_numero":       {"type": "string", "default": ""},
                    "tomador_complemento":  {"type": "string", "default": ""},
                    "tomador_bairro":       {"type": "string", "default": ""},
                    "tomador_cep":          {"type": "string", "default": ""},
                    "tomador_uf":           {"type": "string", "default": ""},
                },
                "required": [
                    "prestador_id", "tomador_cnpj", "tomador_razao_social",
                    "competencia", "discriminacao", "codigo_servico", "valor_servico",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirmar_emissao",
            "description": (
                "Emite a NFS-e. Só chame após confirmação explícita do usuário. "
                "Use os mesmos dados de montar_emissao sem alteração, incluindo o numero_rps. "
                "Se o retorno incluir aviso_rps, informe o usuário que o RPS foi ajustado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prestador_id":         {"type": "string"},
                    "numero_rps":           {"type": "string", "description": "RPS retornado por montar_emissao. Não alterar."},
                    "tomador_cnpj":         {"type": "string"},
                    "tomador_razao_social": {"type": "string"},
                    "competencia":          {"type": "string"},
                    "discriminacao":        {"type": "string"},
                    "codigo_servico":       {"type": "string"},
                    "valor_servico":        {"type": "string"},
                    "tomador_cpf":          {"type": "string", "default": ""},
                    "codigo_cnae":          {"type": "string", "default": ""},
                    "iss_retido":           {"type": "boolean", "default": False},
                    "valor_iss":            {"type": "string", "default": ""},
                    "tomador_email":        {"type": "string", "default": ""},
                    "tomador_logradouro":   {"type": "string", "default": ""},
                    "tomador_numero":       {"type": "string", "default": ""},
                    "tomador_complemento":  {"type": "string", "default": ""},
                    "tomador_bairro":       {"type": "string", "default": ""},
                    "tomador_cep":          {"type": "string", "default": ""},
                    "tomador_uf":           {"type": "string", "default": ""},
                },
                "required": [
                    "prestador_id", "numero_rps", "tomador_cnpj", "tomador_razao_social",
                    "competencia", "discriminacao", "codigo_servico", "valor_servico",
                ],
            },
        },
    },
]


def _despachar(nome: str, kwargs: dict) -> str:
    """Chama a função MCP correspondente e retorna resultado como string."""
    from conta_tools_nfse.mcp.server import (
        buscar_pessoa_fisica,
        cadastrar_pessoa_fisica,
        confirmar_emissao,
        listar_prestadores,
        montar_emissao,
    )

    try:
        if nome == "listar_prestadores":
            return listar_prestadores()
        if nome == "buscar_pessoa_fisica":
            return buscar_pessoa_fisica(**kwargs)
        if nome == "cadastrar_pessoa_fisica":
            return cadastrar_pessoa_fisica(**kwargs)
        if nome == "montar_emissao":
            return montar_emissao(**kwargs)
        if nome == "confirmar_emissao":
            return confirmar_emissao(**kwargs)
    except Exception as e:
        return json.dumps({"erro": f"Erro ao executar {nome}: {e}"}, ensure_ascii=False)

    return json.dumps({"erro": f"Ferramenta desconhecida: {nome}"}, ensure_ascii=False)


def _detectar_fase(last_tool_results: dict[str, str]) -> str:
    """Determina a fase da conversa com base nas ferramentas chamadas no último turno."""
    if "confirmar_emissao" in last_tool_results:
        try:
            data = json.loads(last_tool_results["confirmar_emissao"])
            if isinstance(data, dict) and data.get("numero_nfse"):
                return "concluido"
        except Exception:
            pass
        return "pergunta"

    if "montar_emissao" in last_tool_results:
        result = last_tool_results["montar_emissao"]
        if not result.startswith("ERRO"):
            try:
                data = json.loads(result)
                if isinstance(data, dict) and "numero_rps" in data:
                    return "resumo"
            except Exception:
                pass

    return "pergunta"


def responder(
    mensagem: str,
    historico: list[Any],
    modelo: str = _MODELO_PADRAO,
    api_key: str | None = None,
) -> dict:
    """Executa um turno do agente NFS-e.

    Recebe o histórico completo da conversa (sem o system prompt), adiciona a nova
    mensagem do usuário, executa o loop do agente até ele precisar de input do usuário,
    e retorna:

    {
        "resposta": str,        # texto do agente para exibir ao usuário
        "historico": list,      # histórico atualizado (sem system prompt)
        "fase": str,            # "pergunta" | "resumo" | "concluido"
    }
    """
    import litellm

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        *historico,
        {"role": "user", "content": mensagem},
    ]

    kwargs: dict = {}
    if api_key:
        kwargs["api_key"] = api_key

    _log.info("━━━ nova mensagem (%d msgs no histórico) ━━━", len(historico))
    _log.info("👤 usuário: %s", mensagem[:200])

    last_tool_results: dict[str, str] = {}

    for turno in range(_MAX_TURNS):
        last_tool_results = {}

        _log.debug("[turno %d] enviando %d mensagens para %s", turno + 1, len(messages), modelo)

        response = litellm.completion(
            model=modelo,
            messages=messages,
            tools=_TOOLS,
            tool_choice="auto",
            max_tokens=_MAX_TOKENS,
            **kwargs,
        )

        choice = response.choices[0]
        msg = choice.message
        messages.append(msg.model_dump(exclude_none=True))

        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            texto = msg.content or ""
            fase = _detectar_fase(last_tool_results)
            _log.info("🤖 resposta (fase=%s): %s", fase, texto[:200])
            return {
                "resposta": texto,
                "historico": messages[1:],  # sem system prompt
                "fase": fase,
            }

        for tc in tool_calls:
            nome = tc.function.name
            try:
                kwargs_tool = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                kwargs_tool = {}

            args_str = ", ".join(f"{k}={v!r}" for k, v in kwargs_tool.items() if v not in ("", None, False))
            _log.info("  🔧 → %s(%s)", nome, args_str[:300])

            resultado = _despachar(nome, kwargs_tool)
            last_tool_results[nome] = resultado

            try:
                parsed = json.loads(resultado)
                result_str = json.dumps(parsed, ensure_ascii=False)
            except Exception:
                result_str = resultado
            _log.info("  📦 ← %s", result_str[:_RESULT_MAX] + ("…" if len(result_str) > _RESULT_MAX else ""))

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": resultado,
            })

    _log.warning("⚠ limite de %d turnos atingido", _MAX_TURNS)
    return {
        "resposta": "Número máximo de tentativas atingido. Tente reformular sua solicitação.",
        "historico": messages[1:],
        "fase": "pergunta",
    }
