"""Database-local ACL application for a database physically created by this CI run."""
import re
from pathlib import Path

from psycopg import sql

from .ci_unix_identity import owned_name, require_owned_database


def create_owned_database(admin, receipt, logical, created):
    actual = owned_name(receipt, logical)
    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(actual)))
    created.add(actual)  # No pre-registration: failed CREATE never grants ownership.
    return actual

ROOT = Path(__file__).resolve().parents[3]


def deploy_owned_grants(conn, receipt, logical, actual, created):
    require_owned_database(receipt, logical, actual, created)
    assert conn.exec_driver_sql('SELECT current_database()').scalar_one() == actual
    text = (ROOT / 'deploy/db/roles/grants.sql').read_text()
    local = text[text.index('DO $grants$'):]
    scrub = re.sub(r'--[^\n]*', '', local)
    assert not re.search(r'\b(?:CREATE|ALTER|DROP)\s+(?:ROLE|USER|DATABASE)\b|\bALTER\s+SYSTEM\b', scrub, re.I)
    conn.connection.driver_connection.execute(local)
