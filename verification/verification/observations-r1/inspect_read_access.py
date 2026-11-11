from sqlglot.optimizer.read_access import ReadPolicy, ReadAccessAnalyzer
policy=ReadPolicy(allowed_tables={('app','main','orders'),('app','main','customers')},default_catalog='app',default_schema='main',allowed_functions={'COUNT','SUM'})
analyzer=ReadAccessAnalyzer(policy)
queries=[
    'WITH orders AS (SELECT * FROM customers) SELECT * FROM orders',
    'WITH orders AS (SELECT * FROM secret) SELECT * FROM orders',
    'SELECT * FROM orders WHERE id IN (SELECT id FROM secret)',
    'WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r WHERE n<3) SELECT * FROM r',
    "SELECT * FROM read_csv('private.csv')",
    'SELECT 1; -- another statement\nDELETE FROM orders',
    'SELECT * FROM (',
    'SELECT 1',
]
for sql in queries:
    result=analyzer.analyze(sql)
    print('SQL:',sql)
    print('Allowed:',result.ok,'Tables:',None if result.tables is None else sorted(map(str,result.tables)))
    print('Reason:',result.reason)
    print()
