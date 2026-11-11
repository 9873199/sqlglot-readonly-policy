from sqlglot.optimizer.read_access import ReadPolicy, analyze_read_access
def analyze(sql, **options):
    result = analyze_read_access(sql, ReadPolicy(**options))
    if not result.ok:
        raise PermissionError(result.reason)
    return {(table.catalog, table.schema, table.name) for table in result.tables}
