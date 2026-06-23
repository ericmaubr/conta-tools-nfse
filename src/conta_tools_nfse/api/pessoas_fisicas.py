"""Cadastro de pessoas físicas em SQLite — gerenciado pela API REST."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path


def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


@dataclass
class PessoaFisica:
    cpf: str            # somente dígitos
    nome: str
    logradouro: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    cep: str = ""       # somente dígitos
    municipio: str = ""
    municipio_ibge: str = ""  # código IBGE, somente dígitos
    uf: str = ""        # sigla em maiúsculas
    email: str = ""
    celular: str = ""   # somente dígitos
    fixo: str = ""      # somente dígitos

    def to_dict(self) -> dict:
        return asdict(self)


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pessoa_fisica (
    cpf             TEXT PRIMARY KEY,
    nome            TEXT NOT NULL,
    logradouro      TEXT DEFAULT '',
    numero          TEXT DEFAULT '',
    complemento     TEXT DEFAULT '',
    bairro          TEXT DEFAULT '',
    cep             TEXT DEFAULT '',
    municipio       TEXT DEFAULT '',
    municipio_ibge  TEXT DEFAULT '',
    uf              TEXT DEFAULT '',
    email           TEXT DEFAULT '',
    celular         TEXT DEFAULT '',
    fixo            TEXT DEFAULT '',
    atualizado_em   TEXT DEFAULT (datetime('now'))
);
"""

_UPSERT = """
INSERT INTO pessoa_fisica
    (cpf, nome, logradouro, numero, complemento, bairro, cep,
     municipio, municipio_ibge, uf, email, celular, fixo, atualizado_em)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
ON CONFLICT(cpf) DO UPDATE SET
    nome           = excluded.nome,
    logradouro     = excluded.logradouro,
    numero         = excluded.numero,
    complemento    = excluded.complemento,
    bairro         = excluded.bairro,
    cep            = excluded.cep,
    municipio      = excluded.municipio,
    municipio_ibge = excluded.municipio_ibge,
    uf             = excluded.uf,
    email          = excluded.email,
    celular        = excluded.celular,
    fixo           = excluded.fixo,
    atualizado_em  = datetime('now')
"""


def _row_to_pf(row: sqlite3.Row) -> PessoaFisica:
    return PessoaFisica(
        cpf=row["cpf"],
        nome=row["nome"],
        logradouro=row["logradouro"] or "",
        numero=row["numero"] or "",
        complemento=row["complemento"] or "",
        bairro=row["bairro"] or "",
        cep=row["cep"] or "",
        municipio=row["municipio"] or "",
        municipio_ibge=row["municipio_ibge"] or "",
        uf=row["uf"] or "",
        email=row["email"] or "",
        celular=row["celular"] or "",
        fixo=row["fixo"] or "",
    )


class PessoasFisicasDb:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    def buscar(self, cpf: str) -> PessoaFisica | None:
        row = self._conn.execute(
            "SELECT * FROM pessoa_fisica WHERE cpf = ?", (_somente_digitos(cpf),)
        ).fetchone()
        return _row_to_pf(row) if row else None

    def listar(self) -> list[PessoaFisica]:
        rows = self._conn.execute(
            "SELECT * FROM pessoa_fisica ORDER BY nome COLLATE NOCASE"
        ).fetchall()
        return [_row_to_pf(r) for r in rows]

    def salvar(self, pf: PessoaFisica) -> PessoaFisica:
        self._conn.execute(
            _UPSERT,
            (
                _somente_digitos(pf.cpf),
                pf.nome.strip(),
                pf.logradouro.strip(),
                pf.numero.strip(),
                pf.complemento.strip(),
                pf.bairro.strip(),
                _somente_digitos(pf.cep),
                pf.municipio.strip(),
                _somente_digitos(pf.municipio_ibge),
                pf.uf.strip().upper(),
                pf.email.strip(),
                _somente_digitos(pf.celular),
                _somente_digitos(pf.fixo),
            ),
        )
        self._conn.commit()
        return self.buscar(_somente_digitos(pf.cpf))  # type: ignore[return-value]

    def excluir(self, cpf: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM pessoa_fisica WHERE cpf = ?", (_somente_digitos(cpf),)
        )
        self._conn.commit()
        return cur.rowcount > 0
