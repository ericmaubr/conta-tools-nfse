"""FastAPI — servidor REST para emissão de NFS-e via interface web ou MCP."""

from __future__ import annotations

import calendar
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from conta_tools_nfse.api.conf import ApiConf
from conta_tools_nfse.conf import NfseConf, carregar_conf

# ------------------------------------------------------------------ #
# Estado de aplicação (preenchido por create_app)                     #
# ------------------------------------------------------------------ #

_api_conf: ApiConf | None = None
_rps_cache: dict[str, int] = {}          # prestador_id → proximo_rps
_cnae_cache: dict[str, list[dict]] = {}  # prestador_id → [{codigo, descricao}]

try:
    from conta_tools_nfse.api.pessoas_fisicas import PessoasFisicasDb
    _db_pf: PessoasFisicasDb | None = None
except ImportError:
    _db_pf = None  # type: ignore[assignment]

# ------------------------------------------------------------------ #
# Helpers de autenticação                                             #
# ------------------------------------------------------------------ #

_security = HTTPBearer()


def _verificar_token(
    credentials: HTTPAuthorizationCredentials = Security(_security),
) -> str:
    assert _api_conf is not None
    if credentials.credentials != _api_conf.bearer_token:
        raise HTTPException(status_code=401, detail="Token inválido")
    return credentials.credentials


# ------------------------------------------------------------------ #
# Modelos Pydantic                                                     #
# ------------------------------------------------------------------ #


class PrestadorItem(BaseModel):
    id: str
    nome: str


class PrestadorSchema(BaseModel):
    id: str
    nome: str
    municipio: str
    serie_rps: str
    campos_extras: list[str]
    campos_obrigatorios: list[str]
    cnaes: list[dict] = []           # [{codigo, descricao}] do prestador
    aliq_retencoes: dict = {}        # {aliq_pis, aliq_cofins, aliq_inss, aliq_ir, aliq_csll}
    codigo_servico: str = ""         # código LC 116 padrão do prestador


class EmissaoRequest(BaseModel):
    prestador_id: str
    numero_rps: str
    competencia: str          # "AAAA-MM"
    discriminacao: str
    codigo_servico: str
    codigo_cnae: str = ""
    codigo_tributacao_municipio: str = ""
    valor_servico: str        # string — evita perda de precisão float
    iss_retido: bool = False
    valor_iss: str | None = None
    valor_pis: str = "0"
    valor_cofins: str = "0"
    valor_inss: str = "0"
    valor_ir: str = "0"
    valor_csll: str = "0"
    valor_outras_retencoes: str = "0"
    tomador_razao_social: str
    tomador_cnpj: str = ""
    tomador_cpf: str = ""
    tomador_email: str = ""
    tomador_logradouro: str = ""
    tomador_numero: str = ""
    tomador_complemento: str = ""
    tomador_bairro: str = ""
    tomador_cep: str = ""
    tomador_municipio_ibge: str = ""
    tomador_uf: str = ""


class EmissaoResponse(BaseModel):
    status: str               # "ok" | "erro"
    numero_nfse: str = ""
    codigo_verificacao: str = ""
    link_consulta: str = ""
    rps_ajustado: dict[str, Any] | None = None
    arquivo: str = ""
    mensagem: str = ""


class PessoaFisicaSchema(BaseModel):
    cpf: str
    nome: str
    logradouro: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    cep: str = ""
    municipio: str = ""
    municipio_ibge: str = ""
    uf: str = ""
    email: str = ""
    celular: str = ""
    fixo: str = ""


# ------------------------------------------------------------------ #
# Campos por município                                                 #
# ------------------------------------------------------------------ #

_CAMPOS_EXTRAS: dict[str, list[str]] = {
    "campinas": ["codigo_cnae"],
    "sao_paulo": [],
}

_CAMPOS_OBRIGATORIOS: dict[str, list[str]] = {
    "campinas": ["codigo_servico", "codigo_cnae", "valor_servico", "competencia", "discriminacao"],
    "sao_paulo": ["codigo_servico", "valor_servico", "competencia", "discriminacao"],
}


# ------------------------------------------------------------------ #
# Helpers internos                                                     #
# ------------------------------------------------------------------ #


def _cnpj_prestador(conf: NfseConf) -> str:
    """CNPJ do prestador: campo explícito (procuração) ou extraído do certificado."""
    if conf.cnpj_prestador:
        return conf.cnpj_prestador  # já normalizado em carregar_conf
    from conta_tools_shared.auth.certificate import cnpj_from_certificate, load_pfx_data
    return cnpj_from_certificate(load_pfx_data(conf.cert_path, conf.cert_senha))


def _normalizar_cnae(codigo: str) -> str:
    digits = re.sub(r"\D", "", str(codigo))
    return digits + "00" if len(digits) == 7 else digits


def _get_prestador_cnaes(prestador_id: str, conf: NfseConf) -> list[dict]:
    """Busca CNAEs do prestador via conta-tools-cnpj (cache de sessão).

    Retorna lista com CNAE principal primeiro, seguido dos secundários,
    todos normalizados para 9 dígitos.
    """
    if prestador_id in _cnae_cache:
        return _cnae_cache[prestador_id]

    assert _api_conf is not None
    if not _api_conf.cnpj_api_url:
        _cnae_cache[prestador_id] = []
        return []

    try:
        import requests as _req

        cnpj = _cnpj_prestador(conf)
        r = _req.get(f"{_api_conf.cnpj_api_url}/cnpj/{cnpj}", timeout=5)
        cnaes: list[dict] = []
        if r.status_code == 200:
            d = r.json()
            if d.get("cnae_fiscal"):
                cnaes.append({
                    "codigo": _normalizar_cnae(d["cnae_fiscal"]),
                    "descricao": d.get("cnae_descricao", ""),
                })
            for sec in d.get("cnaes_secundarios") or []:
                if sec.get("codigo"):
                    cnaes.append({
                        "codigo": _normalizar_cnae(sec["codigo"]),
                        "descricao": sec.get("descricao", ""),
                    })
        _cnae_cache[prestador_id] = cnaes
        return cnaes
    except Exception:
        _cnae_cache[prestador_id] = []
        return []


def _caminho_conf(prestador_id: str) -> Path:
    assert _api_conf is not None
    return _api_conf.prestadores_dir / f"{prestador_id}.conf"


def _carregar_prestador(prestador_id: str) -> NfseConf:
    caminho = _caminho_conf(prestador_id)
    if not caminho.exists():
        raise HTTPException(status_code=404, detail=f"Prestador não encontrado: {prestador_id}")
    try:
        return carregar_conf(caminho)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ler configuração do prestador: {e}")


def _nome_prestador(prestador_id: str, conf: NfseConf) -> str:
    return conf.nome or prestador_id.replace("_", " ").title()


def _get_proximo_rps(prestador_id: str, conf: NfseConf) -> int:
    """Consulta o último RPS via SOAP e retorna próximo (com cache de sessão)."""
    if prestador_id in _rps_cache:
        return _rps_cache[prestador_id]

    from conta_tools_shared.domain.nfse import PrestadorNfse

    try:
        cnpj = _cnpj_prestador(conf)
        prestador = PrestadorNfse(
            cnpj=cnpj,
            inscricao_municipal=conf.inscricao_municipal,
            cert_path=conf.cert_path,
            cert_senha=conf.cert_senha,
        )
    except Exception:
        return 1

    driver = _make_driver(conf)
    if driver is None or not hasattr(driver, "consultar_nfse_periodo"):
        return 1

    hoje = date.today()
    ano, mes = hoje.year, hoje.month
    for _ in range(3):
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        data_ini = f"{ano}-{mes:02d}-01"
        data_fim = f"{ano}-{mes:02d}-{ultimo_dia:02d}"
        try:
            resultado = driver.consultar_nfse_periodo(prestador, data_ini, data_fim)
        except Exception:
            resultado = {}
        if resultado:
            ultimo = max(int(v[0]) for v in resultado.values() if v[0].isdigit())
            proximo = ultimo + 1
            _rps_cache[prestador_id] = proximo
            return proximo
        mes -= 1
        if mes == 0:
            mes = 12
            ano -= 1

    _rps_cache[prestador_id] = 1
    return 1


def _make_driver(conf: NfseConf):
    municipio = conf.municipio
    if municipio == "campinas":
        from conta_tools_nfse.drivers.campinas import CampinasDriver
        return CampinasDriver(ambiente=conf.ambiente)
    if municipio in ("sao_paulo", "sp"):
        from conta_tools_nfse.drivers.sao_paulo import SaoPauloDriver
        return SaoPauloDriver(ambiente=conf.ambiente)
    return None


def _salvar_xml(conf: NfseConf, tomador: str, numero: str, competencia: str, xml: bytes) -> str:
    out_dir = conf.output_dir
    if not out_dir:
        return ""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w]", "_", tomador[:30]).strip("_")
    comp = competencia.replace("-", "_")
    filename = f"NF_{slug}_{numero}_{comp}.xml"
    (out_dir / filename).write_bytes(xml)
    return filename


def _decimal(valor: str | None, campo: str) -> Decimal:
    if not valor:
        raise HTTPException(status_code=422, detail=f"Campo obrigatório ausente: {campo}")
    try:
        return Decimal(valor.replace(",", "."))
    except InvalidOperation:
        raise HTTPException(status_code=422, detail=f"Valor inválido para {campo}: {valor!r}")


def _aliquotas_efetivas(conf: NfseConf) -> dict:
    assert _api_conf is not None
    def _ef(prestador_val: float | None, api_val: float) -> float:
        return prestador_val if prestador_val is not None else api_val
    return {
        "aliq_iss":    _ef(conf.aliq_iss,    _api_conf.aliq_iss),
        "aliq_pis":    _ef(conf.aliq_pis,    _api_conf.aliq_pis),
        "aliq_cofins": _ef(conf.aliq_cofins, _api_conf.aliq_cofins),
        "aliq_inss":   _ef(conf.aliq_inss,   _api_conf.aliq_inss),
        "aliq_ir":     _ef(conf.aliq_ir,     _api_conf.aliq_ir),
        "aliq_csll":   _ef(conf.aliq_csll,   _api_conf.aliq_csll),
    }


def _decimal_zero(valor: str | None) -> Decimal:
    if not valor:
        return Decimal("0")
    try:
        return Decimal(valor.replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


# ------------------------------------------------------------------ #
# Rotas                                                               #
# ------------------------------------------------------------------ #

app = FastAPI(title="ContaTools NFS-e API", version="1.0")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/pessoas-fisicas-ui", response_class=HTMLResponse, include_in_schema=False)
def pessoas_fisicas_ui():
    html_path = Path(__file__).parent / "static" / "pessoas-fisicas.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/cnpj/{cnpj}")
def consultar_cnpj(cnpj: str, _token: str = Depends(_verificar_token)):
    import requests as _req

    assert _api_conf is not None
    if not _api_conf.cnpj_api_url:
        raise HTTPException(status_code=503, detail="Consulta de CNPJ nao configurada (cnpj_api_url ausente no api.conf).")

    cnpj_digits = re.sub(r"\D", "", cnpj)
    if len(cnpj_digits) != 14:
        raise HTTPException(status_code=422, detail="CNPJ deve ter 14 digitos.")

    try:
        r = _req.get(f"{_api_conf.cnpj_api_url}/cnpj/{cnpj_digits}", timeout=10)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="CNPJ nao encontrado na base.")
        r.raise_for_status()
        d = r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar conta-tools-cnpj: {e}")

    return {
        "razao_social":    d.get("razao_social", ""),
        "email":           d.get("email", ""),
        "logradouro":      d.get("logradouro", ""),
        "numero":          d.get("numero", ""),
        "complemento":     d.get("complemento", ""),
        "bairro":          d.get("bairro", ""),
        "cep":             re.sub(r"\D", "", d.get("cep", "")),
        "municipio_ibge":  str(d.get("municipio_ibge", "")),
        "uf":              d.get("uf", ""),
        "optante_simples": d.get("optante_simples", "N"),
    }


@app.get("/prestadores", response_model=list[PrestadorItem])
def list_prestadores(_token: str = Depends(_verificar_token)):
    assert _api_conf is not None
    resultado = []
    for conf_path in sorted(_api_conf.prestadores_dir.glob("*.conf")):
        pid = conf_path.stem
        try:
            conf = carregar_conf(conf_path)
            nome = _nome_prestador(pid, conf)
            resultado.append(PrestadorItem(id=pid, nome=nome))
        except Exception:
            pass
    return resultado


@app.get("/prestadores/{prestador_id}", response_model=PrestadorSchema)
def get_prestador_schema(
    prestador_id: str,
    _token: str = Depends(_verificar_token),
):
    conf = _carregar_prestador(prestador_id)
    municipio = conf.municipio or "campinas"
    cnaes = _get_prestador_cnaes(prestador_id, conf)
    return PrestadorSchema(
        id=prestador_id,
        nome=_nome_prestador(prestador_id, conf),
        municipio=municipio,
        serie_rps=conf.serie_rps,
        campos_extras=_CAMPOS_EXTRAS.get(municipio, []),
        campos_obrigatorios=_CAMPOS_OBRIGATORIOS.get(municipio, []),
        cnaes=cnaes,
        aliq_retencoes=_aliquotas_efetivas(conf),
        codigo_servico=conf.codigo_servico,
    )


@app.get("/prestadores/{prestador_id}/proximo-rps")
def get_proximo_rps(
    prestador_id: str,
    _token: str = Depends(_verificar_token),
):
    conf = _carregar_prestador(prestador_id)
    return {"proximo_rps": _get_proximo_rps(prestador_id, conf)}


@app.post("/nfse", response_model=EmissaoResponse)
def emitir_nfse(
    req: EmissaoRequest,
    _token: str = Depends(_verificar_token),
):
    from conta_tools_shared.domain.nfse import NfseRequest, PrestadorNfse, TomadorNfse

    conf = _carregar_prestador(req.prestador_id)

    if not req.tomador_cnpj and not req.tomador_cpf:
        raise HTTPException(status_code=422, detail="Informe CNPJ ou CPF do tomador.")
    if not req.tomador_razao_social.strip():
        raise HTTPException(status_code=422, detail="Razão social do tomador é obrigatória.")

    try:
        cnpj = _cnpj_prestador(conf)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter CNPJ do prestador: {e}")

    prestador = PrestadorNfse(
        cnpj=cnpj,
        inscricao_municipal=conf.inscricao_municipal,
        cert_path=conf.cert_path,
        cert_senha=conf.cert_senha,
    )

    tomador = TomadorNfse(
        razao_social=req.tomador_razao_social.strip(),
        cnpj=re.sub(r"\D", "", req.tomador_cnpj),
        cpf=re.sub(r"\D", "", req.tomador_cpf),
        email=req.tomador_email.strip(),
        logradouro=req.tomador_logradouro.strip(),
        numero=req.tomador_numero.strip(),
        complemento=req.tomador_complemento.strip(),
        bairro=req.tomador_bairro.strip(),
        cep=re.sub(r"\D", "", req.tomador_cep),
        municipio_ibge=req.tomador_municipio_ibge.strip(),
        uf=req.tomador_uf.strip().upper(),
    )

    municipio = conf.municipio or "campinas"
    valor_servico = _decimal(req.valor_servico, "valor_servico")
    valor_iss = _decimal(req.valor_iss, "valor_iss") if req.iss_retido and req.valor_iss else None

    nfse_req = NfseRequest(
        id=str(uuid.uuid4()),
        prestador=prestador,
        tomador=tomador,
        discriminacao=req.discriminacao.strip(),
        valor_servico=valor_servico,
        codigo_servico=req.codigo_servico.strip(),
        municipio_prestacao=municipio,  # type: ignore[arg-type]
        competencia=req.competencia,
        numero_rps=req.numero_rps,
        serie_rps=conf.serie_rps,
        iss_retido=req.iss_retido,
        optante_simples=conf.optante_simples,
        codigo_cnae=req.codigo_cnae.strip(),
        codigo_tributacao_municipio=req.codigo_tributacao_municipio.strip(),
        valor_iss=valor_iss,
        valor_pis=_decimal_zero(req.valor_pis),
        valor_cofins=_decimal_zero(req.valor_cofins),
        valor_inss=_decimal_zero(req.valor_inss),
        valor_ir=_decimal_zero(req.valor_ir),
        valor_csll=_decimal_zero(req.valor_csll),
        valor_outras_retencoes=_decimal_zero(req.valor_outras_retencoes),
    )

    driver = _make_driver(conf)
    if driver is None:
        raise HTTPException(status_code=400, detail=f"Município não suportado: {municipio}")

    rps_ajustado: dict[str, Any] | None = None

    try:
        result = driver.emitir(nfse_req)
    except RuntimeError as e:
        err_str = str(e)
        if "E10" in err_str or "RPS" in err_str.upper() and "utilizado" in err_str.lower():
            # Auto-heal: busca último RPS e retenta
            rps_original = req.numero_rps
            try:
                # Invalida cache e busca o último RPS real via SOAP
                _rps_cache.pop(req.prestador_id, None)
                proximo = _get_proximo_rps(req.prestador_id, conf)
            except Exception:
                raise HTTPException(status_code=500, detail=f"E10 e falha no auto-heal: {e}")
            nfse_req.numero_rps = str(proximo)
            try:
                result = driver.emitir(nfse_req)
                rps_ajustado = {"de": rps_original, "para": str(proximo)}
            except RuntimeError as e2:
                raise HTTPException(status_code=422, detail=str(e2))
        else:
            raise HTTPException(status_code=422, detail=err_str)

    # Atualizar cache com próximo RPS após emissão bem-sucedida
    try:
        _rps_cache[req.prestador_id] = int(nfse_req.numero_rps) + 1
    except ValueError:
        pass

    # Salvar XML
    arquivo = ""
    if result.xml_retorno:
        try:
            arquivo = _salvar_xml(
                conf,
                tomador.razao_social,
                result.numero_nota,
                req.competencia,
                result.xml_retorno,
            )
        except Exception:
            pass  # falha em salvar não deve interromper a resposta

    return EmissaoResponse(
        status="ok",
        numero_nfse=result.numero_nota,
        codigo_verificacao=result.codigo_verificacao,
        link_consulta=result.link_consulta,
        rps_ajustado=rps_ajustado,
        arquivo=arquivo,
    )


# ------------------------------------------------------------------ #
# Endpoints — Cadastro de Pessoas Físicas                             #
# ------------------------------------------------------------------ #

_PF_NAO_CONFIGURADO = HTTPException(
    status_code=503,
    detail="Cadastro de pessoas físicas não configurado (db_path ausente em api.conf).",
)


@app.get("/pessoas-fisicas", response_model=list[PessoaFisicaSchema])
def list_pessoas_fisicas(_token: str = Depends(_verificar_token)):
    if _db_pf is None:
        raise _PF_NAO_CONFIGURADO
    return [pf.to_dict() for pf in _db_pf.listar()]


@app.get("/pessoas-fisicas/{cpf}", response_model=PessoaFisicaSchema)
def get_pessoa_fisica(cpf: str, _token: str = Depends(_verificar_token)):
    if _db_pf is None:
        raise _PF_NAO_CONFIGURADO
    pf = _db_pf.buscar(cpf)
    if pf is None:
        raise HTTPException(status_code=404, detail="CPF não encontrado no cadastro.")
    return pf.to_dict()


@app.post("/pessoas-fisicas", response_model=PessoaFisicaSchema)
def upsert_pessoa_fisica(
    req: PessoaFisicaSchema,
    _token: str = Depends(_verificar_token),
):
    if _db_pf is None:
        raise _PF_NAO_CONFIGURADO
    if not req.nome.strip():
        raise HTTPException(status_code=422, detail="Campo 'nome' é obrigatório.")
    from conta_tools_nfse.api.pessoas_fisicas import PessoaFisica
    pf = PessoaFisica(**req.model_dump())
    saved = _db_pf.salvar(pf)
    return saved.to_dict()


@app.delete("/pessoas-fisicas/{cpf}", status_code=204)
def delete_pessoa_fisica(cpf: str, _token: str = Depends(_verificar_token)):
    if _db_pf is None:
        raise _PF_NAO_CONFIGURADO
    if not _db_pf.excluir(cpf):
        raise HTTPException(status_code=404, detail="CPF não encontrado no cadastro.")


# ------------------------------------------------------------------ #
# Factory chamada por __main__.py                                      #
# ------------------------------------------------------------------ #


# ------------------------------------------------------------------ #
# Endpoint — Chat (emissão inteligente via linguagem natural)          #
# ------------------------------------------------------------------ #


class ChatNfseRequest(BaseModel):
    mensagem: str
    historico: list[Any] = []
    api_key: str | None = None
    modelo: str = "gemini/gemini-2.5-flash"


@app.post("/chat")
def post_chat(req: ChatNfseRequest):
    from conta_tools_nfse.chat import responder
    try:
        resultado = responder(req.mensagem, req.historico, req.modelo, req.api_key)
        return resultado
    except Exception as e:
        msg = str(e)
        if any(w in msg.lower() for w in ("api_key", "authentication", "unauthorized", "invalid key", "api key")):
            raise HTTPException(
                status_code=503,
                detail=f"Chave de API inválida ou não configurada para o modelo '{req.modelo}'. {msg}",
            )
        raise HTTPException(status_code=500, detail=msg)


# ------------------------------------------------------------------ #
# Factory chamada por __main__.py                                      #
# ------------------------------------------------------------------ #


def create_app(api_conf: ApiConf) -> FastAPI:
    global _api_conf, _db_pf
    _api_conf = api_conf
    if api_conf.db_pessoas_fisicas is not None:
        from conta_tools_nfse.api.pessoas_fisicas import PessoasFisicasDb
        _db_pf = PessoasFisicasDb(api_conf.db_pessoas_fisicas)

    # Inicializa o módulo MCP para ser chamado diretamente pelo endpoint /chat
    internal_url = f"http://{api_conf.host}:{api_conf.port}"
    try:
        from conta_tools_nfse.mcp.server import inicializar
        inicializar(internal_url, api_conf.bearer_token)
    except ImportError:
        pass  # mcp opcional

    return app
