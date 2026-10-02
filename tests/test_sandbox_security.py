"""Analysis sandbox: classic escapes are rejected, legitimate analysis works, runaway code is killed."""
import time

import numpy as np
import pandas as pd
import pytest

from src.agents.data_agent.sandbox import SafePythonSandbox

sandbox = SafePythonSandbox(timeout_seconds=6.0)


@pytest.mark.parametrize("code", [
    "().__class__.__mro__[1].__subclasses__()",              # dunder walk to object.__subclasses__
    "x = [].__class__",
    "(lambda: 0).__globals__",
    "'{0.__class__}'.format(1)",                             # str.format attribute smuggling
    "getattr(df, '__class__')",
    "eval('1+1')",
    "exec('x = 1')",
    "type(1)",
    "import importlib",
    "import os",
    "from subprocess import run",
    "import socket",
    "import pickle",
    "import ctypes",
    "open('/etc/passwd')",
    "pd.read_csv('secrets.csv')",
    "pd.read_pickle('x')",
    "df.to_csv('out.csv')",
    "df.to_pickle('out.pkl')",
    "np.load('file.npy', allow_pickle=True)",
    "np.savetxt('out.txt', [1])",
    "pd.io.common.urlopen('http://x')",
    "df.eval('a + 1')",
    "df.query('a > 1')",
    "class A: pass",
    "def f(): return 1",
    "with open('x') as f: pass",
    "global x",
    "x = (y := 3)",
    "await something",
    "__builtins__",
    "df.__dict__",
    "import matplotlib.pyplot as plt; plt.savefig('f.png')",
])
def test_escape_attempts_are_rejected_before_running(code):
    ok, reason = sandbox.validate_code(code)
    assert not ok, code
    assert reason


def test_rejection_messages_name_the_problem():
    assert "forbidden module 'os'" in sandbox.validate_code("import os")[1]
    assert "restricted builtin 'open()'" in sandbox.validate_code("open('x')")[1]
    assert "private attribute '__class__'" in sandbox.validate_code("x.__class__")[1]
    assert "not allowed" in sandbox.validate_code("import json2")[1]


def test_legitimate_analysis_code_is_accepted():
    code = """
import math
from scipy import stats
top = df.groupby('g')['v'].mean().sort_values(ascending=False).head(3)
labels = [f"{k}: {v:.1f}" for k, v in top.items()]
result = top.reset_index()
"""
    assert sandbox.validate_code(code) == (True, None)


def test_dataframe_analysis_returns_a_table():
    df = pd.DataFrame({"g": list("aabbbc"), "v": [1, 2, 3, 4, 5, 60]})
    res = sandbox.execute_sync("result = df.groupby('g')['v'].sum().sort_values(ascending=False).reset_index()", df)
    assert res.success, res.error
    assert res.table["columns"] == ["g", "v"] and res.table["rows"][0] == ["c", 60] and res.table["total_rows"] == 3


def test_comprehensions_can_see_variables_defined_earlier():
    res = sandbox.execute_sync("k = 3\nresult = [i * k for i in range(4)]")
    assert res.success and res.result_data == [0, 3, 6, 9]


def test_series_scalar_and_nan_results():
    df = pd.DataFrame({"v": [1.0, 2.0, np.nan, 4.0]})
    assert sandbox.execute_sync("result = df['v'].mean()", df).result_data == pytest.approx(7 / 3)
    series = sandbox.execute_sync("result = df['v'].describe()", df)
    assert series.table["columns"] == ["index", "value"] and series.table["rows"][0][0] == "count"
    assert sandbox.execute_sync("result = float('nan')").result_data is None
    assert sandbox.execute_sync("import math\nresult = math.sqrt(16)").result_data == 4.0


def test_large_results_are_capped():
    res = sandbox.execute_sync("result = pd.DataFrame({'a': range(5000)})")
    assert len(res.table["rows"]) == 200 and res.table["total_rows"] == 5000


def test_runaway_code_is_killed_at_the_timeout():
    quick = SafePythonSandbox(timeout_seconds=1.0)
    started = time.time()
    res = quick.execute_sync("while True:\n    pass")
    assert not res.success and "vượt quá giới hạn" in res.error
    assert time.time() - started < 12


def test_runtime_errors_are_reported_not_raised():
    res = sandbox.execute_sync("result = df['missing'].sum()", pd.DataFrame({"a": [1]}))
    assert not res.success and "missing" in res.error


def test_print_output_is_captured_and_cannot_corrupt_the_result():
    res = sandbox.execute_sync("print('hello')\nprint('{\"success\": false}')\nresult = 5")
    assert res.success and res.result_data == 5 and "hello" in res.stdout


def test_the_callers_dataframe_is_never_mutated():
    df = pd.DataFrame({"a": [1, 2, 3]})
    sandbox.execute_sync("df['a'] = 0\nresult = 1", df)
    assert df["a"].tolist() == [1, 2, 3]
