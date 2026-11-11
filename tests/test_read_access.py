import unittest
from unittest.mock import patch

import sqlglot.optimizer.read_access as read_access_module
from sqlglot.optimizer.read_access import (
    AccessResult,
    ReadAccessAnalyzer,
    ReadPolicy,
    TableRef,
    analyze_read_access,
)

CATALOG = "memory"
SCHEMA = "main"
OTHER_SCHEMA = "other"


def ref(name: str, schema: str = SCHEMA, catalog: str = CATALOG) -> TableRef:
    return TableRef(catalog=catalog, schema=schema, name=name)


ALLOWED_TABLES = {
    (CATALOG, SCHEMA, "allowed"),
    (CATALOG, SCHEMA, "allowed2"),
    (CATALOG, SCHEMA, "allowed3"),
    (CATALOG, SCHEMA, "t"),
}

ALLOWED_FUNCTIONS = {
    "array_filter",
    "array_length",
    "avg",
    "coalesce",
    "count",
    "date_trunc",
    "generate_series",
    "greatest",
    "if",
    "ifnull",
    "json_extract",
    "json_extract_scalar",
    "list_filter",
    "list_transform",
    "lower",
    "max",
    "min",
    "now",
    "range",
    "regexp_like",
    "regexp_matches",
    "row_number",
    "substr",
    "substring",
    "sum",
    "transform",
    "trim",
    "unnest",
    "upper",
}


def make_policy(
    *,
    allowed_tables=ALLOWED_TABLES,
    default_catalog=CATALOG,
    default_schema=SCHEMA,
    allowed_functions=ALLOWED_FUNCTIONS,
) -> ReadPolicy:
    return ReadPolicy(
        allowed_tables=allowed_tables,
        default_catalog=default_catalog,
        default_schema=default_schema,
        allowed_functions=allowed_functions,
    )


class ReadAccessTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = make_policy()
        self.analyzer = ReadAccessAnalyzer(self.policy)

    def assertAccess(self, sql: str, expected: set[TableRef], policy: ReadPolicy | None = None):
        result = analyze_read_access(sql, policy or self.policy)
        self.assertTrue(result.ok, f"unexpected rejection: {result.reason}")
        self.assertIsNotNone(result.tables)
        self.assertEqual(result.tables, frozenset(expected), sql)
        return result

    def assertRejected(
        self,
        sql: str,
        reason_contains: str | None = None,
        policy: ReadPolicy | None = None,
    ):
        result = analyze_read_access(sql, policy or self.policy)
        self.assertFalse(result.ok, f"unexpectedly allowed: {sql} -> {result.tables}")
        # The critical fail-closed property: a rejection never looks like an empty
        # access set.
        self.assertIsNone(result.tables, "a rejection must not return an access set")
        if reason_contains is not None:
            self.assertIn(reason_contains, result.reason or "")
        return result


class ExpectedAccessSetTest(ReadAccessTestCase):
    """Each case states the exact physical access set the query resolves to."""

    def test_single_table_and_qualification_forms(self):
        cases = [
            ("SELECT * FROM allowed", {ref("allowed")}),
            ("SELECT * FROM main.allowed", {ref("allowed")}),
            ("SELECT * FROM memory.main.allowed", {ref("allowed")}),
            ("SELECT * FROM memory.main.allowed AS a", {ref("allowed")}),
            ("SELECT * FROM allowed AS a", {ref("allowed")}),
            ('SELECT * FROM "allowed"', {ref("allowed")}),
            ('SELECT * FROM "memory"."main"."allowed"', {ref("allowed")}),
        ]
        for sql, expected in cases:
            with self.subTest(sql=sql):
                self.assertAccess(sql, expected)

    def test_joins_and_set_operations(self):
        cases = [
            (
                "SELECT * FROM allowed JOIN allowed2 b ON allowed.id = b.id",
                {ref("allowed"), ref("allowed2")},
            ),
            ("SELECT * FROM allowed, allowed2", {ref("allowed"), ref("allowed2")}),
            (
                "SELECT * FROM allowed UNION ALL SELECT * FROM allowed2",
                {ref("allowed"), ref("allowed2")},
            ),
            (
                "SELECT * FROM allowed EXCEPT SELECT * FROM allowed2",
                {ref("allowed"), ref("allowed2")},
            ),
            (
                "SELECT * FROM allowed UNION ALL "
                "(WITH allowed AS (SELECT * FROM allowed2) SELECT * FROM allowed)",
                {ref("allowed"), ref("allowed2")},
            ),
        ]
        for sql, expected in cases:
            with self.subTest(sql=sql):
                self.assertAccess(sql, expected)

    def test_derived_tables_and_subqueries(self):
        cases = [
            ("SELECT * FROM (SELECT * FROM allowed) AS d", {ref("allowed")}),
            (
                "SELECT * FROM (SELECT * FROM (SELECT * FROM allowed) a) b",
                {ref("allowed")},
            ),
            (
                "SELECT * FROM allowed WHERE EXISTS (SELECT 1 FROM allowed2)",
                {ref("allowed"), ref("allowed2")},
            ),
            (
                "SELECT * FROM allowed WHERE id IN (SELECT id FROM allowed2)",
                {ref("allowed"), ref("allowed2")},
            ),
            (
                "SELECT * FROM allowed a WHERE EXISTS "
                "(SELECT 1 FROM allowed2 b WHERE b.id = a.id)",
                {ref("allowed"), ref("allowed2")},
            ),
        ]
        for sql, expected in cases:
            with self.subTest(sql=sql):
                self.assertAccess(sql, expected)

    def test_cte_resolution(self):
        cases = [
            ("WITH cte AS (SELECT * FROM allowed) SELECT * FROM cte", {ref("allowed")}),
            (
                "WITH x AS (SELECT * FROM allowed), y AS (SELECT * FROM x) SELECT * FROM y",
                {ref("allowed")},
            ),
            # A CTE whose name is a physical table shadows that physical table.
            (
                "WITH allowed AS (SELECT * FROM allowed2) SELECT * FROM allowed",
                {ref("allowed2")},
            ),
            # The complementary case: a CTE named after an unauthorized physical
            # table shadows that name, and the actual source is authorized.
            (
                "WITH secret AS (SELECT * FROM allowed) SELECT * FROM secret",
                {ref("allowed")},
            ),
            (
                "WITH cte AS (SELECT * FROM allowed) SELECT * FROM cte AS c",
                {ref("allowed")},
            ),
        ]
        for sql, expected in cases:
            with self.subTest(sql=sql):
                self.assertAccess(sql, expected)

    def test_nested_with_scoping(self):
        sql = (
            "WITH x AS (SELECT * FROM allowed) "
            "SELECT * FROM (WITH x AS (SELECT * FROM allowed2) SELECT * FROM x) s "
            "UNION ALL SELECT * FROM x"
        )
        self.assertAccess(sql, {ref("allowed"), ref("allowed2")})

    def test_quoted_identifiers_resolve_like_duckdb(self):
        # DuckDB treats identifiers as case-insensitive even when quoted, so a
        # quoted CTE name and an unquoted reference still denote the same scope.
        cases = [
            (
                'WITH "X" AS (SELECT * FROM allowed) SELECT * FROM "x"',
                {ref("allowed")},
            ),
            (
                'WITH "X" AS (SELECT * FROM allowed) SELECT * FROM x',
                {ref("allowed")},
            ),
            # An untrusted `sqlglot.meta` comment must not disable normalization.
            (
                'WITH /* sqlglot.meta case_sensitive */ "ALLOWED" '
                "AS (SELECT * FROM allowed2) SELECT * FROM \"allowed\"",
                {ref("allowed2")},
            ),
        ]
        for sql, expected in cases:
            with self.subTest(sql=sql):
                self.assertAccess(sql, expected)

    def test_recursive_cte(self):
        sql = (
            "WITH RECURSIVE cnt AS ("
            "  SELECT 1 AS n FROM allowed"
            "  UNION ALL"
            "  SELECT n + 1 FROM cnt WHERE n < 10"
            ") SELECT * FROM cnt"
        )
        self.assertAccess(sql, {ref("allowed")})

    def test_query_with_no_physical_tables(self):
        # A successful scan of a table-free query yields a genuine empty set,
        # which is distinguishable from a failed scan (tables is None).
        for sql in (
            "SELECT 1",
            "SELECT * FROM (VALUES (1), (2))",
            "SELECT COUNT(*) FROM (VALUES (1)) v",
        ):
            with self.subTest(sql=sql):
                result = self.assertAccess(sql, set())
                self.assertEqual(result.tables, frozenset())

    def test_alias_shadowing_does_not_change_the_physical_table(self):
        cases = [
            ("SELECT * FROM allowed AS secret", {ref("allowed")}),
        ]
        for sql, expected in cases:
            with self.subTest(sql=sql):
                self.assertAccess(sql, expected)


class BypassAttemptTest(ReadAccessTestCase):
    """The specific bypass attempts the policy must not let through."""

    def test_authorized_cte_name_cannot_hide_unauthorized_entity(self):
        cases = [
            "WITH allowed AS (SELECT * FROM secret) SELECT * FROM allowed",
            "WITH allowed AS (SELECT * FROM (SELECT * FROM secret) s) SELECT * FROM allowed",
            "WITH allowed AS (SELECT * FROM secret) SELECT * FROM allowed AS shadow",
            'WITH "allowed" AS (SELECT * FROM secret) SELECT * FROM "ALLOWED"',
            'WITH /* sqlglot.meta case_sensitive */ "allowed" '
            "AS (SELECT * FROM secret) SELECT * FROM \"allowed\"",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                result = self.assertRejected(sql, "secret")
                self.assertIn("unauthorized table", result.reason or "")

    def test_cte_in_one_set_operation_arm_cannot_shadow_globally(self):
        # The CTE is scoped to its arm, so the left arm still reads `allowed`,
        # while the right arm's CTE body must be resolved and rejected.
        sql = (
            "SELECT * FROM allowed UNION ALL "
            "(WITH allowed AS (SELECT * FROM secret) SELECT * FROM allowed)"
        )
        self.assertRejected(sql, "secret")

    def test_unreferenced_cte_body_is_still_analyzed(self):
        # Conservative by design: a definition that is never selected from could
        # still be bound by the engine, so it must not become a smuggling channel.
        self.assertRejected(
            "WITH unused AS (SELECT * FROM secret) SELECT * FROM allowed", "secret"
        )

    def test_deeply_nested_subquery_cannot_read_forbidden_table(self):
        sql = (
            "SELECT * FROM allowed "
            "WHERE id IN ("
            "  SELECT id FROM ("
            "    SELECT id FROM ("
            "      SELECT id FROM secret"
            "    ) l1"
            "  ) l2"
            ")"
        )
        result = self.assertRejected(sql, "secret")
        self.assertIn("unauthorized table", result.reason or "")

    def test_recursive_cte_cannot_read_forbidden_table(self):
        sql = (
            "WITH RECURSIVE cnt AS ("
            "  SELECT 1 AS n FROM secret"
            "  UNION ALL"
            "  SELECT n + 1 FROM cnt WHERE n < 10"
            ") SELECT * FROM cnt"
        )
        self.assertRejected(sql, "secret")

    def test_physical_table_alias_cannot_borrow_an_allowed_name(self):
        self.assertRejected("SELECT * FROM secret AS allowed", "unauthorized table")

    def test_explicit_schema_is_not_dropped(self):
        # `other.allowed` must become memory.other.allowed, not memory.main.allowed.
        self.assertRejected("SELECT * FROM other.allowed", "memory.other.allowed")

    def test_qualified_cte_name_is_a_physical_table(self):
        # A CTE name is only in scope for unqualified references.
        sql = "WITH allowed AS (SELECT 1) SELECT * FROM main.allowed"
        self.assertAccess(sql, {ref("allowed")})


class MultipleStatementAndCommentTest(ReadAccessTestCase):
    def test_second_statement_hidden_after_comments_is_rejected(self):
        cases = [
            "SELECT * FROM allowed; -- harmless comment\nSELECT * FROM secret",
            "SELECT * FROM allowed /* harmless */; SELECT * FROM secret",
            "SELECT * FROM allowed -- comment\n; SELECT * FROM secret",
            "SELECT * FROM allowed; /* ; */ SELECT * FROM allowed2",
            "SELECT * FROM allowed;;SELECT * FROM allowed2",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                self.assertRejected(sql, "exactly one statement")

    def test_comments_inside_a_single_statement_are_allowed(self):
        cases = [
            "/* leading */ SELECT * FROM allowed",
            "SELECT * FROM allowed /* trailing */",
            "SELECT * FROM allowed /* ; */",
            "SELECT * FROM allowed; -- trailing comment only",
            "SELECT * FROM allowed;\n/* trailing comment only */",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                self.assertAccess(sql, {ref("allowed")})


class UnsupportedStatementTest(ReadAccessTestCase):
    def test_non_query_statements_are_rejected(self):
        cases = [
            "ATTACH 'x.db' AS x",
            "DETACH x",
            "COPY allowed TO 'x.csv'",
            "PRAGMA table_info('allowed')",
            "CREATE TABLE x AS SELECT * FROM allowed",
            "CREATE VIEW v AS SELECT * FROM allowed",
            "INSERT INTO allowed SELECT * FROM allowed2",
            "UPDATE allowed SET x = 1",
            "DELETE FROM allowed",
            "DROP TABLE allowed",
            "ALTER TABLE allowed ADD COLUMN x INT",
            "SET x = 1",
            "SUMMARIZE allowed",
            "DESCRIBE allowed",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                result = self.assertRejected(sql)
                self.assertIn("only read-only queries are allowed", result.reason or "")

    def test_locking_read_is_rejected(self):
        for sql in ("SELECT * FROM allowed FOR UPDATE", "SELECT * FROM allowed FOR SHARE"):
            with self.subTest(sql=sql):
                self.assertRejected(sql, "locking reads")


class ExternalAccessTest(ReadAccessTestCase):
    def test_file_scanning_table_functions_are_rejected(self):
        cases = [
            "SELECT * FROM read_csv('x.csv')",
            "SELECT * FROM read_csv_auto('x.csv')",
            "SELECT * FROM read_parquet('x.parquet')",
            "SELECT * FROM read_json_auto('x.json')",
            "SELECT * FROM glob('*.csv')",
            "SELECT * FROM sqlite_scan('x.db', 't')",
            "SELECT * FROM query_table('allowed')",
            "SELECT read_csv('x.csv') FROM allowed",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                self.assertRejected(sql, "not allowed")

    def test_file_scan_functions_cannot_be_allow_listed(self):
        policy = make_policy(allowed_functions=set(ALLOWED_FUNCTIONS) | {"read_csv", "glob"})
        for sql in ("SELECT * FROM read_csv('x.csv')", "SELECT * FROM glob('*.csv')"):
            with self.subTest(sql=sql):
                self.assertRejected(sql, "file-scanning", policy=policy)

    def test_string_literal_table_sources_are_file_scans(self):
        cases = [
            "SELECT * FROM 'x.csv'",
            "SELECT * FROM ''",
            "SELECT * FROM allowed, 'x.csv'",
            "SELECT * FROM allowed JOIN 'x.csv' t ON 1",
            "SELECT * FROM ONLY 'x.csv'",
            "SELECT * FROM (TABLE 'x.csv')",
            "WITH cte AS (SELECT * FROM 'x.csv') SELECT * FROM cte",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                self.assertRejected(sql, "file scan")

    def test_tvf_must_be_explicitly_allow_listed(self):
        self.assertAccess("SELECT * FROM range(5)", set())
        self.assertAccess("SELECT * FROM generate_series(1, 10)", set())
        self.assertAccess("SELECT * FROM unnest([1, 2])", set())
        self.assertRejected("SELECT * FROM unknown_tvf(5)", "table-valued function")

    def test_qualified_tvf_requires_qualified_allow_list_entry(self):
        bare = make_policy(allowed_functions={"my_tvf"})
        self.assertRejected(
            "SELECT * FROM main.my_tvf(5)", "table-valued function", policy=bare
        )
        qualified = make_policy(allowed_functions={"main.my_tvf"})
        self.assertAccess("SELECT * FROM main.my_tvf(5)", set(), policy=qualified)


class FunctionPolicyTest(ReadAccessTestCase):
    def test_unapproved_scalar_functions_are_rejected(self):
        cases = [
            "SELECT my_udf(x) FROM allowed",
            "SELECT nextval('s') FROM allowed",
            'SELECT "my_udf"(x) FROM allowed',
            "SELECT * FROM allowed WHERE EXISTS (SELECT my_udf(x) FROM allowed2)",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                result = self.assertRejected(sql, "function is not allowed")
                self.assertIn("explicitly allow-listed", result.reason or "")

    def test_allow_listed_functions_are_accepted(self):
        cases = [
            "SELECT COUNT(*) FROM allowed",
            "SELECT SUM(x), AVG(x), MIN(x), MAX(x) FROM allowed",
            "SELECT UPPER(x), LOWER(x), COALESCE(x, 1), IFNULL(x, 1) FROM allowed",
            "SELECT DATE_TRUNC('day', x) FROM allowed",
            "SELECT ROW_NUMBER() OVER (ORDER BY x) FROM allowed",
            "SELECT NOW() FROM allowed",
            "SELECT LIST_TRANSFORM([1, 2], x -> x + 1) FROM allowed",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                self.assertAccess(sql, {ref("allowed")})

    def test_function_aliases_are_matched(self):
        # SQLGlot canonicalizes DATE_TRUNC to TimestampTrunc; callers may allow
        # either its canonical or its DuckDB spelling.
        policy = make_policy(allowed_functions={"timestamp_trunc"})
        self.assertAccess(
            "SELECT DATE_TRUNC('day', x) FROM allowed", {ref("allowed")}, policy=policy
        )
        policy = make_policy(allowed_functions={"date_trunc"})
        self.assertAccess(
            "SELECT DATE_TRUNC('day', x) FROM allowed", {ref("allowed")}, policy=policy
        )

    def test_syntax_constructs_do_not_require_function_allow_listing(self):
        policy = make_policy(allowed_functions=set())
        cases = [
            "SELECT CAST(x AS INT) FROM allowed",
            "SELECT TRY_CAST(x AS INT) FROM allowed",
            "SELECT CASE WHEN x THEN 1 ELSE 2 END FROM allowed",
            "SELECT x AND y, x OR y FROM allowed",
            "SELECT x IS NULL, x BETWEEN 1 AND 2, x IN (1, 2) FROM allowed",
            "SELECT [1, 2], {'a': 1} FROM allowed",
            "SELECT EXISTS(SELECT 1) FROM allowed",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                result = analyze_read_access(sql, policy)
                self.assertTrue(result.ok, f"{sql}: {result.reason}")
                self.assertEqual(result.tables, frozenset({ref("allowed")}))

    def test_qualified_function_requires_qualified_allow_list_entry(self):
        # A bare allow-list entry must not authorize `main.my_udf`.
        bare = make_policy(allowed_functions={"my_udf"})
        self.assertRejected(
            "SELECT main.my_udf(x) FROM allowed", "function is not allowed", policy=bare
        )
        qualified = make_policy(allowed_functions={"main.my_udf"})
        self.assertAccess(
            "SELECT main.my_udf(x) FROM allowed", {ref("allowed")}, policy=qualified
        )

    def test_standalone_if_requires_allow_listing(self):
        policy = make_policy(allowed_functions=set())
        self.assertRejected(
            "SELECT IF(x, 1, 2) FROM allowed",
            "function is not allowed",
            policy=policy,
        )
        policy = make_policy(allowed_functions={"if"})
        self.assertAccess("SELECT IF(x, 1, 2) FROM allowed", {ref("allowed")}, policy=policy)


class DefaultNamespaceTest(ReadAccessTestCase):
    def test_uniform_completion_of_unqualified_names(self):
        expected = {ref("allowed")}
        for sql in (
            "SELECT * FROM allowed",
            "SELECT * FROM main.allowed",
            "SELECT * FROM memory.main.allowed",
        ):
            with self.subTest(sql=sql):
                self.assertAccess(sql, expected)

    def test_missing_default_schema_is_deterministic_rejection(self):
        policy = make_policy(default_schema=None)
        self.assertRejected("SELECT * FROM allowed", "no default schema", policy=policy)

    def test_missing_default_catalog_is_deterministic_rejection(self):
        policy = make_policy(default_catalog=None)
        self.assertRejected("SELECT * FROM main.allowed", "no default catalog", policy=policy)

    def test_fully_qualified_table_needs_no_defaults(self):
        policy = make_policy(default_catalog=None, default_schema=None)
        self.assertAccess("SELECT * FROM memory.main.allowed", {ref("allowed")}, policy=policy)


class FailClosedTest(ReadAccessTestCase):
    def test_parse_failure_is_rejected_not_an_empty_set(self):
        result = self.assertRejected("SELECT * FROM", "cannot parse SQL")
        self.assertIsNone(result.tables)

    def test_empty_and_comment_only_input_is_rejected(self):
        for sql in ("", "   ", "-- only a comment", "/* only a comment */"):
            with self.subTest(sql=sql):
                self.assertRejected(sql, "no statement")

    def test_scope_builder_returning_nothing_is_rejected(self):
        with patch.object(read_access_module, "traverse_scope", return_value=[]):
            result = self.analyzer.analyze("SELECT * FROM allowed")
        self.assertFalse(result.ok)
        self.assertIsNone(result.tables)
        self.assertIn("could not build a query scope", result.reason or "")

    def test_scope_builder_raising_is_rejected(self):
        with patch.object(
            read_access_module, "traverse_scope", side_effect=RuntimeError("scope exploded")
        ):
            result = self.analyzer.analyze("SELECT * FROM allowed")
        self.assertFalse(result.ok)
        self.assertIsNone(result.tables)
        self.assertIn("analysis failed", result.reason or "")
        self.assertIn("scope exploded", result.reason or "")

    def test_unauthorized_table_rejection_has_no_tables(self):
        result = self.assertRejected("SELECT * FROM secret")
        self.assertIsNone(result.tables)


class ConvenienceApiTest(ReadAccessTestCase):
    def test_function_and_class_agree(self):
        sql = "WITH cte AS (SELECT * FROM allowed) SELECT * FROM cte"
        by_function = analyze_read_access(sql, self.policy)
        by_class = self.analyzer.analyze(sql)
        self.assertEqual(by_function, by_class)
        self.assertEqual(by_function.tables, frozenset({ref("allowed")}))

    def test_readable_description(self):
        result = AccessResult(ok=True, tables=frozenset({ref("allowed"), ref("allowed2")}))
        self.assertEqual(
            result.describe_tables(), "memory.main.allowed, memory.main.allowed2"
        )

    def test_example_does_not_connect_to_a_database(self):
        # This is the documented usage example: parse + scope analysis only.
        policy = ReadPolicy(
            allowed_tables={("memory", "main", "sales")},
            default_catalog="memory",
            default_schema="main",
            allowed_functions={"sum"},
        )
        result = analyze_read_access(
            "WITH total AS (SELECT SUM(amount) AS n FROM sales) SELECT * FROM total",
            policy,
        )
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.tables, frozenset({TableRef("memory", "main", "sales")}))


if __name__ == "__main__":
    unittest.main()
