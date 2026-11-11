"""Exact AST-only policy cases; the adapter only maps the documented result shape."""
import json
from pathlib import Path
import pytest
import sql_adapter as api
CASES=json.loads(Path(__file__).with_name('sql-policy-cases.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('case',CASES['cases'],ids=[str(n+1) for n in range(len(CASES['cases']))])
def test_policy_scope_and_access_set(case):
    options={'allowed_tables':{tuple(t) for t in CASES['allowed_tables']},'default_catalog':CASES['default_catalog'],'default_schema':CASES['default_schema'],'allowed_functions':set(CASES['allowed_pure_functions'])}
    if case['allow']:
        actual=api.analyze(case['sql'],**options)
        assert {tuple(t) for t in actual}=={tuple(t) for t in case['tables']}
    else:
        with pytest.raises(Exception) as caught:api.analyze(case['sql'],**options)
        assert str(caught.value),'No readable refusal reason'

def test_no_tables_is_valid_only_for_a_successfully_analyzed_query():
    options={'allowed_tables':set(),'default_catalog':'app','default_schema':'main','allowed_functions':set()}
    assert set(api.analyze('SELECT 1',**options))==set()
    for sql in ('SELECT * FROM (','SELECT * FROM absent','SELECT 1; DELETE FROM absent'):
        with pytest.raises(Exception):api.analyze(sql,**options)

def test_namespace_disambiguation():
    options={'allowed_tables':{('app','safe','orders')},'default_catalog':'app','default_schema':'safe','allowed_functions':set()}
    assert {tuple(t) for t in api.analyze('SELECT * FROM orders',**options)}=={('app','safe','orders')}
    with pytest.raises(Exception):api.analyze('SELECT * FROM unsafe.orders',**options)
