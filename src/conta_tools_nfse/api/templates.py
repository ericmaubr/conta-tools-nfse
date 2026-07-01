"""Banco de templates de emissão de NFS-e (SQLite separado)."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS template (
    id                          TEXT PRIMARY KEY,
    nome                        TEXT NOT NULL,
    descricao                   TEXT,
    categoria                   TEXT NOT NULL,
    prestador_id                TEXT,
    tomador_cnpj                TEXT,
    tomador_cpf                 TEXT,
    tomador_razao_social        TEXT,
    tomador_email               TEXT,
    tomador_logradouro          TEXT,
    tomador_numero              TEXT,
    tomador_complemento         TEXT,
    tomador_bairro              TEXT,
    tomador_cep                 TEXT,
    tomador_municipio_ibge      TEXT,
    tomador_uf                  TEXT,
    discriminacao               TEXT,
    codigo_servico              TEXT,
    codigo_cnae                 TEXT,
    codigo_tributacao_municipio TEXT,
    valor_servico               TEXT,
    iss_retido                  INTEGER,
    valor_iss                   TEXT,
    valor_pis                   TEXT,
    valor_cofins                TEXT,
    valor_inss                  TEXT,
    valor_ir                    TEXT,
    valor_csll                  TEXT,
    valor_outras_retencoes      TEXT,
    criado_em                   TEXT DEFAULT (datetime('now')),
    atualizado_em               TEXT DEFAULT (datetime('now'))
);
"""

_ORDER_EXPR = """
    CASE categoria
      WHEN 'prestador_cliente' THEN 0
      WHEN 'prestador' THEN 1
      ELSE 2
    END, nome COLLATE NOCASE
"""


@dataclass
class Template:
    id: str
    nome: str
    categoria: str   # 'global' | 'prestador' | 'prestador_cliente'
    descricao: Optional[str] = None
    prestador_id: Optional[str] = None
    tomador_cnpj: Optional[str] = None
    tomador_cpf: Optional[str] = None
    tomador_razao_social: Optional[str] = None
    tomador_email: Optional[str] = None
    tomador_logradouro: Optional[str] = None
    tomador_numero: Optional[str] = None
    tomador_complemento: Optional[str] = None
    tomador_bairro: Optional[str] = None
    tomador_cep: Optional[str] = None
    tomador_municipio_ibge: Optional[str] = None
    tomador_uf: Optional[str] = None
    discriminacao: Optional[str] = None
    codigo_servico: Optional[str] = None
    codigo_cnae: Optional[str] = None
    codigo_tributacao_municipio: Optional[str] = None
    valor_servico: Optional[str] = None
    iss_retido: Optional[bool] = None
    valor_iss: Optional[str] = None
    valor_pis: Optional[str] = None
    valor_cofins: Optional[str] = None
    valor_inss: Optional[str] = None
    valor_ir: Optional[str] = None
    valor_csll: Optional[str] = None
    valor_outras_retencoes: Optional[str] = None
    criado_em: str = ""
    atualizado_em: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _row_to_template(row: sqlite3.Row) -> Template:
    d = dict(row)
    iss_raw = d.get("iss_retido")
    return Template(
        id=d["id"],
        nome=d["nome"],
        categoria=d["categoria"],
        descricao=d.get("descricao"),
        prestador_id=d.get("prestador_id"),
        tomador_cnpj=d.get("tomador_cnpj"),
        tomador_cpf=d.get("tomador_cpf"),
        tomador_razao_social=d.get("tomador_razao_social"),
        tomador_email=d.get("tomador_email"),
        tomador_logradouro=d.get("tomador_logradouro"),
        tomador_numero=d.get("tomador_numero"),
        tomador_complemento=d.get("tomador_complemento"),
        tomador_bairro=d.get("tomador_bairro"),
        tomador_cep=d.get("tomador_cep"),
        tomador_municipio_ibge=d.get("tomador_municipio_ibge"),
        tomador_uf=d.get("tomador_uf"),
        discriminacao=d.get("discriminacao"),
        codigo_servico=d.get("codigo_servico"),
        codigo_cnae=d.get("codigo_cnae"),
        codigo_tributacao_municipio=d.get("codigo_tributacao_municipio"),
        valor_servico=d.get("valor_servico"),
        iss_retido=bool(iss_raw) if iss_raw is not None else None,
        valor_iss=d.get("valor_iss"),
        valor_pis=d.get("valor_pis"),
        valor_cofins=d.get("valor_cofins"),
        valor_inss=d.get("valor_inss"),
        valor_ir=d.get("valor_ir"),
        valor_csll=d.get("valor_csll"),
        valor_outras_retencoes=d.get("valor_outras_retencoes"),
        criado_em=d.get("criado_em", ""),
        atualizado_em=d.get("atualizado_em", ""),
    )


def _n(v: Optional[str]) -> Optional[str]:
    """Return None for empty/whitespace strings."""
    if v is None:
        return None
    s = v.strip()
    return s if s else None


class TemplatesDb:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    def listar(self, prestador_id: Optional[str] = None) -> list[Template]:
        """Retorna templates ordenados: prestador_cliente → prestador → global, depois nome."""
        if prestador_id:
            rows = self._conn.execute(
                f"SELECT * FROM template WHERE categoria='global' OR prestador_id=? ORDER BY {_ORDER_EXPR}",
                (prestador_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT * FROM template ORDER BY {_ORDER_EXPR}"
            ).fetchall()
        return [_row_to_template(r) for r in rows]

    def buscar(self, tid: str) -> Optional[Template]:
        row = self._conn.execute("SELECT * FROM template WHERE id=?", (tid,)).fetchone()
        return _row_to_template(row) if row else None

    def criar(self, t: Template) -> Template:
        iss = int(t.iss_retido) if t.iss_retido is not None else None
        self._conn.execute(
            """
            INSERT INTO template
              (id,nome,descricao,categoria,prestador_id,
               tomador_cnpj,tomador_cpf,tomador_razao_social,tomador_email,
               tomador_logradouro,tomador_numero,tomador_complemento,tomador_bairro,
               tomador_cep,tomador_municipio_ibge,tomador_uf,
               discriminacao,codigo_servico,codigo_cnae,codigo_tributacao_municipio,
               valor_servico,iss_retido,valor_iss,
               valor_pis,valor_cofins,valor_inss,valor_ir,valor_csll,valor_outras_retencoes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (t.id, t.nome, _n(t.descricao), t.categoria, _n(t.prestador_id),
             _n(t.tomador_cnpj), _n(t.tomador_cpf), _n(t.tomador_razao_social), _n(t.tomador_email),
             _n(t.tomador_logradouro), _n(t.tomador_numero), _n(t.tomador_complemento), _n(t.tomador_bairro),
             _n(t.tomador_cep), _n(t.tomador_municipio_ibge), _n(t.tomador_uf),
             _n(t.discriminacao), _n(t.codigo_servico), _n(t.codigo_cnae), _n(t.codigo_tributacao_municipio),
             _n(t.valor_servico), iss, _n(t.valor_iss),
             _n(t.valor_pis), _n(t.valor_cofins), _n(t.valor_inss), _n(t.valor_ir), _n(t.valor_csll),
             _n(t.valor_outras_retencoes)),
        )
        self._conn.commit()
        return self.buscar(t.id)  # type: ignore[return-value]

    def atualizar(self, t: Template) -> Optional[Template]:
        if not self.buscar(t.id):
            return None
        iss = int(t.iss_retido) if t.iss_retido is not None else None
        self._conn.execute(
            """
            UPDATE template SET
              nome=?,descricao=?,categoria=?,prestador_id=?,
              tomador_cnpj=?,tomador_cpf=?,tomador_razao_social=?,tomador_email=?,
              tomador_logradouro=?,tomador_numero=?,tomador_complemento=?,tomador_bairro=?,
              tomador_cep=?,tomador_municipio_ibge=?,tomador_uf=?,
              discriminacao=?,codigo_servico=?,codigo_cnae=?,codigo_tributacao_municipio=?,
              valor_servico=?,iss_retido=?,valor_iss=?,
              valor_pis=?,valor_cofins=?,valor_inss=?,valor_ir=?,valor_csll=?,valor_outras_retencoes=?,
              atualizado_em=datetime('now')
            WHERE id=?
            """,
            (t.nome, _n(t.descricao), t.categoria, _n(t.prestador_id),
             _n(t.tomador_cnpj), _n(t.tomador_cpf), _n(t.tomador_razao_social), _n(t.tomador_email),
             _n(t.tomador_logradouro), _n(t.tomador_numero), _n(t.tomador_complemento), _n(t.tomador_bairro),
             _n(t.tomador_cep), _n(t.tomador_municipio_ibge), _n(t.tomador_uf),
             _n(t.discriminacao), _n(t.codigo_servico), _n(t.codigo_cnae), _n(t.codigo_tributacao_municipio),
             _n(t.valor_servico), iss, _n(t.valor_iss),
             _n(t.valor_pis), _n(t.valor_cofins), _n(t.valor_inss), _n(t.valor_ir), _n(t.valor_csll),
             _n(t.valor_outras_retencoes), t.id),
        )
        self._conn.commit()
        return self.buscar(t.id)

    def excluir(self, tid: str) -> bool:
        cur = self._conn.execute("DELETE FROM template WHERE id=?", (tid,))
        self._conn.commit()
        return cur.rowcount > 0
