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


async def resolve_account_or_customer(conn: oracledb.AsyncConnection,
                                      identifier: str) -> int:
    """Resolve an ACCOUNT_ID from either an account number OR a customer number.

    Users often say "change the account status for customer CUST000150" — i.e.
    they give a customer number where an account is expected. We try the account
    number first; if that misses, we look the value up as a customer and use
    their account when there is exactly one. With several accounts we raise a
    helpful error listing them so the caller can pick.
    """
    # 1) Direct account-number hit.
    with conn.cursor() as cur:
        await cur.execute(
            "SELECT ACCOUNT_ID FROM MCP_APP.ACCOUNT "
            "WHERE UPPER(ACCOUNT_NUMBER) = UPPER(:1)",
            [identifier],
        )
        row = await cur.fetchone()
    if row is not None:
        return int(row[0])

    # 2) Maybe it's a customer number — resolve to their account(s).
    with conn.cursor() as cur:
        await cur.execute(
            "SELECT a.ACCOUNT_ID, a.ACCOUNT_NUMBER "
            "FROM   MCP_APP.ACCOUNT a "
            "JOIN   MCP_APP.CUSTOMER c ON c.CUSTOMER_ID = a.CUSTOMER_ID "
            "WHERE  UPPER(c.CUSTOMER_NUMBER) = UPPER(:1) "
            "ORDER BY a.ACCOUNT_NUMBER",
            [identifier],
        )
        accounts = await cur.fetchall()

    if len(accounts) == 1:
        return int(accounts[0][0])
    if len(accounts) > 1:
        nums = ", ".join(a[1] for a in accounts)
        raise ValueError(
            f"'{identifier}' is a customer with multiple accounts ({nums}). "
            f"Please specify which account number.")
    raise ValueError(f"Account '{identifier}' not found")


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
