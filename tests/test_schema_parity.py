"""Paridade entre as CHECK constraints dos modelos e as da base migrada.

Substitui o `diff` manual de dois `pg_dump --schema-only` que se fazia a mao no
fim de cada ronda. Enquanto a migracao 0004 importava `resoiltwin.constraints`,
esse diff era tautologico quanto ao texto das constraints: as duas metades
liam o mesmo modulo em tempo de execucao, portanto nao podiam divergir. Com os
literais congelados dentro das migracoes, a divergencia passou a ser possivel
-- e e este teste que a apanha no dia em que aparecer.

Vale a pena dizer porque e que este teste tem de existir de todo: o
autogenerate do Alembic 1.13 NAO compara CheckConstraints. Uma constraint
alterada no modelo e esquecida na migracao nao aparece em `alembic revision
--autogenerate`, nao aparece em lado nenhum, e so se manifesta na primeira base
construida do zero.

A base contra a qual isto corre e a que o conftest constroi por
`alembic upgrade head`, ou seja o schema real das migracoes.

Metodo de comparacao: em vez de comparar strings escritas por pessoas (que
diferem em parenteses, espacos e ordem sem diferirem em significado), a
expressao declarada no modelo e aplicada a uma tabela temporaria com as mesmas
colunas e depois lida de volta por `pg_get_constraintdef`. Os dois lados sao
assim normalizados pelo mesmo parser do PostgreSQL, e a comparacao e entre o
que o PostgreSQL entendeu de cada um.
"""

import pytest
from sqlalchemy import CheckConstraint, text

from resoiltwin.db import Base
import resoiltwin.models  # noqa: F401  garante que os modelos entram no metadata


def _model_checks() -> dict[tuple[str, str], str]:
    """{(tabela, nome): expressao SQL} das CheckConstraints declaradas nos modelos."""
    return {
        (table.name, constraint.name): str(constraint.sqltext)
        for table in Base.metadata.sorted_tables
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }


def _database_checks(session) -> dict[tuple[str, str], str]:
    """{(tabela, nome): definicao} das CHECK constraints presentes na base.

    Restringido as tabelas dos modelos: a imagem postgis/postgis:16-3.4 traz
    tiger_geocoder e topology, cujas constraints nao pertencem a este schema.
    Constraints NOT NULL nao entram -- no PostgreSQL nao sao contype='c'.
    """
    tables = [t.name for t in Base.metadata.sorted_tables]
    rows = session.execute(
        text(
            "SELECT rel.relname AS table_name, con.conname AS name,"
            "       pg_get_constraintdef(con.oid) AS definition"
            "  FROM pg_constraint con"
            "  JOIN pg_class rel ON rel.oid = con.conrelid"
            "  JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace"
            " WHERE con.contype = 'c'"
            "   AND nsp.nspname = 'public'"
            "   AND rel.relname = ANY(:tables)"
        ),
        {"tables": tables},
    ).all()
    return {(r.table_name, r.name): r.definition for r in rows}


def _normalise(session, table: str, name: str, sqltext: str) -> str:
    """Le de volta, pela boca do PostgreSQL, o que ele entendeu da expressao.

    A tabela temporaria copia as colunas da real (LIKE), o que tambem verifica
    que a expressao do modelo e SQL valido contra essas colunas -- uma
    constraint que referisse uma coluna inexistente rebentava aqui.
    """
    tmp = f"_parity_{table}"
    session.execute(text(f'CREATE TEMP TABLE "{tmp}" (LIKE public."{table}")'))
    session.execute(text(f'ALTER TABLE "{tmp}" ADD CONSTRAINT "{name}" CHECK ({sqltext})'))
    definition = session.execute(
        text(
            "SELECT pg_get_constraintdef(con.oid) AS definition"
            "  FROM pg_constraint con"
            "  JOIN pg_class rel ON rel.oid = con.conrelid"
            " WHERE rel.relnamespace = pg_my_temp_schema()"
            "   AND rel.relname = :tmp AND con.conname = :name"
        ),
        {"tmp": tmp, "name": name},
    ).scalar_one()
    session.execute(text(f'DROP TABLE "{tmp}"'))
    return definition


def test_models_declare_at_least_one_check_constraint():
    """Rede de seguranca do proprio teste: se a recolha deixasse de encontrar
    constraints, os dois testes abaixo ficavam verdes por vacuidade."""
    assert len(_model_checks()) >= 10


@pytest.mark.parametrize("key", sorted(_model_checks()))
def test_model_check_constraint_exists_in_the_migrated_database(session, key):
    table, name = key
    present = _database_checks(session)
    assert key in present, (
        f"a constraint {name} esta declarada no modelo de {table} e nao existe na base "
        "construida pelas migracoes -- falta a migracao que a cria"
    )
    expected = _normalise(session, table, name, _model_checks()[key])
    assert present[key] == expected, (
        f"a constraint {name} da tabela {table} tem definicoes diferentes no modelo e na "
        f"base:\n  modelo: {expected}\n  base:   {present[key]}"
    )


def test_database_has_no_check_constraint_the_models_do_not_declare(session):
    """O sentido inverso: uma migracao que crie uma constraint que os modelos
    nao conhecem faz a base recusar escritas que o codigo julga validas."""
    extra = set(_database_checks(session)) - set(_model_checks())
    assert extra == set(), (
        f"constraints na base que os modelos nao declaram: {sorted(extra)}"
    )
