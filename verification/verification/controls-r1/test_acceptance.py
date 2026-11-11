from unittest.mock import patch
import pytest
import sqlglot.optimizer.read_access as native

def policy(**kw):
    options=dict(allowed_tables={('app','main','orders'),('app','main','customers')},default_catalog='app',default_schema='main',allowed_functions={'COUNT','ABS','SUM'})
    options.update(kw)
    return native.ReadPolicy(**options)

@pytest.mark.parametrize('mode',['empty','raise'])
def test_scope_failure_is_explicit_rejection(mode):
    options={'return_value':[]} if mode=='empty' else {'side_effect':RuntimeError('independent scope failure')}
    with patch.object(native,'traverse_scope',**options):
        result=native.ReadAccessAnalyzer(policy()).analyze('SELECT * FROM orders')
    assert result.ok is False and result.tables is None and result.reason

def test_reused_analyzer_has_no_state_leak_after_rejection():
    analyzer=native.ReadAccessAnalyzer(policy())
    for sql in ['SELECT * FROM secret','SELECT * FROM (','SELECT * FROM orders; DELETE FROM orders']:
        result=analyzer.analyze(sql)
        assert result.ok is False and result.tables is None and result.reason
        result=analyzer.analyze('SELECT * FROM customers')
        assert result.ok and result.tables==frozenset({native.TableRef('app','main','customers')})

@pytest.mark.parametrize('defaults',[{'default_catalog':None},{'default_schema':None}])
def test_missing_namespace_refuses_but_qualified_reference_works(defaults):
    analyzer=native.ReadAccessAnalyzer(policy(**defaults))
    result=analyzer.analyze('SELECT * FROM orders')
    assert not result.ok and result.tables is None and result.reason
    result=analyzer.analyze('SELECT * FROM app.main.orders')
    assert result.ok and result.tables==frozenset({native.TableRef('app','main','orders')})

@pytest.mark.parametrize('sql',[
    "SELECT * FROM read_csv('private.csv')",
    "SELECT * FROM query_table('secret')",
    "SELECT * FROM 'private.csv'",
])
def test_external_scans_are_refused_even_with_matching_allowlist(sql):
    analyzer=native.ReadAccessAnalyzer(policy(allowed_tables={('app','main','private.csv')},allowed_functions={'read_csv','query_table'}))
    result=analyzer.analyze(sql)
    assert not result.ok and result.tables is None and result.reason

def test_untrusted_case_sensitive_directive_does_not_change_identity():
    result=native.ReadAccessAnalyzer(policy()).analyze('WITH /* sqlglot.meta case_sensitive */ "Orders" AS (SELECT * FROM secret) SELECT * FROM "ORDERS"')
    assert not result.ok and result.tables is None and 'secret' in result.reason

def test_unknown_function_in_correlated_subquery_is_not_skipped():
    result=native.ReadAccessAnalyzer(policy()).analyze('SELECT * FROM orders o WHERE EXISTS (SELECT unknown_udf(c.id) FROM customers c WHERE c.id=o.id)')
    assert not result.ok and result.tables is None and result.reason

def test_uppercase_policy_and_class_convenience_agree():
    p=policy(allowed_tables={('APP','MAIN','ORDERS')},default_catalog='APP',default_schema='MAIN')
    sql='SELECT COUNT(*) FROM "ORDERS"'
    first=native.analyze_read_access(sql,p)
    second=native.ReadAccessAnalyzer(p).analyze(sql)
    assert first==second and first.ok
    assert first.tables==frozenset({native.TableRef('app','main','orders')})
