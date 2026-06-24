"""
TASK 04 — Schema Introspection Tools (Group L)
Unit tests: T04-01 through T04-10
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_exec_mock(rows: list[dict]):
    """Patch src.tools.schema._exec to return *rows*."""
    return patch("src.tools.schema._exec", new_callable=AsyncMock, return_value=rows)


def _make_audit_mock():
    return patch("src.tools.schema.log_audit", new_callable=AsyncMock, return_value=True)


# ── T04-01: list_tables returns expected count ────────────────────────────────

@pytest.mark.asyncio
async def test_t04_01_list_tables_returns_count():
    fake_tables = [{"table_name": f"TBL{i}", "row_count": i * 10, "comments": None}
                   for i in range(20)]
    with _make_exec_mock(fake_tables), _make_audit_mock():
        from src.tools.schema import list_tables
        result = await list_tables()
    assert result["success"] is True
    assert result["row_count"] == 20
    assert len(result["data"]) == 20


# ── T04-02: describe_table returns columns ────────────────────────────────────

@pytest.mark.asyncio
async def test_t04_02_describe_table_customer_columns():
    fake_cols = [
        {"column_name": "CUSTOMER_ID", "data_type": "NUMBER"},
        {"column_name": "CUSTOMER_NUMBER", "data_type": "VARCHAR2"},
        {"column_name": "CUSTOMER_NAME", "data_type": "VARCHAR2"},
        {"column_name": "STATUS", "data_type": "VARCHAR2"},
        {"column_name": "CUSTOMER_TYPE_ID", "data_type": "NUMBER"},
        {"column_name": "INV_COMPANY_ID", "data_type": "NUMBER"},
        {"column_name": "CREATED_DTM", "data_type": "DATE"},
    ]
    # describe_table calls _exec twice (cols + constraints)
    with patch("src.tools.schema._exec", new_callable=AsyncMock,
               side_effect=[fake_cols, []]), _make_audit_mock():
        from src.tools.schema import describe_table
        result = await describe_table("CUSTOMER")
    assert result["success"] is True
    assert result["row_count"] == 7
    assert result["data"]["table_name"] == "CUSTOMER"
    assert len(result["data"]["columns"]) == 7


# ── T04-03: describe_table for non-existent table returns not-found ───────────

@pytest.mark.asyncio
async def test_t04_03_describe_table_not_found():
    with patch("src.tools.schema._exec", new_callable=AsyncMock,
               side_effect=[[], []]), _make_audit_mock():
        from src.tools.schema import describe_table
        result = await describe_table("NONEXISTENT")
    assert result["success"] is True
    assert result["data"] is None
    assert result["row_count"] == 0


# ── T04-04: list_packages returns packages ────────────────────────────────────

@pytest.mark.asyncio
async def test_t04_04_list_packages():
    fake_pkgs = [{"package_name": f"PKG_{i}", "status": "VALID"} for i in range(9)]
    with _make_exec_mock(fake_pkgs), _make_audit_mock():
        from src.tools.schema import list_packages
        result = await list_packages()
    assert result["success"] is True
    assert result["row_count"] == 9


# ── T04-05: list_package_procedures for BILLING_PKG returns procedures ─────────

@pytest.mark.asyncio
async def test_t04_05_list_package_procedures_billing():
    fake_procs = [
        {"procedure_name": "GENERATE_BILL"},
        {"procedure_name": "GET_BILL_DETAILS"},
        {"procedure_name": "UPDATE_BILL_STATUS"},
    ]
    with _make_exec_mock(fake_procs), _make_audit_mock():
        from src.tools.schema import list_package_procedures
        result = await list_package_procedures("BILLING_PKG")
    assert result["success"] is True
    assert result["row_count"] == 3
    names = [r["procedure_name"] for r in result["data"]]
    assert "GENERATE_BILL" in names


# ── T04-06: get_procedure_signature returns parameters ────────────────────────

@pytest.mark.asyncio
async def test_t04_06_get_procedure_signature_generate_bill():
    fake_args = [
        {"argument_name": "P_ACCOUNT_ID", "position": 1, "in_out": "IN",
         "data_type": "NUMBER", "default_value": None},
        {"argument_name": "P_BILLING_MONTH", "position": 2, "in_out": "IN",
         "data_type": "DATE", "default_value": None},
        {"argument_name": "P_BILL_ID", "position": 3, "in_out": "OUT",
         "data_type": "NUMBER", "default_value": None},
        {"argument_name": "P_STATUS", "position": 4, "in_out": "OUT",
         "data_type": "VARCHAR2", "default_value": None},
    ]
    with _make_exec_mock(fake_args), _make_audit_mock():
        from src.tools.schema import get_procedure_signature
        result = await get_procedure_signature("BILLING_PKG", "GENERATE_BILL")
    assert result["success"] is True
    assert result["row_count"] == 4


# ── T04-07: list_sequences returns sequences ──────────────────────────────────

@pytest.mark.asyncio
async def test_t04_07_list_sequences():
    fake_seqs = [{"sequence_name": f"SEQ_{i}", "min_value": 1,
                  "max_value": 9999999, "increment_by": 1, "last_number": 100}
                 for i in range(19)]
    with _make_exec_mock(fake_seqs), _make_audit_mock():
        from src.tools.schema import list_sequences
        result = await list_sequences()
    assert result["success"] is True
    assert result["row_count"] == 19


# ── T04-08: list_indexes for ACCOUNT returns indexes ─────────────────────────

@pytest.mark.asyncio
async def test_t04_08_list_indexes_for_account():
    fake_idxs = [
        {"index_name": "SYS_C001", "table_name": "ACCOUNT",
         "uniqueness": "UNIQUE", "column_name": "ACCOUNT_ID", "index_type": "NORMAL"},
        {"index_name": "IDX_ACC_NUM", "table_name": "ACCOUNT",
         "uniqueness": "UNIQUE", "column_name": "ACCOUNT_NUMBER", "index_type": "NORMAL"},
    ]
    with _make_exec_mock(fake_idxs), _make_audit_mock():
        from src.tools.schema import list_indexes
        result = await list_indexes("ACCOUNT")
    assert result["success"] is True
    assert result["row_count"] == 2
    assert all(r["table_name"] == "ACCOUNT" for r in result["data"])


# ── T04-09: find_procedure_for_table returns package source lines ─────────────

@pytest.mark.asyncio
async def test_t04_09_find_procedure_for_table_bill_summary():
    fake_src = [
        {"object_name": "BILLING_PKG", "object_type": "PACKAGE BODY",
         "line_number": 42, "source_line": "  INSERT INTO BILL_SUMMARY ..."},
        {"object_name": "BILLING_PKG", "object_type": "PACKAGE BODY",
         "line_number": 55, "source_line": "  SELECT * FROM BILL_SUMMARY ..."},
    ]
    with _make_exec_mock(fake_src), _make_audit_mock():
        from src.tools.schema import find_procedure_for_table
        result = await find_procedure_for_table("BILL_SUMMARY")
    assert result["success"] is True
    assert result["row_count"] == 2
    assert any("BILLING_PKG" in r["object_name"] for r in result["data"])


# ── T04-10: Every tool call creates an audit entry (mock verify) ──────────────

@pytest.mark.asyncio
async def test_t04_10_list_tables_calls_audit():
    with _make_exec_mock([]), \
         patch("src.tools.schema.log_audit", new_callable=AsyncMock) as mock_audit:
        from src.tools.schema import list_tables
        await list_tables()
    mock_audit.assert_called_once()
    call_args = mock_audit.call_args[0]
    assert call_args[0] == "schema"   # tool_name
    assert call_args[3] == "READ"     # action_type


@pytest.mark.asyncio
async def test_t04_10_describe_table_calls_audit():
    with patch("src.tools.schema._exec", new_callable=AsyncMock,
               side_effect=[[], []]), \
         patch("src.tools.schema.log_audit", new_callable=AsyncMock) as mock_audit:
        from src.tools.schema import describe_table
        await describe_table("CUSTOMER")
    mock_audit.assert_called_once()
    assert mock_audit.call_args[0][3] == "READ"


# ── Integration tests (live Oracle DB) ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.integration
async def test_t04_01_integration_list_tables_20(db_conn):
    from src.tools.schema import list_tables
    result = await list_tables()
    assert result["success"] is True
    assert result["row_count"] >= 20


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t04_02_integration_describe_customer(db_conn):
    from src.tools.schema import describe_table
    result = await describe_table("CUSTOMER")
    assert result["success"] is True
    assert result["data"] is not None
    col_names = [c["column_name"] for c in result["data"]["columns"]]
    assert "CUSTOMER_ID" in col_names


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t04_04_integration_list_packages_9(db_conn):
    from src.tools.schema import list_packages
    result = await list_packages()
    assert result["success"] is True
    assert result["row_count"] >= 9


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t04_05_integration_billing_pkg_procedures(db_conn):
    from src.tools.schema import list_package_procedures
    result = await list_package_procedures("BILLING_PKG")
    assert result["success"] is True
    names = [r["procedure_name"] for r in result["data"]]
    assert "GENERATE_BILL" in names


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t04_07_integration_list_sequences_19(db_conn):
    from src.tools.schema import list_sequences
    result = await list_sequences()
    assert result["success"] is True
    assert result["row_count"] >= 19


@pytest.mark.asyncio
@pytest.mark.integration
async def test_t04_09_integration_find_procedure_bill_summary(db_conn):
    from src.tools.schema import find_procedure_for_table
    result = await find_procedure_for_table("BILL_SUMMARY")
    assert result["success"] is True
    assert result["row_count"] > 0
