"""ID resolvers — convert human-readable business codes to Oracle numeric PKs.

All resolvers are case-insensitive and raise ValueError with the invalid value
included in the message on failure. Each accepts an open AsyncConnection so
callers can reuse their existing transaction.
"""
import oracledb


async def resolve_customer_number(conn: oracledb.AsyncConnection, customer_number: str) -> int:
    with conn.cursor() as cur:
        await cur.execute(
            "SELECT CUSTOMER_ID FROM MCP_APP.CUSTOMER "
            "WHERE UPPER(CUSTOMER_NUMBER) = UPPER(:1)",
            [customer_number],
        )
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"Customer '{customer_number}' not found")
    return int(row[0])


async def resolve_company_code(conn: oracledb.AsyncConnection, company_code: str) -> int:
    with conn.cursor() as cur:
        await cur.execute(
            "SELECT INV_COMPANY_ID FROM MCP_APP.INVOICING_COMPANY "
            "WHERE UPPER(COMPANY_CODE) = UPPER(:1)",
            [company_code],
        )
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"Invoicing company '{company_code}' not found")
    return int(row[0])


async def resolve_currency_code(conn: oracledb.AsyncConnection, currency_code: str) -> int:
    with conn.cursor() as cur:
        await cur.execute(
            "SELECT CURRENCY_ID FROM MCP_APP.CURRENCY "
            "WHERE UPPER(CURRENCY_CODE) = UPPER(:1)",
            [currency_code],
        )
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"Currency '{currency_code}' not found")
    return int(row[0])


async def resolve_account_number(conn: oracledb.AsyncConnection, account_number: str) -> int:
    with conn.cursor() as cur:
        await cur.execute(
            "SELECT ACCOUNT_ID FROM MCP_APP.ACCOUNT "
            "WHERE UPPER(ACCOUNT_NUMBER) = UPPER(:1)",
            [account_number],
        )
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"Account '{account_number}' not found")
    return int(row[0])


async def resolve_product_code(conn: oracledb.AsyncConnection, product_code: str) -> int:
    with conn.cursor() as cur:
        await cur.execute(
            "SELECT PRODUCT_ID FROM MCP_APP.PRODUCT "
            "WHERE UPPER(PRODUCT_CODE) = UPPER(:1)",
            [product_code],
        )
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"Product '{product_code}' not found")
    return int(row[0])


async def resolve_provider_code(conn: oracledb.AsyncConnection, provider_code: str) -> int:
    with conn.cursor() as cur:
        await cur.execute(
            "SELECT PROVIDER_ID FROM MCP_APP.PROVIDER "
            "WHERE UPPER(PROVIDER_CODE) = UPPER(:1)",
            [provider_code],
        )
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"Provider '{provider_code}' not found")
    return int(row[0])


async def resolve_customer_type_code(conn: oracledb.AsyncConnection, type_code: str) -> int:
    with conn.cursor() as cur:
        await cur.execute(
            "SELECT CUSTOMER_TYPE_ID FROM MCP_APP.CUSTOMER_TYPE "
            "WHERE UPPER(CUSTOMER_TYPE_CODE) = UPPER(:1)",
            [type_code],
        )
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"Customer type '{type_code}' not found")
    return int(row[0])
