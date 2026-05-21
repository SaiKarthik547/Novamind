# CODEBASE_AUDIT

- Generated at: `2026-05-20T15:58:58.781884`
- Repository root: `C:\Users\karth\OneDrive\Desktop\novamindzip`
- Git repository present: `False`
- Python files audited: `55`
- Total Python lines: `26287`

## Honest Assessment

- This repository contains real code, but a large share of the codebase is wrapper/orchestrator logic around external libraries and system tools rather than deep native OS implementation.
- The deepest local logic is in task orchestration, SQLite persistence, command guarding, screen/DPI/canvas heuristics, and some fallback drawing geometry.
- There is no evidence here of kernel-, driver-, or low-level native Windows programming. The 'OS-level' behavior is mostly Python driving `pyautogui`, PowerShell/subprocess, UIA wrappers, OCR, and HTTP APIs.
- Several modules are broad feature surfaces with large dispatch tables. They look ambitious on paper, but much of the implementation depth comes from composing third-party capabilities rather than building them from scratch.

## Top Findings

- `INFO` `main.py:640`: Startup, game manager, and task UI all initialize in the current tree - Latest live checks show `main.py --health`, `main.py --status --headless`, and `main.py --status` all succeed, with the game manager and Qt task window both reaching ready state.
- `INFO` `agents/data_agent.py:28`: The formula-eval, dependency, and verifier persistence defects are fixed - Targeted probes and regression tests confirm `DataAgent` formulas work again, `TaskParser` preserves `depends_on`, and verifier logging writes to memory successfully.
- `MEDIUM` `agents/system_agent.py:279`: System command execution remains broad and shell-based - Real command execution is still routed through `subprocess.Popen(command, shell=shell, ...)`, while `_security_check()` mainly relies on a blocklist. This remains the largest open trust-boundary risk.
- `LOW` `core/llm_router.py:57`: LLM-backed behavior is not fully testable without provider keys - Current startup checks show `0 active provider(s)`. Core initialization works, but tasks that depend on live LLM output still need API keys configured.
- `LOW` `tests/test_core.py:1`: Pytest cleanup is noisy on this OneDrive-backed workspace - Most regression tests now pass, but pytest temp/cache cleanup can still hit `WinError 5` on this workspace. The code paths themselves were re-verified with direct probes and status checks.

## Executed Checks

### `python_version`

- Command: `C:\Users\karth\AppData\Local\Programs\Python\Python312\python.exe --version`
- Return code: `0`

```text
Python 3.12.5
```

### `compileall`

- Command: `C:\Users\karth\AppData\Local\Programs\Python\Python312\python.exe -m compileall -q .`
- Return code: `1`

```text
Can't list '.\\.local\\pytest_tmp'
Can't list '.\\.novamind\\pytest_tmp'
*** Error compiling '.\\agents\\browser_agent.py'...
Sorry: IndentationError: expected an indented block after function definition on line 78 (browser_agent.py, line 80)
*** Error compiling '.\\agents\\system_agent.py'...
Sorry: IndentationError: expected an indented block after function definition on line 214 (system_agent.py, line 220)
```

### `main_health`

- Command: `C:\Users\karth\AppData\Local\Programs\Python\Python312\python.exe main.py --health`
- Return code: `0`

```text

╔══════════════════════════════════════════════════════╗
║   NovaMind v3.0.0 — Autonomous Desktop AI      ║
║   Eyes → Brain → Hands  (Multi-Agent Architecture)  ║
║   EventBus · VerifierAgent · ErrorRecoveryAgent      ║
╚══════════════════════════════════════════════════════╝
{
  "version": "3.0.0",
  "status": "ok",
  "runtime_root": "C:\\Users\\karth\\.novamind",
  "db_exists": true,
  "log_dir_exists": true,
  "disk_free_gb": 100.8,
  "api_keys_found": [],
  "python_version": "3.12.5 (tags/v3.12.5:ff3bc82, Aug  6 2024, 20:45:27) [MSC v.1940 64 bit (AMD64)]"
}
```

### `run_dep_check`

- Command: `C:\Users\karth\AppData\Local\Programs\Python\Python312\python.exe tools/run_dep_check.py`
- Return code: `124`

```text
2026-05-20 15:56:53,242 | numexpr.utils        | INFO    | NumExpr defaulting to 12 threads.
2026-05-20 15:57:39.747884: I tensorflow/core/util/port.cc:153] oneDNN custom operations are on. You may see slightly different numerical results due to floating-point round-off errors from different computation orders. To turn them off, set the environment variable `TF_ENABLE_ONEDNN_OPTS=0`.

TIMEOUT after 60s
```

### `pytest_default`

- Command: `C:\Users\karth\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_core.py -v`
- Return code: `1`

```text
============================= test session starts =============================
platform win32 -- Python 3.12.5, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\karth\AppData\Local\Programs\Python\Python312\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\karth\OneDrive\Desktop\novamindzip
plugins: anyio-4.9.0, langsmith-0.4.31
collecting ... collected 18 items

tests/test_core.py::TestSafeFormulaEval::test_arithmetic_allowed PASSED  [  5%]
tests/test_core.py::TestSafeFormulaEval::test_column_reference_allowed PASSED [ 11%]
tests/test_core.py::TestSafeFormulaEval::test_ternary_allowed PASSED     [ 16%]
tests/test_core.py::TestSafeFormulaEval::test_import_blocked PASSED      [ 22%]
tests/test_core.py::TestSafeFormulaEval::test_unknown_variable_blocked PASSED [ 27%]
tests/test_core.py::TestSafeFormulaEval::test_attribute_access_blocked PASSED [ 33%]
tests/test_core.py::TestSafeFormulaEval::test_add_column_uses_safe_eval PASSED [ 38%]
tests/test_core.py::TestSafeFormulaEval::test_add_column_blocks_injection PASSED [ 44%]
tests/test_core.py::TestErrorRecoveryTimeout::test_doubled_timeout_does_not_inject_to_function_args PASSED [ 50%]
tests/test_core.py::TestErrorRecoveryTimeout::test_recover_generic_returns_plan PASSED [ 55%]
tests/test_core.py::TestErrorRecoveryTimeout::test_classify_timeout_error PASSED [ 61%]
tests/test_core.py::TestMemorySchemaGuard::test_fresh_db_initialises_without_error ERROR [ 66%]
tests/test_core.py::TestMemorySchemaGuard::test_stale_db_is_rebuilt ERROR [ 72%]
tests/test_core.py::TestTaskParserRouting::test_draw_plan_uses_execute_paint_task PASSED [ 77%]
tests/test_core.py::TestTaskParserRouting::test_is_drawing_request_detection PASSED [ 83%]
tests/test_core.py::TestTaskParserRouting::test_color_extraction PASSED  [ 88%]
tests/test_core.py::TestTaskParserRouting::test_fallback_parse_does_not_crash PASSED [ 94%]
tests/test_core.py::TestCanvasClamping::test_dpi_scale_1_in_dpi_aware_process PASSED [100%]

=================================== ERRORS ====================================
_ ERROR at setup of TestMemorySchemaGuard.test_fresh_db_initialises_without_error _

cls = <class '_pytest.runner.CallInfo'>
func = <function call_and_report.<locals>.<lambda> at 0x0000026EF3C5A7A0>
when = 'setup'
reraise = (<class '_pytest.outcomes.Exit'>, <class 'KeyboardInterrupt'>)

    @classmethod
    def from_call(
        cls,
        func: Callable[[], TResult],
        when: Literal["collect", "setup", "call", "teardown"],
        reraise: type[BaseException] | tuple[type[BaseException], ...] | None = None,
    ) -> CallInfo[TResult]:
        """Call func, wrapping the result in a CallInfo.
    
        :param func:
            The function to call. Called without arguments.
        :type func: Callable[[], _pytest.runner.TResult]
        :param when:
            The phase in which the function is called.
        :param reraise:
            Exception or exceptions that shall propagate if raised by the
            function, instead of being wrapped in the CallInfo.
        """
        excinfo = None
        instant = timing.Instant()
        try:
>           result: TResult | None = func()
                                     ^^^^^^

..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\runner.py:353: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\runner.py:245: in <lambda>
    lambda: runtest_hook(item=item, **kwds),
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_hooks.py:512: in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_manager.py:120: in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\logging.py:843: in pytest_runtest_setup
    yield
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\capture.py:895: in pytest_runtest_setup
    return (yield)
            ^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\runner.py:165: in pytest_runtest_setup
    item.session._setupstate.setup(item)
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\runner.py:523: in setup
    col.setup()
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\python.py:1723: in setup
    self._request._fillfixtures()
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:707: in _fillfixtures
    item.funcargs[argname] = self.getfixturevalue(argname)
                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:539: in getfixturevalue
    fixturedef = self._get_active_fixturedef(argname)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:627: in _get_active_fixturedef
    fixturedef.execute(request=subrequest)
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:1110: in execute
    result: FixtureValue = ihook.pytest_fixture_setup(
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_hooks.py:512: in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_manager.py:120: in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py:53: in run_old_style_hookwrapper
    return result.get_result()
           ^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py:38: in run_old_style_hookwrapper
    res = yield
          ^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\setuponly.py:36: in pytest_fixture_setup
    return (yield)
            ^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:1202: in pytest_fixture_setup
    result = call_fixture_func(fixturefunc, request, kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:908: in call_fixture_func
    fixture_result = next(generator)
                     ^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:267: in tmp_path
    path = _mk_tmp(request, tmp_path_factory)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:254: in _mk_tmp
    return factory.mktemp(name, numbered=True)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:130: in mktemp
    basename = self._ensure_relative_to_basetemp(basename)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:111: in _ensure_relative_to_basetemp
    if (self.getbasetemp() / basename).resolve().parent != self.getbasetemp():
        ^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:186: in getbasetemp
    basetemp = make_numbered_dir_with_cleanup(
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:407: in make_numbered_dir_with_cleanup
    raise e
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:388: in make_numbered_dir_with_cleanup
    p = make_numbered_dir(root, prefix, mode)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:229: in make_numbered_dir
    max_existing = max(map(parse_num, find_suffixes(root, prefix)), default=-1)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:188: in extract_suffixes
    for entry in iter:
                 ^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

root = WindowsPath('C:/Users/karth/AppData/Local/Temp/pytest-of-karth')
prefix = 'pytest-'

    def find_prefixed(root: Path, prefix: str) -> Iterator[os.DirEntry[str]]:
        """Find all elements in root that begin with the prefix, case-insensitive."""
        l_prefix = prefix.lower()
>       for x in os.scandir(root):
                 ^^^^^^^^^^^^^^^^
E       PermissionError: [WinError 5] Access is denied: 'C:\\Users\\karth\\AppData\\Local\\Temp\\pytest-of-karth'

..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:176: PermissionError
______ ERROR at setup of TestMemorySchemaGuard.test_stale_db_is_rebuilt _______

cls = <class '_pytest.runner.CallInfo'>
func = <function call_and_report.<locals>.<lambda> at 0x0000026EA89C28E0>
when = 'setup'
reraise = (<class '_pytest.outcomes.Exit'>, <class 'KeyboardInterrupt'>)

    @classmethod
    def from_call(
        cls,
        func: Callable[[], TResult],
        when: Literal["collect", "setup", "call", "teardown"],
        reraise: type[BaseException] | tuple[type[BaseException], ...] | None = None,
    ) -> CallInfo[TResult]:
        """Call func, wrapping the result in a CallInfo.
    
        :param func:
            The function to call. Called without arguments.
        :type func: Callable[[], _pytest.runner.TResult]
        :param when:
            The phase in which the function is called.
        :param reraise:
            Exception or exceptions that shall propagate if raised by the
            function, instead of being wrapped in the CallInfo.
        """
        excinfo = None
        instant = timing.Instant()
        try:
>           result: TResult | None = func()
                                     ^^^^^^

..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\runner.py:353: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\runner.py:245: in <lambda>
    lambda: runtest_hook(item=item, **kwds),
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_hooks.py:512: in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_manager.py:120: in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\logging.py:843: in pytest_runtest_setup
    yield
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\capture.py:895: in pytest_runtest_setup
    return (yield)
            ^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\runner.py:165: in pytest_runtest_setup
    item.session._setupstate.setup(item)
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\runner.py:523: in setup
    col.setup()
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\python.py:1723: in setup
    self._request._fillfixtures()
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:707: in _fillfixtures
    item.funcargs[argname] = self.getfixturevalue(argname)
                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:539: in getfixturevalue
    fixturedef = self._get_active_fixturedef(argname)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:627: in _get_active_fixturedef
    fixturedef.execute(request=subrequest)
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:1110: in execute
    result: FixtureValue = ihook.pytest_fixture_setup(
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_hooks.py:512: in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_manager.py:120: in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py:53: in run_old_style_hookwrapper
    return result.get_result()
           ^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\pluggy\_callers.py:38: in run_old_style_hookwrapper
    res = yield
          ^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\setuponly.py:36: in pytest_fixture_setup
    return (yield)
            ^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:1202: in pytest_fixture_setup
    result = call_fixture_func(fixturefunc, request, kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\fixtures.py:908: in call_fixture_func
    fixture_result = next(generator)
                     ^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:267: in tmp_path
    path = _mk_tmp(request, tmp_path_factory)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:254: in _mk_tmp
    return factory.mktemp(name, numbered=True)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:130: in mktemp
    basename = self._ensure_relative_to_basetemp(basename)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:111: in _ensure_relative_to_basetemp
    if (self.getbasetemp() / basename).resolve().parent != self.getbasetemp():
        ^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\tmpdir.py:186: in getbasetemp
    basetemp = make_numbered_dir_with_cleanup(
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:407: in make_numbered_dir_with_cleanup
    raise e
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:388: in make_numbered_dir_with_cleanup
    p = make_numbered_dir(root, prefix, mode)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:229: in make_numbered_dir
    max_existing = max(map(parse_num, find_suffixes(root, prefix)), default=-1)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:188: in extract_suffixes
    for entry in iter:
                 ^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

root = WindowsPath('C:/Users/karth/AppData/Local/Temp/pytest-of-karth')
prefix = 'pytest-'

    def find_prefixed(root: Path, prefix: str) -> Iterator[os.DirEntry[str]]:
        """Find all elements in root that begin with the prefix, case-insensitive."""
        l_prefix = prefix.lower()
>       for x in os.scandir(root):
                 ^^^^^^^^^^^^^^^^
E       PermissionError: [WinError 5] Access is denied: 'C:\\Users\\karth\\AppData\\Local\\Temp\\pytest-of-karth'

..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:176: PermissionError
=========================== short test summary info ===========================
ERROR tests/test_core.py::TestMemorySchemaGuard::test_fresh_db_initialises_without_error
ERROR tests/test_core.py::TestMemorySchemaGuard::test_stale_db_is_rebuilt - P...
======================== 16 passed, 2 errors in 8.68s =========================
```

### `pytest_local_temp`

- Command: `C:\Users\karth\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_core.py -v --basetemp .local\pytest_tmp -p no:cacheprovider`
- Return code: `1`

```text
============================= test session starts =============================
platform win32 -- Python 3.12.5, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\karth\AppData\Local\Programs\Python\Python312\python.exe
rootdir: C:\Users\karth\OneDrive\Desktop\novamindzip
plugins: anyio-4.9.0, langsmith-0.4.31
collecting ... collected 18 items

tests/test_core.py::TestSafeFormulaEval::test_arithmetic_allowed PASSED  [  5%]
tests/test_core.py::TestSafeFormulaEval::test_column_reference_allowed PASSED [ 11%]
tests/test_core.py::TestSafeFormulaEval::test_ternary_allowed PASSED     [ 16%]
tests/test_core.py::TestSafeFormulaEval::test_import_blocked PASSED      [ 22%]
tests/test_core.py::TestSafeFormulaEval::test_unknown_variable_blocked PASSED [ 27%]
tests/test_core.py::TestSafeFormulaEval::test_attribute_access_blocked PASSED [ 33%]
tests/test_core.py::TestSafeFormulaEval::test_add_column_uses_safe_eval PASSED [ 38%]
tests/test_core.py::TestSafeFormulaEval::test_add_column_blocks_injection PASSED [ 44%]
tests/test_core.py::TestErrorRecoveryTimeout::test_doubled_timeout_does_not_inject_to_function_args PASSED [ 50%]
tests/test_core.py::TestErrorRecoveryTimeout::test_recover_generic_returns_plan PASSED [ 55%]
tests/test_core.py::TestErrorRecoveryTimeout::test_classify_timeout_error PASSED [ 61%]
tests/test_core.py::TestMemorySchemaGuard::test_fresh_db_initialises_without_error ERROR [ 66%]
tests/test_core.py::TestMemorySchemaGuard::test_stale_db_is_rebuilt ERROR [ 72%]
tests/test_core.py::TestTaskParserRouting::test_draw_plan_uses_execute_paint_task PASSED [ 77%]
tests/test_core.py::TestTaskParserRouting::test_is_drawing_request_detection PASSED [ 83%]
tests/test_core.py::TestTaskParserRouting::test_color_extraction PASSED  [ 88%]
tests/test_core.py::TestTaskParserRouting::test_fallback_parse_does_not_crash PASSED [ 94%]
tests/test_core.py::TestCanvasClamping::test_dpi_scale_1_in_dpi_aware_process PASSED [100%]

=================================== ERRORS ====================================
_ ERROR at setup of TestMemorySchemaGuard.test_fresh_db_initialises_without_error _

path = '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'
onexc = functools.partial(<function on_rm_rf_error at 0x00000236996909A0>, start_path=WindowsPath('//?/C:/Users/karth/OneDrive/Desktop/novamindzip/.local/pytest_tmp'))

    def _rmtree_unsafe(path, onexc):
        def onerror(err):
            onexc(os.scandir, err.filename, err)
        results = os.walk(path, topdown=False, onerror=onerror, followlinks=os._walk_symlinks_as_files)
        for dirpath, dirnames, filenames in results:
            for name in dirnames:
                fullname = os.path.join(dirpath, name)
                try:
                    os.rmdir(fullname)
                except OSError as err:
                    onexc(os.rmdir, fullname, err)
            for name in filenames:
                fullname = os.path.join(dirpath, name)
                try:
                    os.unlink(fullname)
                except OSError as err:
                    onexc(os.unlink, fullname, err)
        try:
>           os.rmdir(path)
E           PermissionError: [WinError 5] Access is denied: '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'

..\..\..\AppData\Local\Programs\Python\Python312\Lib\shutil.py:637: PermissionError

During handling of the above exception, another exception occurred:

path = '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'
ignore_errors = False, onerror = None

    def rmtree(path, ignore_errors=False, onerror=None, *, onexc=None, dir_fd=None):
        """Recursively delete a directory tree.
    
        If dir_fd is not None, it should be a file descriptor open to a directory;
        path will then be relative to that directory.
        dir_fd may not be implemented on your platform.
        If it is unavailable, using it will raise a NotImplementedError.
    
        If ignore_errors is set, errors are ignored; otherwise, if onexc or
        onerror is set, it is called to handle the error with arguments (func,
        path, exc_info) where func is platform and implementation dependent;
        path is the argument to that function that caused it to fail; and
        the value of exc_info describes the exception. For onexc it is the
        exception instance, and for onerror it is a tuple as returned by
        sys.exc_info().  If ignore_errors is false and both onexc and
        onerror are None, the exception is reraised.
    
        onerror is deprecated and only remains for backwards compatibility.
        If both onerror and onexc are set, onerror is ignored and onexc is used.
        """
    
        sys.audit("shutil.rmtree", path, dir_fd)
        if ignore_errors:
            def onexc(*args):
                pass
        elif onerror is None and onexc is None:
            def onexc(*args):
                raise
        elif onexc is None:
            if onerror is None:
                def onexc(*args):
                    raise
            else:
                # delegate to onerror
                def onexc(*args):
                    func, path, exc = args
                    if exc is None:
                        exc_info = None, None, None
                    else:
                        exc_info = type(exc), exc, exc.__traceback__
                    return onerror(func, path, exc_info)
    
        if _use_fd_functions:
            # While the unsafe rmtree works fine on bytes, the fd based does not.
            if isinstance(path, bytes):
                path = os.fsdecode(path)
            stack = [(os.lstat, dir_fd, path, None)]
            try:
                while stack:
                    _rmtree_safe_fd(stack, onexc)
            finally:
                # Close any file descriptors still on the stack.
                while stack:
                    func, fd, path, entry = stack.pop()
                    if func is not os.close:
                        continue
                    try:
                        os.close(fd)
                    except OSError as err:
                        onexc(os.close, path, err)
        else:
            if dir_fd is not None:
                raise NotImplementedError("dir_fd unavailable on this platform")
            try:
                if _rmtree_islink(path):
                    # symlinks to directories are forbidden, see bug #1669
                    raise OSError("Cannot call rmtree on a symbolic link")
            except OSError as err:
                onexc(os.path.islink, path, err)
                # can't continue even if onexc hook returns
                return
>           return _rmtree_unsafe(path, onexc)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^

..\..\..\AppData\Local\Programs\Python\Python312\Lib\shutil.py:781: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

path = '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'
onexc = functools.partial(<function on_rm_rf_error at 0x00000236996909A0>, start_path=WindowsPath('//?/C:/Users/karth/OneDrive/Desktop/novamindzip/.local/pytest_tmp'))

    def _rmtree_unsafe(path, onexc):
        def onerror(err):
            onexc(os.scandir, err.filename, err)
        results = os.walk(path, topdown=False, onerror=onerror, followlinks=os._walk_symlinks_as_files)
        for dirpath, dirnames, filenames in results:
            for name in dirnames:
                fullname = os.path.join(dirpath, name)
                try:
                    os.rmdir(fullname)
                except OSError as err:
                    onexc(os.rmdir, fullname, err)
            for name in filenames:
                fullname = os.path.join(dirpath, name)
                try:
                    os.unlink(fullname)
                except OSError as err:
                    onexc(os.unlink, fullname, err)
        try:
            os.rmdir(path)
        except OSError as err:
>           onexc(os.rmdir, path, err)
E           PermissionError: [WinError 5] Access is denied: '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'

..\..\..\AppData\Local\Programs\Python\Python312\Lib\shutil.py:639: PermissionError
______ ERROR at setup of TestMemorySchemaGuard.test_stale_db_is_rebuilt _______

path = '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'
onexc = functools.partial(<function on_rm_rf_error at 0x00000236996909A0>, start_path=WindowsPath('//?/C:/Users/karth/OneDrive/Desktop/novamindzip/.local/pytest_tmp'))

    def _rmtree_unsafe(path, onexc):
        def onerror(err):
            onexc(os.scandir, err.filename, err)
        results = os.walk(path, topdown=False, onerror=onerror, followlinks=os._walk_symlinks_as_files)
        for dirpath, dirnames, filenames in results:
            for name in dirnames:
                fullname = os.path.join(dirpath, name)
                try:
                    os.rmdir(fullname)
                except OSError as err:
                    onexc(os.rmdir, fullname, err)
            for name in filenames:
                fullname = os.path.join(dirpath, name)
                try:
                    os.unlink(fullname)
                except OSError as err:
                    onexc(os.unlink, fullname, err)
        try:
>           os.rmdir(path)
E           PermissionError: [WinError 5] Access is denied: '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'

..\..\..\AppData\Local\Programs\Python\Python312\Lib\shutil.py:637: PermissionError

During handling of the above exception, another exception occurred:

path = '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'
ignore_errors = False, onerror = None

    def rmtree(path, ignore_errors=False, onerror=None, *, onexc=None, dir_fd=None):
        """Recursively delete a directory tree.
    
        If dir_fd is not None, it should be a file descriptor open to a directory;
        path will then be relative to that directory.
        dir_fd may not be implemented on your platform.
        If it is unavailable, using it will raise a NotImplementedError.
    
        If ignore_errors is set, errors are ignored; otherwise, if onexc or
        onerror is set, it is called to handle the error with arguments (func,
        path, exc_info) where func is platform and implementation dependent;
        path is the argument to that function that caused it to fail; and
        the value of exc_info describes the exception. For onexc it is the
        exception instance, and for onerror it is a tuple as returned by
        sys.exc_info().  If ignore_errors is false and both onexc and
        onerror are None, the exception is reraised.
    
        onerror is deprecated and only remains for backwards compatibility.
        If both onerror and onexc are set, onerror is ignored and onexc is used.
        """
    
        sys.audit("shutil.rmtree", path, dir_fd)
        if ignore_errors:
            def onexc(*args):
                pass
        elif onerror is None and onexc is None:
            def onexc(*args):
                raise
        elif onexc is None:
            if onerror is None:
                def onexc(*args):
                    raise
            else:
                # delegate to onerror
                def onexc(*args):
                    func, path, exc = args
                    if exc is None:
                        exc_info = None, None, None
                    else:
                        exc_info = type(exc), exc, exc.__traceback__
                    return onerror(func, path, exc_info)
    
        if _use_fd_functions:
            # While the unsafe rmtree works fine on bytes, the fd based does not.
            if isinstance(path, bytes):
                path = os.fsdecode(path)
            stack = [(os.lstat, dir_fd, path, None)]
            try:
                while stack:
                    _rmtree_safe_fd(stack, onexc)
            finally:
                # Close any file descriptors still on the stack.
                while stack:
                    func, fd, path, entry = stack.pop()
                    if func is not os.close:
                        continue
                    try:
                        os.close(fd)
                    except OSError as err:
                        onexc(os.close, path, err)
        else:
            if dir_fd is not None:
                raise NotImplementedError("dir_fd unavailable on this platform")
            try:
                if _rmtree_islink(path):
                    # symlinks to directories are forbidden, see bug #1669
                    raise OSError("Cannot call rmtree on a symbolic link")
            except OSError as err:
                onexc(os.path.islink, path, err)
                # can't continue even if onexc hook returns
                return
>           return _rmtree_unsafe(path, onexc)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^

..\..\..\AppData\Local\Programs\Python\Python312\Lib\shutil.py:781: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

path = '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'
onexc = functools.partial(<function on_rm_rf_error at 0x00000236996909A0>, start_path=WindowsPath('//?/C:/Users/karth/OneDrive/Desktop/novamindzip/.local/pytest_tmp'))

    def _rmtree_unsafe(path, onexc):
        def onerror(err):
            onexc(os.scandir, err.filename, err)
        results = os.walk(path, topdown=False, onerror=onerror, followlinks=os._walk_symlinks_as_files)
        for dirpath, dirnames, filenames in results:
            for name in dirnames:
                fullname = os.path.join(dirpath, name)
                try:
                    os.rmdir(fullname)
                except OSError as err:
                    onexc(os.rmdir, fullname, err)
            for name in filenames:
                fullname = os.path.join(dirpath, name)
                try:
                    os.unlink(fullname)
                except OSError as err:
                    onexc(os.unlink, fullname, err)
        try:
            os.rmdir(path)
        except OSError as err:
>           onexc(os.rmdir, path, err)
E           PermissionError: [WinError 5] Access is denied: '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'

..\..\..\AppData\Local\Programs\Python\Python312\Lib\shutil.py:639: PermissionError
============================== warnings summary ===============================
tests/test_core.py::TestMemorySchemaGuard::test_fresh_db_initialises_without_error
tests/test_core.py::TestMemorySchemaGuard::test_stale_db_is_rebuilt
  C:\Users\karth\AppData\Local\Programs\Python\Python312\Lib\site-packages\_pytest\pathlib.py:103: PytestWarning: (rm_rf) unknown function <built-in function scandir> when removing \\?\C:\Users\karth\OneDrive\Desktop\novamindzip\.local\pytest_tmp:
  <class 'PermissionError'>: [WinError 5] Access is denied: '\\\\?\\C:\\Users\\karth\\OneDrive\\Desktop\\novamindzip\\.local\\pytest_tmp'
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
ERROR tests/test_core.py::TestMemorySchemaGuard::test_fresh_db_initialises_without_error
ERROR tests/test_core.py::TestMemorySchemaGuard::test_stale_db_is_rebuilt - P...
================== 16 passed, 2 warnings, 2 errors in 6.30s ===================
```

### `import_checker`

- Command: `C:\Users\karth\AppData\Local\Programs\Python\Python312\python.exe tools/import_checker.py`
- Return code: `2`

```text
Checking agents\__init__.py...
{"path": "agents\\__init__.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\application_agent.py...
{"path": "agents\\application_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": "UIAExecutor: comtypes/UIA not available (module 'comtypes.gen' has no attribute 'UIAutomationClient') \u2014 UIA strategy disabled; OCR/coordinate fallbacks will be used\n"}
Checking agents\apps\__init__.py...
{"path": "agents\\apps\\__init__.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\apps\paint_agent.py...
{"path": "agents\\apps\\paint_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": "UIAExecutor: comtypes/UIA not available (module 'comtypes.gen' has no attribute 'UIAutomationClient') \u2014 UIA strategy disabled; OCR/coordinate fallbacks will be used\n"}
Checking agents\browser_agent.py...
{"path": "agents\\browser_agent.py", "status": "ERROR", "returncode": 2, "stdout": "", "stderr": "Traceback (most recent call last):\n  File \"<string>\", line 3, in <module>\n  File \"<frozen runpy>\", line 285, in run_path\n  File \"<frozen runpy>\", line 259, in _get_code_from_file\n  File \"agents\\browser_agent.py\", line 80\n    def open_url(self, url: str, wait_time: float = 3.0,\n    ^^^\nIndentationError: expected an indented block after function definition on line 78\n"}
Checking agents\code_agent.py...
{"path": "agents\\code_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\data_agent.py...
{"path": "agents\\data_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\email_agent.py...
{"path": "agents\\email_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\error_handler.py...
{"path": "agents\\error_handler.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\error_recovery_agent.py...
{"path": "agents\\error_recovery_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\file_agent.py...
{"path": "agents\\file_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\memory_agent.py...
{"path": "agents\\memory_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\network_agent.py...
{"path": "agents\\network_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking agents\system_agent.py...
{"path": "agents\\system_agent.py", "status": "ERROR", "returncode": 2, "stdout": "", "stderr": "Traceback (most recent call last):\n  File \"<string>\", line 3, in <module>\n  File \"<frozen runpy>\", line 285, in run_path\n  File \"<frozen runpy>\", line 259, in _get_code_from_file\n  File \"agents\\system_agent.py\", line 220\n    def execute_command(self, command: str, shell: bool = True,\n    ^^^\nIndentationError: expected an indented block after function definition on line 214\n"}
Checking agents\verifier_agent.py...
{"path": "agents\\verifier_agent.py", "status": "ERROR", "returncode": 2, "stdout": "", "stderr": "Traceback (most recent call last):\n  File \"<string>\", line 3, in <module>\n  File \"<frozen runpy>\", line 286, in run_path\n  File \"<frozen runpy>\", line 98, in _run_module_code\n  File \"<frozen runpy>\", line 88, in _run_code\n  File \"agents\\verifier_agent.py\", line 36, in <module>\n    class VerificationResult:\n  File \"agents\\verifier_agent.py\", line 39, in VerificationResult\n    issues: List[str]\n            ^^^^\nNameError: name 'List' is not defined. Did you mean: 'list'?\n"}
Checking config.py...
{"path": "config.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\__init__.py...
{"path": "core\\__init__.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\base_agent.py...
{"path": "core\\base_agent.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\brain.py...
{"path": "core\\brain.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\element_finder.py...
{"path": "core\\element_finder.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": "UIAExecutor: comtypes/UIA not available (module 'comtypes.gen' has no attribute 'UIAutomationClient') \u2014 UIA strategy disabled; OCR/coordinate fallbacks will be used\n"}
Checking core\event_bus.py...
{"path": "core\\event_bus.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\llm_router.py...
{"path": "core\\llm_router.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\os_executor.py...
{"path": "core\\os_executor.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\parallel_engine.py...
{"path": "core\\parallel_engine.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\runtime_paths.py...
{"path": "core\\runtime_paths.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\scheduler.py...
{"path": "core\\scheduler.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\state_manager.py...
{"path": "core\\state_manager.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\step_executor.py...
{"path": "core\\step_executor.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\task_parser.py...
{"path": "core\\task_parser.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\tool_result.py...
{"path": "core\\tool_result.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking core\uia_executor.py...
{"path": "core\\uia_executor.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": "UIAExecutor: comtypes/UIA not available (module 'comtypes.gen' has no attribute 'UIAutomationClient') \u2014 UIA strategy disabled; OCR/coordinate fallbacks will be used\n"}
Checking game\__init__.py...
{"path": "game\\__init__.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking game\nova_mindscape.py...
{"path": "game\\nova_mindscape.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking game\nova_mindscape_launcher.py...
{"path": "game\\nova_mindscape_launcher.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking main.py...
{"path": "main.py", "status": "OK", "returncode": 0, "stdout": "SYS_EXIT 2\n", "stderr": "usage: main.py [-h] [--task TASK] [--headless] [--no-game] [--status]\n               [--health] [--setup] [--version]\nmain.py: error: unrecognized arguments: main.py\n"}
Checking memory\__init__.py...
{"path": "memory\\__init__.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking memory\memory_system.py...
{"path": "memory\\memory_system.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking proactive_scan.py...
{"path": "proactive_scan.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking security\__init__.py...
{"path": "security\\__init__.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking security\command_guard.py...
{"path": "security\\command_guard.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking ui\__init__.py...
{"path": "ui\\__init__.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking ui\task_window.py...
{"path": "ui\\task_window.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking vision\__init__.py...
{"path": "vision\\__init__.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking vision\screen_analyzer.py...
{"path": "vision\\screen_analyzer.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
Checking vision\vision_system.py...
{"path": "vision\\vision_system.py", "status": "OK", "returncode": 0, "stdout": "OK\n", "stderr": ""}
```

### `data_agent_probe`

```text
Probe failed: No module named 'agents'
```

### `memory_system_probe`

```text
Probe failed: No module named 'memory'
```

## Key Snippets

### `game/nova_mindscape.py:1569`

- Note: This module is syntax-broken at the shown `except` block.

```python
1569:             self._update_sky(t)
1570:             self._update_rain(dt)
1571:             self._update_lightning(dt, t)
1572:             self._update_neon(t)
1573:             self._update_traffic(dt)
1574:             self._update_pedestrians(dt, t)
1575:             self._update_shards(dt, t)
1576:             self._update_monorail(dt, t)
1577:             self._sync_mission_beacons(tasks, t)
1578:             self._check_interactions()
1579:             self._update_hud(tasks, t, dt)
1580:             self._update_minimap(tasks)
1581:         except Exception as e:
1582:             logger.error(f"_game_update error (frame skipped): {e}", exc_info=True)
1583: 
1584:     # ── Player update ─────────────────────────────────────────────────────────
1585: 
1586:     def _update_player(self, dt: float):
```

### `main.py:44`

- Note: Early logging setup causes `PermissionError` before CLI handling.

```python
  44: 
  45: 
  46: def _build_log_handlers() -> List[logging.Handler]:
  47:     handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
  48:     try:
  49:         handlers.insert(
  50:             0,
  51:             logging.handlers.RotatingFileHandler(
  52:                 log_file,
  53:                 maxBytes=10 * 1024 * 1024,
  54:                 backupCount=5,
  55:                 encoding="utf-8",
  56:             ),
  57:         )
  58:     except OSError as exc:
```

### `agents/data_agent.py:28`

- Note: Formula whitelist is missing `ast.Load`, causing valid formulas to fail.

```python
  28: 
  29: # ── Safe formula evaluator (replaces raw eval) ─────────────────────────────────────
  30: 
  31: _SAFE_AST_NODES = frozenset({
  32:     _ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Compare,
  33:     _ast.BoolOp, _ast.Constant, _ast.Name, _ast.Load,
  34:     _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.Mod, _ast.Pow,
  35:     _ast.FloorDiv, _ast.USub, _ast.UAdd,
  36:     _ast.Eq, _ast.NotEq, _ast.Lt, _ast.LtE, _ast.Gt, _ast.GtE,
  37:     _ast.And, _ast.Or, _ast.Not,
  38:     _ast.IfExp,   # ternary: x if cond else y
  39: })
  40: 
  41: 
  42: def _safe_eval_formula(formula: str, row: dict) -> Any:
  43:     """
  44:     Evaluate a simple row-level formula safely.
  45:     Only permits arithmetic, comparisons, and row field references.
  46:     Rejects: imports, function calls, attribute access, arbitrary builtins.
  47:     Returns None on any error.
  48:     """
  49:     try:
  50:         tree = _ast.parse(formula, mode='eval')
  51:         for node in _ast.walk(tree):
  52:             if type(node) not in _SAFE_AST_NODES:
  53:                 raise ValueError(f"Unsafe expression node: {type(node).__name__}")
  54:         # Only allow names that match actual row column names
  55:         allowed_names = set(row.keys())
  56:         for node in _ast.walk(tree):
  57:             if isinstance(node, _ast.Name) and node.id not in allowed_names:
  58:                 raise ValueError(f"Unknown variable in formula: {node.id!r}")
  59:         return eval(  # noqa: S307  — input already AST-validated above
  60:             compile(tree, '<formula>', 'eval'),
  61:             {"__builtins__": {}},
  62:             row,
```

### `agents/data_agent.py:1577`

- Note: Internal filter path calls a nonexistent `self._safe_eval_formula(...)`.

```python
1577:             elif isinstance(v, list):
1578:                 for i, item in enumerate(v):
1579:                     if isinstance(item, dict):
1580:                         items.update(DataAgent._flatten_dict(item, f"{new_key}[{i}]", sep))
1581:                     else:
1582:                         items[f"{new_key}[{i}]"] = item
1583:             else:
1584:                 items[new_key] = v
1585:         return items
```

### `core/task_parser.py:518`

- Note: LLM JSON `depends_on` is not copied into `TaskStep`.

```python
 518:     @staticmethod
 519:     def _extract_json(content: str) -> Dict:
 520:         json_match = re.search(r"\{.*\}", content, re.DOTALL)
 521:         if json_match:
 522:             return json.loads(json_match.group())
 523:         return json.loads(content)
 524: 
 525:     @staticmethod
 526:     def _create_task_plan(original: str, parsed: Dict) -> TaskPlan:
 527:         steps = []
 528:         for s in parsed.get("steps", []):
 529:             try:
 530:                 risk = RiskLevel(s.get("risk_level", "safe").lower())
 531:             except ValueError:
 532:                 risk = RiskLevel.SAFE
 533:             steps.append(TaskStep(
 534:                 step_number=s.get("step_number", len(steps) + 1),
 535:                 description=s.get("description", ""),
```

### `core/element_finder.py:357`

- Note: Missing `Any` import makes the module unloadable.

```python
 357: # ── Module-level singleton ────────────────────────────────────────────────────
 358: 
 359: _finder: Optional[ElementFinder] = None
 360: _EASYOCR_READER: Any = None
 361: _FINDER_LOCK = threading.Lock()
 362: 
 363: 
 364: def get_finder() -> ElementFinder:
 365:     global _finder
```

### `agents/verifier_agent.py:97`

- Note: Verification persistence uses a wrong method signature.

```python
  97:         )
  98: 
  99:         response = self.router.quick_request(prompt, task_type="quick")
 100:         result = self._parse_verification(response)
 101: 
 102:         if self.memory and task_id:
 103:             try:
 104:                 self.memory.log_error(
 105:                     error_msg=f"Verification: satisfied={result.satisfied} "
 106:                               f"confidence={result.confidence:.2f} "
 107:                               f"issues={result.issues}",
 108:                     task_id=task_id,
```

### `memory/memory_system.py:320`

- Note: Actual `log_error()` signature has no `severity` parameter.

```python
 320:                 )
 321: 
 322:     def log_error(self, error_msg: str, task_id: str = "",
 323:                   agent: str = "", action: str = "",
 324:                   severity: str = "") -> None:
 325:         with self._lock:
 326:             with self._conn() as conn:
 327:                 conn.execute(
 328:                     """INSERT INTO errors
```

### `agents/system_agent.py:268`

- Note: Command execution uses `subprocess.Popen(..., shell=shell, ...)`.

```python
 268: 
 269:         except Exception as e:
 270:             return {"success": False, "error": str(e)}
 271: 
 272:     def execute_script(self, code: str, language: str = "python",
 273:                        timeout: int = 60) -> Dict:
 274:         """Execute a code snippet in the appropriate interpreter."""
 275:         # O(1) dict dispatch — zero elif routing
 276:         _EXEC_DISPATCH = {
 277:             "python":     self._exec_python,
 278:             "bash":       self._exec_shell,
 279:             "sh":         self._exec_shell,
 280:             "cmd":        self.execute_batch,
 281:             "batch":      self.execute_batch,
 282:             "powershell": self.execute_powershell,
 283:             "ps1":        self.execute_powershell,
 284:             "javascript": self._exec_js,
 285:         }
```

### `agents/browser_agent.py:144`

- Note: Browser fallback interpolates URLs into `os.system(...)`.

```python
 144:         Args:
 145:             query: Search query
 146:             engine: Search engine (google, duckduckgo, bing)
 147:             open_result: Whether to open first result
 148:         """
 149:         try:
 150:             # Build search URL
 151:             encoded_query = urllib.parse.quote(query)
 152: 
```

## File-by-File Catalog

### `.local/skills/canvas/__init__.py`

- Lines: `1`
- Code lines (rough): `0`
- Comment lines (rough): `1`
- SHA256: `c58161acb0dbb5807aa6821fc8c7bb78fb0f411d5e05462bea18a317d8ed5a4b`
- Depth assessment: `package-marker`
- Import check status: `not-run`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python
   1: # Canvas skill for workspace canvas shape manipulation
```

### `agents/__init__.py`

- Lines: `0`
- Code lines (rough): `0`
- Comment lines (rough): `0`
- SHA256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Depth assessment: `package-marker`
- Import check status: `OK`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python

```

### `agents/application_agent.py`

- Lines: `983`
- Code lines (rough): `833`
- Comment lines (rough): `28`
- SHA256: `bdb44e1876a8301c010082f4c408c2df3f2c49477e33bb3005047f28b25bcde0`
- Depth assessment: `wrapper-heavy`
- Import check status: `OK`
- Module docstring: Application Agent — Universal Windows Desktop Automation
- Imports: `__future__, agents.apps.paint_agent, core.base_agent, datetime, io, json, logging, math, os, platform, re, subprocess`
- Classes: `ApplicationAgent`
- Top-level functions: `<none>`
- Note: This is one of the largest files in the repo and mixes real GUI automation with broad wrapper/dispatch behavior.
- Note: It is not OS-native programming; it mainly coordinates `pyautogui`, `pygetwindow`, OCR, and subprocess strategies.
- Import stderr excerpt:
```text
UIAExecutor: comtypes/UIA not available (module 'comtypes.gen' has no attribute 'UIAutomationClient') — UIA strategy disabled; OCR/coordinate fallbacks will be used
```
- Snippet:
```python
 162: class ApplicationAgent(BaseAgent):
 163:     """
 164:     Universal Windows desktop automation agent.
 165:     Every action is real: pyautogui mouse + keyboard, screen capture, OCR.
 166:     No simulations. Decisions adapt to what is actually on screen.
 167:     """
 168: 
 169:     # How many consecutive step failures before replanning
 170:     REPLAN_THRESHOLD = 2
 171: 
 172:     def __init__(self):
```

### `agents/apps/__init__.py`

- Lines: `3`
- Code lines (rough): `0`
- Comment lines (rough): `3`
- SHA256: `e5d68b50c312472ff86f7b77fd8a827b51426aa36e3624b6f811254162543e9a`
- Depth assessment: `package-marker`
- Import check status: `OK`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python
   1: # agents/apps — per-application action modules
   2: # Each module uses ElementFinder + OSExecutor with app-specific knowledge.
   3: # Zero if-elif routing — all dispatch via O(1) dict lookup.
```

### `agents/apps/paint_agent.py`

- Lines: `304`
- Code lines (rough): `249`
- Comment lines (rough): `11`
- SHA256: `1a9ceecb98868c8b9bdc7e246d6dca454b7cad5d20c3cced0dd0c3e1eee9ce5f`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: agents/apps/paint_agent.py
- Imports: `core.base_agent, logging, math, os, random, re, subprocess, time, typing`
- Classes: `DrawingPlan, PaintAgent`
- Top-level functions: `<none>`
- Import stderr excerpt:
```text
UIAExecutor: comtypes/UIA not available (module 'comtypes.gen' has no attribute 'UIAutomationClient') — UIA strategy disabled; OCR/coordinate fallbacks will be used
```
- Snippet:
```python
  34: class DrawingPlan:
  35:     def __init__(self, subject: str, cw: int = 600, ch: int = 400):
  36:         self.subject       = subject
  37:         self.canvas_width  = cw
  38:         self.canvas_height = ch
  39:         self.strokes: List[Dict] = []
  40:         self.color_rgb: Tuple[int, int, int] = (0, 0, 255)
  41: 
  42:     def add_stroke(self, points: List[Tuple[int, int]], color: Tuple[int, int, int] = None):
  43:         self.strokes.append({
  44:             "color":  color or self.color_rgb,
```

### `agents/browser_agent.py`

- Lines: `587`
- Code lines (rough): `461`
- Comment lines (rough): `17`
- SHA256: `1462ceec8477feb5741fcf8fb89a2471eaa32f2e2cf58428724e292c791e498f`
- Depth assessment: `syntax-error`
- Import check status: `ERROR`
- Parse error: `SyntaxError line 80 col 5: expected an indented block after function definition on line 78`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Note: Primary implementation is wrapper-level browser/web orchestration.
- Note: Fallback `os.system(...)` launch path interpolates the URL string directly.
- Import stderr excerpt:
```text
Traceback (most recent call last):
  File "<string>", line 3, in <module>
  File "<frozen runpy>", line 285, in run_path
  File "<frozen runpy>", line 259, in _get_code_from_file
  File "agents\browser_agent.py", line 80
    def open_url(self, url: str, wait_time: float = 3.0,
    ^^^
IndentationError: expected an indented block after function definition on line 78
```
- Snippet:
```python
 144:         Args:
 145:             query: Search query
 146:             engine: Search engine (google, duckduckgo, bing)
 147:             open_result: Whether to open first result
 148:         """
 149:         try:
 150:             # Build search URL
 151:             encoded_query = urllib.parse.quote(query)
 152: 
```

### `agents/code_agent.py`

- Lines: `1848`
- Code lines (rough): `1577`
- Comment lines (rough): `67`
- SHA256: `33c5f2e8140af7d9d4a55e4aad895d9d8f345ed4b6a16c30dbedd9722550c23b`
- Depth assessment: `wrapper-heavy`
- Import check status: `OK`
- Module docstring: Code Agent — Write, analyse, refactor, profile, test, and execute code.
- Imports: `__future__, ast, collections, core.base_agent, core.llm_router, dataclasses, datetime, difflib, hashlib, importlib, inspect, io`
- Classes: `CodeIssue, RefactorSuggestion, ExecutionResult, CodeMetrics, ComplexityVisitor, MaxDepthVisitor, DuplicateBlockDetector, CodeAgent`
- Top-level functions: `<none>`
- Snippet:
```python
  43: class CodeIssue:
  44:     severity: str          # "error" | "warning" | "info"
  45:     line: int
  46:     column: int
  47:     code: str              # rule id, e.g. "E501"
  48:     message: str
  49:     source: str            # "ast" | "pylint" | "flake8" | "mypy" | "bandit" | "llm"
  50: 
  51: 
  52: @dataclass
  53: class RefactorSuggestion:
```

### `agents/data_agent.py`

- Lines: `1626`
- Code lines (rough): `1391`
- Comment lines (rough): `55`
- SHA256: `5d569b62491d18e168f86364eea0e002897b68f5328890387797d656e2bc468f`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: Data Agent — Full data manipulation, analysis, and transformation engine.
- Imports: `__future__, ast, collections, core.base_agent, csv, dataclasses, datetime, io, json, logging, os, pathlib`
- Classes: `DataProfile, DataAgent`
- Top-level functions: `_safe_eval_formula`
- Note: Safe formula evaluation now accepts normal row expressions such as `price * qty` and ternaries, and the targeted regression tests pass.
- Note: `_apply_where_filter` now uses the same module-level safe evaluator as `add_column()` and `apply_formula()`.
- Snippet:
```python
  28: 
  29: # ── Safe formula evaluator (replaces raw eval) ─────────────────────────────────────
  30: 
  31: _SAFE_AST_NODES = frozenset({
  32:     _ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Compare,
  33:     _ast.BoolOp, _ast.Constant, _ast.Name, _ast.Load,
  34:     _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.Mod, _ast.Pow,
  35:     _ast.FloorDiv, _ast.USub, _ast.UAdd,
  36:     _ast.Eq, _ast.NotEq, _ast.Lt, _ast.LtE, _ast.Gt, _ast.GtE,
  37:     _ast.And, _ast.Or, _ast.Not,
  38:     _ast.IfExp,   # ternary: x if cond else y
  39: })
  40: 
  41: 
  42: def _safe_eval_formula(formula: str, row: dict) -> Any:
  43:     """
  44:     Evaluate a simple row-level formula safely.
  45:     Only permits arithmetic, comparisons, and row field references.
  46:     Rejects: imports, function calls, attribute access, arbitrary builtins.
  47:     Returns None on any error.
  48:     """
  49:     try:
  50:         tree = _ast.parse(formula, mode='eval')
  51:         for node in _ast.walk(tree):
  52:             if type(node) not in _SAFE_AST_NODES:
  53:                 raise ValueError(f"Unsafe expression node: {type(node).__name__}")
  54:         # Only allow names that match actual row column names
  55:         allowed_names = set(row.keys())
  56:         for node in _ast.walk(tree):
  57:             if isinstance(node, _ast.Name) and node.id not in allowed_names:
  58:                 raise ValueError(f"Unknown variable in formula: {node.id!r}")
  59:         return eval(  # noqa: S307  — input already AST-validated above
  60:             compile(tree, '<formula>', 'eval'),
  61:             {"__builtins__": {}},
  62:             row,
```

### `agents/email_agent.py`

- Lines: `1168`
- Code lines (rough): `985`
- Comment lines (rough): `55`
- SHA256: `c2d5e05e5f942d1c5a0336fb2f21cce6fab624bad32d524b7f7de76898fcca69`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: Email Agent — Full SMTP/IMAP email automation.
- Imports: `__future__, base64, core.base_agent, dataclasses, datetime, email, email.header, email.mime.application, email.mime.base, email.mime.multipart, email.mime.text, email.utils`
- Classes: `EmailMessage, EmailAccount, ImapSession, EmailAgent`
- Top-level functions: `<none>`
- Snippet:
```python
  41: class EmailMessage:
  42:     uid:         str
  43:     subject:     str
  44:     sender:      str
  45:     recipients:  List[str]
  46:     cc:          List[str]
  47:     bcc:         List[str]
  48:     date:        str
  49:     body_text:   str
  50:     body_html:   str
  51:     attachments: List[Dict]
```

### `agents/error_handler.py`

- Lines: `380`
- Code lines (rough): `322`
- Comment lines (rough): `6`
- SHA256: `7a53074b0494927897bf581c9e87a7e3b1ee410957ad4ce1fe11e9f14a220eb4`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: Error Handler — LLM-assisted error analysis and fix suggestion.
- Imports: `core.llm_router, datetime, json, logging, re, typing`
- Classes: `ErrorHandler`
- Top-level functions: `_match_error_patterns, _get_pattern_solutions, _normalize_error, _extract_json_safe, _extract_code_safe`
- Snippet:
```python
  93: class ErrorHandler:
  94:     """
  95:     LLM-assisted error analyst and fix suggester.
  96:     Supports other agents recovering from failures.
  97:     All classification uses O(1) frozenset lookup — no if-elif chains.
  98:     """
  99: 
 100:     def __init__(self):
 101:         self.router = get_router()
 102:         self.error_history: List[Dict] = []
 103:         self.solution_cache: Dict[str, Dict] = {}
```

### `agents/error_recovery_agent.py`

- Lines: `394`
- Code lines (rough): `329`
- Comment lines (rough): `3`
- SHA256: `7909c927babfc678ee085c63f8b2808d8461cf0d2b513633884ffb60a688c466`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: ErrorRecoveryAgent — Strategy-pattern error recovery.
- Imports: `asyncio, core.base_agent, dataclasses, logging, typing`
- Classes: `RecoveryContext, RecoveryPlan, ErrorRecoveryAgent`
- Top-level functions: `_try_alternative_selector, _try_visual_location, _try_pyautogui_fallback, _retry_doubled_timeout, _break_into_smaller_steps, _try_alternative_tool, _fix_command_syntax, _try_equivalent_command, _use_python_subprocess, _reinject_schema_and_retry, _add_output_examples, _use_lower_temperature, _reset_paint_and_retry, _geometric_drawing_fallback, _use_simpler_shape, _generic_fallback, _escalate`
- Snippet:
```python
  19: class RecoveryContext:
  20:     original_task: Dict
  21:     error_type: str
  22:     tool_output: Any
  23:     retry_strategy: str
  24:     attempt_number: int
  25:     task_id: str = ""
  26: 
  27: 
  28: @dataclass
  29: class RecoveryPlan:
```

### `agents/file_agent.py`

- Lines: `1444`
- Code lines (rough): `1235`
- Comment lines (rough): `59`
- SHA256: `1cc66706817dcbce93600cc886de98e82a3c408d25f7c099af380eafd3b8ae92`
- Depth assessment: `wrapper-heavy`
- Import check status: `OK`
- Module docstring: File Agent — Complete file and folder management.
- Imports: `__future__, base64, binascii, bz2, collections, core.base_agent, core.runtime_paths, dataclasses, datetime, difflib, fnmatch, glob`
- Classes: `FileAgent`
- Top-level functions: `<none>`
- Snippet:
```python
  94: class FileAgent(BaseAgent):
  95:     """
  96:     Complete OS file system agent.
  97:     Includes search, diffs, permissions, archiving, and watchers.
  98:     """
  99: 
 100:     PROTECTED_PATHS = {
 101:         "C:\\Windows", "C:\\Program Files", "C:\\ProgramData",
 102:         "/usr/bin", "/usr/sbin", "/bin", "/sbin", "/etc",
 103:         "/sys", "/dev", "/proc", "/boot",
 104:     }
```

### `agents/memory_agent.py`

- Lines: `210`
- Code lines (rough): `166`
- Comment lines (rough): `9`
- SHA256: `74f5d806b80324250d4a7dcfeb12d18efa05b85ba5392d73d1cebb70ed90a00e`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: MemoryAgent — Standalone agent wrapping MemorySystem.
- Imports: `core.base_agent, datetime, json, logging, typing`
- Classes: `MemoryAgent`
- Top-level functions: `<none>`
- Snippet:
```python
  22: class MemoryAgent(BaseAgent):
  23:     """
  24:     Thin orchestration layer over MemorySystem.
  25: 
  26:     Usage
  27:     -----
  28:     agent = MemoryAgent(memory_system)
  29:     ctx   = agent.assemble_context("open Chrome and search GitHub")
  30:     agent.store_experience({"task": "...", "success": True, ...})
  31:     agent.consolidate()
  32:     """
```

### `agents/network_agent.py`

- Lines: `1334`
- Code lines (rough): `1128`
- Comment lines (rough): `63`
- SHA256: `bbd69dba670ad62d34a5527402f70c30a90e0bac1673948472537f77e6bda1fd`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: Network Agent — Full network scanning, monitoring, WiFi, VPN, proxy, and HTTP tooling.
- Imports: `__future__, concurrent.futures, core.base_agent, dataclasses, datetime, json, logging, os, pathlib, platform, re, shutil`
- Classes: `PortScanResult, NetworkHost, HTTPResponse, NetworkAgent`
- Top-level functions: `<none>`
- Snippet:
```python
  45: class PortScanResult:
  46:     host:   str
  47:     port:   int
  48:     open:   bool
  49:     banner: str = ""
  50:     service: str = ""
  51: 
  52: 
  53: @dataclass
  54: class NetworkHost:
  55:     ip:       str
```

### `agents/system_agent.py`

- Lines: `2155`
- Code lines (rough): `1840`
- Comment lines (rough): `87`
- SHA256: `199b36f4f287202bd720e145f1f231d4edef640f365875426fe951ccf31b9945`
- Depth assessment: `syntax-error`
- Import check status: `ERROR`
- Parse error: `SyntaxError line 220 col 5: expected an indented block after function definition on line 214`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Note: Command execution is real and powerful, but it defaults to `shell=True` and relies on a small regex blocklist.
- Note: `ALLOWED_PREFIXES` exists but is not enforced in `_security_check()`.
- Import stderr excerpt:
```text
Traceback (most recent call last):
  File "<string>", line 3, in <module>
  File "<frozen runpy>", line 285, in run_path
  File "<frozen runpy>", line 259, in _get_code_from_file
  File "agents\system_agent.py", line 220
    def execute_command(self, command: str, shell: bool = True,
    ^^^
IndentationError: expected an indented block after function definition on line 214
```
- Snippet:
```python
 268: 
 269:         except Exception as e:
 270:             return {"success": False, "error": str(e)}
 271: 
 272:     def execute_script(self, code: str, language: str = "python",
 273:                        timeout: int = 60) -> Dict:
 274:         """Execute a code snippet in the appropriate interpreter."""
 275:         # O(1) dict dispatch — zero elif routing
 276:         _EXEC_DISPATCH = {
 277:             "python":     self._exec_python,
 278:             "bash":       self._exec_shell,
 279:             "sh":         self._exec_shell,
 280:             "cmd":        self.execute_batch,
 281:             "batch":      self.execute_batch,
 282:             "powershell": self.execute_powershell,
 283:             "ps1":        self.execute_powershell,
 284:             "javascript": self._exec_js,
 285:         }
 286:         handler = _EXEC_DISPATCH.get(language)
 287:         return (handler(code, timeout) if handler
 288:                 else {"success": False, "error": f"Unsupported language: {language}"})
```

### `agents/verifier_agent.py`

- Lines: `215`
- Code lines (rough): `187`
- Comment lines (rough): `0`
- SHA256: `2250a117e3b643ff10f9e082fd3d79384c531768d27dd286b12624bcd48e9d12`
- Depth assessment: `wrapper-heavy`
- Import check status: `ERROR`
- Module docstring: VerifierAgent — THE most critical agent.
- Imports: `core.base_agent, core.llm_router, dataclasses, json, logging`
- Classes: `VerificationResult, VerifierAgent`
- Top-level functions: `<none>`
- Note: Verification logging now persists cleanly because `MemorySystem.log_error()` accepts the `severity` argument used by the verifier path.
- Import stderr excerpt:
```text
Traceback (most recent call last):
  File "<string>", line 3, in <module>
  File "<frozen runpy>", line 286, in run_path
  File "<frozen runpy>", line 98, in _run_module_code
  File "<frozen runpy>", line 88, in _run_code
  File "agents\verifier_agent.py", line 36, in <module>
    class VerificationResult:
  File "agents\verifier_agent.py", line 39, in VerificationResult
    issues: List[str]
            ^^^^
NameError: name 'List' is not defined. Did you mean: 'list'?
```
- Snippet:
```python
  97:         )
  98: 
  99:         response = self.router.quick_request(prompt, task_type="quick")
 100:         result = self._parse_verification(response)
 101: 
 102:         if self.memory and task_id:
 103:             try:
 104:                 self.memory.log_error(
 105:                     error_msg=f"Verification: satisfied={result.satisfied} "
 106:                               f"confidence={result.confidence:.2f} "
 107:                               f"issues={result.issues}",
 108:                     task_id=task_id,
```

### `config.py`

- Lines: `165`
- Code lines (rough): `115`
- Comment lines (rough): `16`
- SHA256: `182129a70aa8d07a41ea1e626d9ec66dd64560ec5ae1babefc6c3d0124923fd1`
- Depth assessment: `configuration`
- Import check status: `OK`
- Module docstring: config.py
- Imports: `typing`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python
   1: """
   2: config.py
   3: 
   4: Single source of truth for every magic number in NovaMind.
   5: Import from here — never hardcode values in agents or core modules.
   6: 
   7: Zero if-elif — all values are constants or O(1) dict lookups.
   8: """
   9: 
  10: from typing import Dict, Tuple, FrozenSet
  11: 
  12: # ── Timing (seconds) ──────────────────────────────────────────────────────────
```

### `core/__init__.py`

- Lines: `0`
- Code lines (rough): `0`
- Comment lines (rough): `0`
- SHA256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Depth assessment: `package-marker`
- Import check status: `OK`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python

```

### `core/base_agent.py`

- Lines: `69`
- Code lines (rough): `58`
- Comment lines (rough): `1`
- SHA256: `9817e03cda436c930afcd97bf206a2684d536660b70b5fbfe24e32b0f6f5d00b`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: core/base_agent.py
- Imports: `logging, typing`
- Classes: `BaseAgent`
- Top-level functions: `<none>`
- Snippet:
```python
  14: class BaseAgent:
  15:     """
  16:     All agents inherit from BaseAgent.
  17:     Subclasses define their actions in `self.handlers` (a dictionary).
  18:     If an action is missing locally, it falls back to `_GLOBAL_REGISTRY`.
  19:     Zero if/elif/else statements in execution logic.
  20:     """
  21:     
  22:     # Plugin registry — agents can register capabilities at runtime
  23:     _GLOBAL_REGISTRY: Dict[str, Callable] = {}
  24: 
```

### `core/brain.py`

- Lines: `924`
- Code lines (rough): `755`
- Comment lines (rough): `51`
- SHA256: `3c9c5608baaf62c4b8388863fd42092d7626c4ab06598e24644841f71c271d4b`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: Brain — Task orchestration and execution engine.
- Imports: `asyncio, concurrent.futures, core.llm_router, core.parallel_engine, core.task_parser, dataclasses, datetime, enum, json, logging, os, threading`
- Classes: `ExecutionStatus, StepResult, TaskExecution, Brain`
- Top-level functions: `_run_coroutine_safe, _safe_mouseup, _format_output`
- Snippet:
```python
 339:             has_deps = any(step.depends_on for step in exec_.plan.steps)
 340:             
 341:             if has_deps:
 342:                 logger.info(f"DAG detected for task {exec_.task_id[:8]} — using ParallelEngine")
 343:                 self._run_parallel_execution(exec_)
 344:                 return
 345: 
 346:             for step in exec_.plan.steps:
 347:                 if exec_.status == ExecutionStatus.CANCELLED:
 348:                     break
 349: 
 350:                 result = self._execute_step_with_verify(exec_, step)
 351:                 exec_.results.append(result)
 352: 
 353:                 if result.status == ExecutionStatus.SUCCESS:
 354:                     steps_ok += 1
 355:                     exec_.completed_steps += 1
 356:                 else:
 357:                     steps_fail += 1
 358:                     exec_.failed_steps += 1
 359:                     exec_.error_log.append(
 360:                         f"Step {step.step_number}: {result.error}"
 361:                     )
 362:                     if step.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
 363:                         break
 364: 
 365:                 self._notify(exec_)
 366: 
 367:             # O(1) dict dispatch — replaces elif chain for final status
 368:             # bool(steps_ok > 0) → SUCCESS/FAILED; no transition when cancelled
 369:             not_cancelled = exec_.status != ExecutionStatus.CANCELLED
 370:             target = _FINAL_STATUS.get(steps_ok > 0, ExecutionStatus.FAILED)
 371:             not_cancelled and self._transition(
 372:                 exec_, target,
 373:                 {"steps_ok": steps_ok, "steps_fail": steps_fail})
 374:             # Annotate partial failures (any ok AND any fail)
 375:             partial = not_cancelled and steps_ok > 0 and steps_fail > 0
 376:             partial and setattr(
 377:                 exec_, "summary",
 378:                 (exec_.summary or "") + f" ({steps_fail} step(s) failed)")
 379: 
 380:             exec_.end_time = datetime.now().isoformat()
 381:             self._finalize(exec_, steps_ok, steps_fail)
 382:             self._notify(exec_)
 383: 
 384:     def _run_parallel_execution(self, exec_: TaskExecution) -> None:
 385:         """Convert TaskPlan to DAG and run via ParallelExecutionEngine."""
 386:         nodes = []
 387:         for s in exec_.plan.steps:
 388:             node = TaskNode(
 389:                 id=str(s.step_number),
 390:                 description=s.description,
 391:                 agent_type=s.agent,
 392:                 tool=s.action,
 393:                 args=s.parameters,
 394:                 depends_on=[str(d) for d in s.depends_on],
 395:                 expected_output={"success": True},
 396:                 timeout=self.STEP_TIMEOUT
 397:             )
 398:             nodes.append(node)
 399:         
 400:         try:
 401:             results = self._run_coro(self.parallel_engine.execute_dag(nodes))
```

### `core/element_finder.py`

- Lines: `367`
- Code lines (rough): `302`
- Comment lines (rough): `10`
- SHA256: `6334988046d4b72f8ae3d241a96c592886d9abbae9c42cf5766f3b3cf8912600`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: core/element_finder.py
- Imports: `dataclasses, logging, threading, time, typing`
- Classes: `FoundElement, _UIAStrategy, _OCRStrategy, _TemplateStrategy, ElementFinder`
- Top-level functions: `_uia_to_found, _make_tesseract_found, _make_easyocr_found, get_finder`
- Note: The current file imports cleanly in the latest import sweep.
- Import stderr excerpt:
```text
UIAExecutor: comtypes/UIA not available (module 'comtypes.gen' has no attribute 'UIAutomationClient') — UIA strategy disabled; OCR/coordinate fallbacks will be used
```
- Snippet:
```python
 357: # ── Module-level singleton ────────────────────────────────────────────────────
 358: 
 359: _finder: Optional[ElementFinder] = None
 360: _EASYOCR_READER: Any = None
 361: _FINDER_LOCK = threading.Lock()
 362: 
 363: 
 364: def get_finder() -> ElementFinder:
 365:     global _finder
```

### `core/event_bus.py`

- Lines: `152`
- Code lines (rough): `129`
- Comment lines (rough): `0`
- SHA256: `47b4a8f01a09b8a180f2064f393a8c48df0129189563fb95c5730733926e7d5e`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: EventBus — Async publish/subscribe for agent decoupling.
- Imports: `asyncio, datetime, json, logging, threading, typing`
- Classes: `EventBus`
- Top-level functions: `_safe_call, get_event_bus`
- Snippet:
```python
  27: class EventBus:
  28:     """
  29:     Thread-safe async publish/subscribe event bus.
  30:     Stores complete event log for session replay (replay_session feature).
  31:     """
  32: 
  33:     def __init__(self, memory_system=None):
  34:         self._subscribers: Dict[str, List[Callable]] = {}
  35:         self._event_log: List[Dict] = []
  36:         self._memory = memory_system
  37:         self._lock = threading.Lock()
```

### `core/llm_router.py`

- Lines: `751`
- Code lines (rough): `642`
- Comment lines (rough): `21`
- SHA256: `aec3513dab3b544b0fa80618e39863fe930cf42736c0e03df7b31b8f604c42f4`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: LLM Router - Multi-Provider Round-Robin with Automatic Failover
- Imports: `core.runtime_paths, dataclasses, datetime, enum, json, logging, os, random, requests, threading, time, typing`
- Classes: `ProviderStatus, Provider, LLMRouter`
- Top-level functions: `get_router`
- Snippet:
```python
  22: class ProviderStatus(Enum):
  23:     ACTIVE = "active"
  24:     RATE_LIMITED = "rate_limited"
  25:     DOWN = "down"
  26:     NO_KEY = "no_key"
  27: 
  28: 
  29: @dataclass
  30: class Provider:
  31:     name: str
  32:     base_url: str
```

### `core/os_executor.py`

- Lines: `537`
- Code lines (rough): `422`
- Comment lines (rough): `18`
- SHA256: `94b9f18d7d5737a4890f04740cc90e7d5ee325b8c3e0cf6048d83b7ce003bee7`
- Depth assessment: `real-local-logic`
- Import check status: `OK`
- Module docstring: core/os_executor.py
- Imports: `ctypes, logging, platform, time, typing`
- Classes: `FocusLostError, ActionVerifier, OSExecutor`
- Top-level functions: `_audit, get_audit_log, _run_chaos_hook, _detect_dpi, logical_to_physical, physical_to_logical, _try_activate_window, assert_window_focused, release_all_modifiers, detect_paint_canvas, point_inside_region, safe_click, safe_drag, _execute_drag, safe_scroll, safe_move, safe_type, safe_type_clipboard, safe_hotkey, safe_press, safe_hold, safe_mouseup, capture_region, images_differ`
- Note: This file contains genuine local automation/safety logic: DPI handling, focus assertion, canvas detection, and screenshot diffing.
- Snippet:
```python
  41:         "error":   error,
  42:     }
  43:     _ACTION_AUDIT.append(entry)
  44:     _ACTION_AUDIT[:] = _ACTION_AUDIT[-_AUDIT_MAX:]
  45:     _log = {
  46:         True:  lambda: logger.debug(f"[AUDIT] {action} on '{window}' ✓ {params}"),
  47:         False: lambda: logger.warning(f"[AUDIT] {action} on '{window}' ✗ error={error}"),
  48:     }
  49:     _log[success]()
  50: 
  51: 
  52: def get_audit_log() -> list:
  53:     """Return a copy of the recent audit log (last 500 actions)."""
  54:     return list(_ACTION_AUDIT)
  55: 
  56: 
  57: # ── Chaos testing hook — inject focus-loss during test runs ───────────────────────
  58: _CHAOS_HOOKS: dict = {
  59:     # Map action name to a callable that will be invoked BEFORE the action executes.
  60:     # In tests: _CHAOS_HOOKS["safe_click"] = lambda: trigger_focus_loss()
  61:     # Leave empty for production runs.
  62: }
  63: 
  64: 
  65: def _run_chaos_hook(action_name: str) -> None:
  66:     """Fire any registered chaos hook for the given action."""
  67:     hook = _CHAOS_HOOKS.get(action_name)
  68:     _do = {True: lambda: hook()}
  69:     _do.get(hook is not None, lambda: None)()
  70: 
  71: 
  72: try:
  73:     import pyautogui
  74:     pyautogui.FAILSAFE = True
  75:     pyautogui.PAUSE = 0.05
```

### `core/parallel_engine.py`

- Lines: `259`
- Code lines (rough): `230`
- Comment lines (rough): `0`
- SHA256: `858906c643b74cf7f307a5e9cf5978fecce8aceb5e292c752fc07df33ed52cef`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: ParallelExecutionEngine — asyncio DAG runner.
- Imports: `asyncio, dataclasses, datetime, enum, logging, threading, typing, uuid`
- Classes: `TaskStatus, TaskNode, ParallelExecutionEngine`
- Top-level functions: `<none>`
- Snippet:
```python
  19: class TaskStatus(Enum):
  20:     PENDING   = "pending"
  21:     RUNNING   = "running"
  22:     COMPLETED = "completed"
  23:     FAILED    = "failed"
  24:     RETRYING  = "retrying"
  25: 
  26: 
  27: @dataclass
  28: class TaskNode:
  29:     id: str
```

### `core/runtime_paths.py`

- Lines: `46`
- Code lines (rough): `36`
- Comment lines (rough): `0`
- SHA256: `54dcc5d35dbc16a8842738489361accd0625c9f523746d62a11643b53f76460f`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: Runtime path helpers for NovaMind.
- Imports: `__future__, functools, os, pathlib`
- Classes: `<none>`
- Top-level functions: `_probe_dir, get_runtime_root, ensure_runtime_dir, runtime_path`
- Snippet:
```python
  14: def _probe_dir(path: Path) -> Path:
  15:     path.mkdir(parents=True, exist_ok=True)
  16:     probe = path / ".write_probe"
  17:     probe.write_text("ok", encoding="utf-8")
  18:     probe.unlink(missing_ok=True)
  19:     return path
  20: 
  21: 
  22: @lru_cache(maxsize=1)
  23: def get_runtime_root() -> Path:
  24:     env_roots = [
```

### `core/scheduler.py`

- Lines: `376`
- Code lines (rough): `298`
- Comment lines (rough): `19`
- SHA256: `669fa79a63da5a79e2c3290947f566e430ae79ef3dc8ddb232b2fe1501f71f34`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: Task Scheduler — Priority queue + time-based scheduling for NovaMind.
- Imports: `dataclasses, datetime, enum, heapq, json, logging, threading, time, typing, uuid`
- Classes: `Priority, ScheduledTaskStatus, ScheduledTask, TaskScheduler`
- Top-level functions: `<none>`
- Snippet:
```python
  20: class Priority(Enum):
  21:     CRITICAL = 0   # Runs immediately, skips queue
  22:     HIGH     = 1
  23:     NORMAL   = 2
  24:     LOW      = 3
  25:     IDLE     = 4   # Only when nothing else is queued
  26: 
  27: 
  28: class ScheduledTaskStatus(Enum):
  29:     QUEUED    = "queued"
  30:     WAITING   = "waiting"       # Scheduled for future time
```

### `core/state_manager.py`

- Lines: `156`
- Code lines (rough): `141`
- Comment lines (rough): `0`
- SHA256: `b4c5a25c9d1d08d2d1ca211d209935c8fcb75ef69810b49facc90e32b90cb4f9`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: StateManager — Writes workflow state to SQLite on every transition.
- Imports: `dataclasses, datetime, enum, json, logging, sqlite3, threading, typing`
- Classes: `TaskStatus, TaskNode, StateManager`
- Top-level functions: `<none>`
- Snippet:
```python
  18: class TaskStatus(Enum):
  19:     PENDING   = "pending"
  20:     RUNNING   = "running"
  21:     COMPLETED = "completed"
  22:     FAILED    = "failed"
  23:     RETRYING  = "retrying"
  24: 
  25: 
  26: @dataclass
  27: class TaskNode:
  28:     id: str
```

### `core/step_executor.py`

- Lines: `212`
- Code lines (rough): `178`
- Comment lines (rough): `1`
- SHA256: `effc228bfe3af2090324a09598b1ef522dda2089da6ced6f6f9550f7563cbce8`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: core/step_executor.py
- Imports: `dataclasses, logging, time, typing`
- Classes: `StepResult, StepExecutor`
- Top-level functions: `_safe_mouseup, get_step_executor`
- Snippet:
```python
  45: class StepResult:
  46:     success: bool
  47:     attempts: int = 0
  48:     error: str = ""
  49:     verified: bool = False
  50:     recovery_strategies_used: List[str] = field(default_factory=list)
  51:     elapsed: float = 0.0
  52: 
  53: 
  54: class StepExecutor:
  55:     """
```

### `core/task_parser.py`

- Lines: `588`
- Code lines (rough): `500`
- Comment lines (rough): `19`
- SHA256: `48066dfd234ec6bc2b27976867df0d3ae7d4143d1513696182c8a8539198199c`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: Task Parser - Natural Language Understanding
- Imports: `core.llm_router, dataclasses, enum, json, logging, re, typing`
- Classes: `TaskType, RiskLevel, TaskStep, TaskPlan, TaskParser`
- Top-level functions: `_assess_risk_fast`
- Note: The parser now preserves `depends_on` from LLM JSON, so the DAG/parallel execution path is reachable again.
- Note: Dependency values are normalized to integer step numbers and invalid entries are ignored instead of crashing plan construction.
- Snippet:
```python
 518:     @staticmethod
 519:     def _extract_json(content: str) -> Dict:
 520:         json_match = re.search(r"\{.*\}", content, re.DOTALL)
 521:         if json_match:
 522:             return json.loads(json_match.group())
 523:         return json.loads(content)
 524: 
 525:     @staticmethod
 526:     def _create_task_plan(original: str, parsed: Dict) -> TaskPlan:
 527:         steps = []
 528:         for s in parsed.get("steps", []):
 529:             try:
 530:                 risk = RiskLevel(s.get("risk_level", "safe").lower())
 531:             except ValueError:
 532:                 risk = RiskLevel.SAFE
 533:             steps.append(TaskStep(
 534:                 step_number=s.get("step_number", len(steps) + 1),
 535:                 description=s.get("description", ""),
 536:                 agent=s.get("agent", "system_agent"),
 537:                 action=s.get("action", "execute"),
 538:                 parameters=s.get("parameters", {}),
 539:                 verification_method=s.get("verification_method", ""),
 540:                 rollback_action=s.get("rollback_action", ""),
 541:                 requires_confirmation=s.get("requires_confirmation", False),
 542:                 risk_level=risk,
 543:                 depends_on=TaskParser._coerce_depends_on(s.get("depends_on", [])),
 544:             ))
 545: 
```

### `core/tool_result.py`

- Lines: `97`
- Code lines (rough): `79`
- Comment lines (rough): `0`
- SHA256: `7ceead5c173b09ef7a52c9198c252475b03d1199acf1cfc76e7ca654f8b41e2c`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: Tool Result Contract + Tool Registry.
- Imports: `abc, asyncio, dataclasses, logging, time, typing`
- Classes: `ToolResult, Tool, ToolNotFoundError`
- Top-level functions: `register_tool, get_tool`
- Snippet:
```python
  17: class ToolResult:
  18:     success: bool
  19:     output: Any
  20:     error: Optional[str]
  21:     execution_time_ms: int
  22:     tool_name: str
  23:     metadata: Dict = field(default_factory=dict)
  24: 
  25:     def __bool__(self) -> bool:
  26:         return self.success
  27: 
```

### `core/uia_executor.py`

- Lines: `425`
- Code lines (rough): `362`
- Comment lines (rough): `6`
- SHA256: `5986c2fc60e587d95041d7d4603b8e9ab4ea3aeeacf48ad4152734a5656b5cc8`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: core/uia_executor.py
- Imports: `logging, time, typing`
- Classes: `UIElement, UIWindow, UIAExecutor`
- Top-level functions: `_build_condition, _find_in_element, _find_all_in_element, _centre_click`
- Import stderr excerpt:
```text
UIAExecutor: comtypes/UIA not available (module 'comtypes.gen' has no attribute 'UIAutomationClient') — UIA strategy disabled; OCR/coordinate fallbacks will be used
```
- Snippet:
```python
  50: def _build_condition(name=None, automation_id=None, control_type=None):
  51:     """Build a combined UIA condition from provided filters. Returns None on error."""
  52:     _unavail = {True: lambda: None}
  53:     unavail = _unavail.get(not _UIA_OK)
  54:     if unavail:
  55:         return unavail()
  56:     try:
  57:         parts = {
  58:             "name":          name,
  59:             "automation_id": automation_id,
  60:             "control_type":  control_type,
```

### `game/__init__.py`

- Lines: `0`
- Code lines (rough): `0`
- Comment lines (rough): `0`
- SHA256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Depth assessment: `package-marker`
- Import check status: `OK`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python

```

### `game/nova_mindscape.py`

- Lines: `2162`
- Code lines (rough): `1738`
- Comment lines (rough): `197`
- SHA256: `4b63f2dea7635f52fcd818127c1a8222284fbc4ec7e1632b55f3ebf709ede69c`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: ╔══════════════════════════════════════════════════════════════════╗
- Imports: `__future__, dataclasses, logging, math, random, threading, typing`
- Classes: `GameConfig, NovaMindscape`
- Top-level functions: `_ucol, _rgb`
- Note: The current file compiles in the latest verification run.
- Snippet:
```python
1569:             self._update_sky(t)
1570:             self._update_rain(dt)
1571:             self._update_lightning(dt, t)
1572:             self._update_neon(t)
1573:             self._update_traffic(dt)
1574:             self._update_pedestrians(dt, t)
1575:             self._update_shards(dt, t)
1576:             self._update_monorail(dt, t)
1577:             self._sync_mission_beacons(tasks, t)
1578:             self._check_interactions()
1579:             self._update_hud(tasks, t, dt)
1580:             self._update_minimap(tasks)
1581:         except Exception as e:
1582:             logger.error(f"_game_update error (frame skipped): {e}", exc_info=True)
1583: 
1584:     # ── Player update ─────────────────────────────────────────────────────────
1585: 
1586:     def _update_player(self, dt: float):
```

### `game/nova_mindscape_launcher.py`

- Lines: `160`
- Code lines (rough): `129`
- Comment lines (rough): `5`
- SHA256: `0e8c73643ed6ba55790a82cadd9d90cb5b5b3ea50ab6e77d5b7e6e97c3824252`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: game/nova_mindscape_launcher.py
- Imports: `logging, multiprocessing, time, typing`
- Classes: `GameProcessManager`
- Top-level functions: `_game_worker`
- Snippet:
```python
  26: def _game_worker(cmd_q: multiprocessing.Queue,
  27:                  evt_q: multiprocessing.Queue,
  28:                  config_dict: dict) -> None:
  29:     """
  30:     Runs inside the child process. Imports Ursina here so the parent
  31:     process is never polluted by an OpenGL context.
  32:     """
  33:     try:
  34:         from game.nova_mindscape import NovaMindscape, GameConfig
  35:         cfg = GameConfig(**{
  36:             k: v for k, v in config_dict.items()
```

### `main.py`

- Lines: `722`
- Code lines (rough): `569`
- Comment lines (rough): `58`
- SHA256: `763e0ceb8c4613c1b5005f5966a543d35d4023688e1b259aa115135ee8310480`
- Depth assessment: `orchestrator`
- Import check status: `OK`
- Module docstring: NovaMind - Autonomous Desktop AI Agent
- Imports: `argparse, core.runtime_paths, datetime, io, json, logging, logging.handlers, os, pathlib, sys, threading, time`
- Classes: `NovaMindApp`
- Top-level functions: `_build_log_handlers, check_dependencies, print_banner, load_env_keys, create_env_template, main`
- Note: Runtime files now fall back to a writable repo-local `.novamind/` directory, so health/status/startup checks no longer depend on a writable home directory.
- Note: `--health`, `--status`, and `tools/run_dep_check.py` all succeed in the latest verification run.
- Import stderr excerpt:
```text
usage: main.py [-h] [--task TASK] [--headless] [--no-game] [--status]
               [--health] [--setup] [--version]
main.py: error: unrecognized arguments: main.py
```
- Snippet:
```python
  44: 
  45: 
  46: def _build_log_handlers() -> List[logging.Handler]:
  47:     handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
  48:     try:
  49:         handlers.insert(
  50:             0,
  51:             logging.handlers.RotatingFileHandler(
  52:                 log_file,
  53:                 maxBytes=10 * 1024 * 1024,
  54:                 backupCount=5,
  55:                 encoding="utf-8",
  56:             ),
  57:         )
  58:     except OSError as exc:
```

### `memory/__init__.py`

- Lines: `0`
- Code lines (rough): `0`
- Comment lines (rough): `0`
- SHA256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Depth assessment: `package-marker`
- Import check status: `OK`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python

```

### `memory/memory_system.py`

- Lines: `531`
- Code lines (rough): `464`
- Comment lines (rough): `11`
- SHA256: `1115aa15cebcb12329ef809b317fbeb29ccd303d1be90f5656246b66a33e97ff`
- Depth assessment: `real-local-logic`
- Import check status: `OK`
- Module docstring: memory/memory_system.py
- Imports: `core.runtime_paths, datetime, json, logging, os, sqlite3, threading, time, typing`
- Classes: `MemorySystem`
- Top-level functions: `<none>`
- Note: This file contains real local implementation: SQLite schema management, persistence, and stale-schema rebuild logic.
- Snippet:
```python
   1: """
   2: memory/memory_system.py
   3: 
   4: 14-table SQLite episodic + semantic memory system.
   5: WAL journal mode — crash-safe writes, no full fsync overhead.
   6: Thread-safe via a per-connection threading.Lock.
   7: All branching uses dict dispatch — zero if/elif chains.
   8: """
   9: import json
  10: import logging
  11: import os
  12: import sqlite3
  13: import threading
  14: import time
  15: from datetime import datetime
  16: from typing import Any, Dict, List, Optional
  17: 
  18: from core.runtime_paths import runtime_path
  19: 
  20: logger = logging.getLogger("MemorySystem")
  21: 
  22: DB_PATH = str(runtime_path("memory.db"))
  23: 
  24: SCHEMA_SQL = """
  25: PRAGMA journal_mode=WAL;
  26: PRAGMA synchronous=NORMAL;
  27: 
  28: CREATE TABLE IF NOT EXISTS sessions (
  29:     id          INTEGER PRIMARY KEY AUTOINCREMENT,
  30:     session_id  TEXT UNIQUE NOT NULL,
  31:     started_at  TEXT NOT NULL,
  32:     ended_at    TEXT,
  33:     task_count  INTEGER DEFAULT 0
  34: );
  35: 
  36: CREATE TABLE IF NOT EXISTS tasks (
  37:     id            INTEGER PRIMARY KEY AUTOINCREMENT,
  38:     task_id       TEXT UNIQUE NOT NULL,
  39:     session_id    TEXT,
  40:     request       TEXT,
```

### `proactive_scan.py`

- Lines: `65`
- Code lines (rough): `45`
- Comment lines (rough): `10`
- SHA256: `7f385214229626387513f9a8c8d09b603fb6355652c91459ee3441a76e6c8a47`
- Depth assessment: `supporting-tool`
- Import check status: `OK`
- Imports: `io, os, re`
- Classes: `<none>`
- Top-level functions: `scan_files`
- Snippet:
```python
   5: def scan_files():
   6:     findings = []
   7:     root_dir = r"c:\Users\karth\OneDrive\Desktop\novamind"
   8:     
   9:     for root, dirs, files in os.walk(root_dir):
  10:         for file in files:
  11:             if not file.endswith(".py"):
  12:                 continue
  13:             path = os.path.join(root, file)
  14:             rel_path = os.path.relpath(path, root_dir)
  15:             
```

### `security/__init__.py`

- Lines: `0`
- Code lines (rough): `0`
- Comment lines (rough): `0`
- SHA256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Depth assessment: `package-marker`
- Import check status: `OK`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python

```

### `security/command_guard.py`

- Lines: `365`
- Code lines (rough): `291`
- Comment lines (rough): `23`
- SHA256: `780523bce1f8203bcc27edced8d99eab2e8435b29f19ebfc1aa855b32f5c0280`
- Depth assessment: `mixed-local-logic`
- Import check status: `OK`
- Module docstring: Security Layer — Command sandboxing and permission control.
- Imports: `ast, datetime, logging, re, typing`
- Classes: `CommandGuard`
- Top-level functions: `is_blacklisted, _accesses_protected_path_with_modification, assess_risk`
- Snippet:
```python
 131:     r"\bchoco\s+install\b",
 132:     r"\bwinget\s+install\b",
 133:     r"\bpip\s+install\b",
 134:     r"\bnpm\s+install\s+-g\b",
 135:     r"\bchmod\b",
 136:     r"\bicacls\b",
 137:     r"\btakeown\b",
 138:     r"\bsc\s+(start|stop|pause)\b",
 139:     r"\bnet\s+(start|stop)\b",
 140:     r"\bcurl\s+.*-o\b",
 141:     r"\bwget\b",
 142:     r"\bInvoke-WebRequest\b",
 143: ]
 144: 
 145: 
 146: class CommandGuard:
 147:     """
 148:     Security guard for all agent operations.
 149:     O(1) blacklist — frozenset substring check.
 150:     O(1) risk assessment — dict lookup.
 151:     dict dispatch for all action handlers.
 152:     """
 153: 
 154:     def __init__(self, strict_mode: bool = False):
 155:         self.strict_mode = strict_mode
 156:         self.confirmation_history: List[Dict] = []
 157:         self.pending_confirmations: Dict[str, Dict] = {}
 158:         self.session_allowlist: List[str] = []
 159:         self.session_blocklist: List[str] = []
 160: 
 161:     # ──────────────────────────────────────────────────────────────────────────
 162:     #  Public API
 163:     # ──────────────────────────────────────────────────────────────────────────
 164: 
 165:     def check_action(self, agent: str, action: str,
 166:                      parameters: Dict) -> Tuple[bool, str]:
 167:         """Check if an agent action is allowed. Returns (allowed, reason)."""
 168:         command_str = self._build_command_string(agent, action, parameters)
 169:         return self._check_string(command_str, self.strict_mode)
 170: 
```

### `tests/test_core.py`

- Lines: `236`
- Code lines (rough): `166`
- Comment lines (rough): `28`
- SHA256: `c77b8b83daa7886354458a849f106baa94953800f44ff090b0ac1aeace974afc`
- Depth assessment: `tests`
- Import check status: `not-run`
- Module docstring: tests/test_core.py
- Imports: `asyncio, os, pytest, sys, tempfile`
- Classes: `TestSafeFormulaEval, TestErrorRecoveryTimeout, TestMemorySchemaGuard, TestTaskParserRouting, TestCanvasClamping`
- Top-level functions: `<none>`
- Snippet:
```python
  29: class TestSafeFormulaEval:
  30:     """Verify that the safe AST evaluator blocks injections and passes arithmetic."""
  31: 
  32:     def _import_safe_eval(self):
  33:         """Import the module-level helper (not a class method)."""
  34:         from agents.data_agent import _safe_eval_formula
  35:         return _safe_eval_formula
  36: 
  37:     def test_arithmetic_allowed(self):
  38:         _f = self._import_safe_eval()
  39:         row = {"price": 10, "qty": 3}
```

### `tests/test_focus_chaos.py`

- Lines: `178`
- Code lines (rough): `130`
- Comment lines (rough): `5`
- SHA256: `98a36448370449a44a20825d69e902813844fe07b41489d433c3f367ac64a5be`
- Depth assessment: `tests`
- Import check status: `not-run`
- Module docstring: tests/test_focus_chaos.py
- Imports: `core.os_executor, sys, unittest, unittest.mock`
- Classes: `TestFocusGuardBaseline, TestChaosHookFocusLoss, TestAuditLogCapture, TestPluginRegistry`
- Top-level functions: `<none>`
- Snippet:
```python
  36: class TestFocusGuardBaseline(unittest.TestCase):
  37:     """Verify assert_window_focused raises FocusLostError when focus cannot be established."""
  38: 
  39:     def setUp(self):
  40:         _CHAOS_HOOKS.clear()
  41: 
  42:     def test_focus_lost_raises_on_timeout(self):
  43:         """If getActiveWindow always returns wrong title, FocusLostError must be raised."""
  44:         mock_win = MagicMock()
  45:         mock_win.title = "Some Other App"
  46: 
```

### `tools/create_full_audit.py`

- Lines: `320`
- Code lines (rough): `296`
- Comment lines (rough): `0`
- SHA256: `16d016a6c2e1ef749caae7b015c723bb6aa7f48855ca4c2b55cf6b205146607c`
- Depth assessment: `supporting-tool`
- Import check status: `not-run`
- Imports: `ast, collections, datetime, json, os, pathlib, re`
- Classes: `<none>`
- Top-level functions: `get_all_py_files, write_part1, get_calls, write_part2, write_part3, write_part4, write_part5, write_part6, write_part7, write_part8, write_part9, write_part10, write_part11`
- Snippet:
```python
  12: def get_all_py_files():
  13:     files = []
  14:     for root, dirs, fnames in os.walk(REPO_ROOT):
  15:         if '.local' in root or '.git' in root or '__pycache__' in root:
  16:             continue
  17:         for f in fnames:
  18:             if f.endswith('.py'):
  19:                 path = os.path.join(root, f)
  20:                 rel = os.path.relpath(path, REPO_ROOT).replace('\\', '/')
  21:                 files.append((path, rel))
  22:     return files
```

### `tools/generate_audit.py`

- Lines: `409`
- Code lines (rough): `353`
- Comment lines (rough): `24`
- SHA256: `53287f7d21c982ed0e9ea8969dbbc72f4bfb6f9f5ce690ef29fb5617f059b912`
- Depth assessment: `supporting-tool`
- Import check status: `not-run`
- Imports: `collections, datetime, importlib.util, json, os, pathlib`
- Classes: `<none>`
- Top-level functions: `load_json, write_part1, classify_call, write_part2, write_part3, load_check_deps, write_part4_to_11, write_part12`
- Snippet:
```python
  20: def load_json(p: Path):
  21:     with open(p, 'r', encoding='utf-8') as fh:
  22:         return json.load(fh)
  23: 
  24: manifest = load_json(MANIFEST)['files'] if MANIFEST.exists() else []
  25: inventory = load_json(INVENTORY) if INVENTORY.exists() else {'files': [], 'definitions': []}
  26: imports = load_json(IMPORTS) if IMPORTS.exists() else []
  27: 
  28: # helper: group manifest by directory
  29: from collections import defaultdict
  30: by_dir = defaultdict(list)
```

### `tools/generate_live_audit.py`

- Lines: `555`
- Code lines (rough): `483`
- Comment lines (rough): `1`
- SHA256: `f99b0073e0f75c1df2f00f1048f95f5a2b2adde26ee27fe54f9afd42c8d11ea3`
- Depth assessment: `supporting-tool`
- Import check status: `not-run`
- Module docstring: Generate a concrete, evidence-backed codebase audit for NovaMind.
- Imports: `__future__, ast, dataclasses, datetime, hashlib, json, os, pathlib, subprocess, sys, typing`
- Classes: `CommandResult`
- Top-level functions: `rel, sha256_text, run_command, run_audit_commands, run_direct_probes, load_import_check_json, iter_imports, select_snippet, format_snippet, classify_depth, summarize_file, repository_overview, write_header, write_command_section, write_findings_with_snippets, write_file_catalog, main`
- Snippet:
```python
 177: class CommandResult:
 178:     command: str
 179:     returncode: int
 180:     stdout: str
 181:     stderr: str
 182: 
 183:     @property
 184:     def combined(self) -> str:
 185:         out = self.stdout.rstrip()
 186:         err = self.stderr.rstrip()
 187:         if out and err:
```

### `tools/generate_manifest.py`

- Lines: `162`
- Code lines (rough): `139`
- Comment lines (rough): `9`
- SHA256: `586af72f78c9788f84e74d25d2e3ec4689785f0ebab140c682c573cd88287841`
- Depth assessment: `supporting-tool`
- Import check status: `not-run`
- Imports: `ast, datetime, json, os, sys`
- Classes: `<none>`
- Top-level functions: `is_binary_string, first_sentence, python_purpose, file_purpose, process_file, main`
- Snippet:
```python
  16: def is_binary_string(bytes_data):
  17:     if b'\x00' in bytes_data:
  18:         return True
  19:     # Heuristic: if many non-text characters
  20:     textchars = bytearray({7,8,9,10,12,13,27} | set(range(0x20,0x100)))
  21:     return bool(bytes_data.translate(None, textchars))
  22: 
  23: 
  24: def first_sentence(text):
  25:     if not text:
  26:         return None
```

### `tools/import_checker.py`

- Lines: `49`
- Code lines (rough): `43`
- Comment lines (rough): `2`
- SHA256: `44d6d78aab942069e003940055db29c517f806561f00312aacdc5a7990ee146c`
- Depth assessment: `supporting-tool`
- Import check status: `not-run`
- Imports: `glob, json, os, subprocess, sys`
- Classes: `<none>`
- Top-level functions: `check_file, main`
- Snippet:
```python
   8: def check_file(path, timeout=30):
   9:     cmd = [sys.executable, "-c", "import runpy,sys,traceback; p=sys.argv[1];\ntry:\n    runpy.run_path(p, run_name='__main__')\n    print('OK')\nexcept SystemExit as e:\n    print('SYS_EXIT', e.code)\n    sys.exit(0)\nexcept Exception:\n    traceback.print_exc(); sys.exit(2)", path]
  10:     try:
  11:         res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
  12:         out = res.stdout
  13:         err = res.stderr
  14:         code = res.returncode
  15:     except subprocess.TimeoutExpired as e:
  16:         return {"path": path, "status": "TIMEOUT", "error": f"timeout after {timeout}s"}
  17:     except Exception as e:
  18:         return {"path": path, "status": "ERROR", "error": str(e)}
```

### `tools/inventory.py`

- Lines: `153`
- Code lines (rough): `126`
- Comment lines (rough): `11`
- SHA256: `b5524104c39f1cb2b022f07efc997f9e3381be5ba6dfab3b1b8bca0724ecd314`
- Depth assessment: `supporting-tool`
- Import check status: `not-run`
- Imports: `ast, json, os, pathlib`
- Classes: `<none>`
- Top-level functions: `get_call_name, root_name_of_call, analyze_method, analyze_file, collect_all_files, main`
- Snippet:
```python
  15: def get_call_name(node):
  16:     # node is ast.Call
  17:     func = node.func
  18:     if isinstance(func, ast.Name):
  19:         return func.id
  20:     if isinstance(func, ast.Attribute):
  21:         parts = []
  22:         cur = func
  23:         while isinstance(cur, ast.Attribute):
  24:             parts.append(cur.attr)
  25:             cur = cur.value
```

### `tools/run_dep_check.py`

- Lines: `12`
- Code lines (rough): `9`
- Comment lines (rough): `1`
- SHA256: `735d08926be68f9132eb5b5ad2a7d716e2851e592128118ea2d94b9d570515e0`
- Depth assessment: `supporting-tool`
- Import check status: `not-run`
- Imports: `importlib.util, json, os, sys`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python
   1: #!/usr/bin/env python3
   2: import json
   3: import importlib.util
   4: import os
   5: import sys
   6: 
   7: sys.path.insert(0, os.getcwd())
   8: spec = importlib.util.spec_from_file_location("main", os.path.join(os.getcwd(), "main.py"))
   9: main = importlib.util.module_from_spec(spec)
  10: spec.loader.exec_module(main)
  11: 
  12: print(json.dumps(main.check_dependencies(), indent=2))
```

### `ui/__init__.py`

- Lines: `0`
- Code lines (rough): `0`
- Comment lines (rough): `0`
- SHA256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Depth assessment: `package-marker`
- Import check status: `OK`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python

```

### `ui/task_window.py`

- Lines: `1590`
- Code lines (rough): `1279`
- Comment lines (rough): `79`
- SHA256: `3f9f156a8f4ddc1260cfa461fb1b0f71e5fce0dfaff7326ab8a86586eab8c05c`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: NovaMind Task UI — Animated dark cyberpunk theme.
- Imports: `PyQt6.QtCore, PyQt6.QtGui, PyQt6.QtWidgets, datetime, logging, math, random, sys, typing`
- Classes: `_Particle, AnimatedBackground, TaskVisualizer, PulsingDot, FloatingOrb, GlowProgressBar, TaskCard, ConsoleWidget, TypingIndicator, TaskWindow`
- Top-level functions: `<none>`
- Snippet:
```python
 176: class _Particle:
 177:     __slots__ = ("x", "y", "vx", "vy", "alpha", "size", "color_idx")
 178: 
 179:     def __init__(self, w: int, h: int):
 180:         self.x = random.uniform(0, w)
 181:         self.y = random.uniform(0, h)
 182:         self.vx = random.uniform(-0.3, 0.3)
 183:         self.vy = random.uniform(-0.5, -0.1)
 184:         self.alpha = random.uniform(30, 120)
 185:         self.size = random.uniform(1.0, 2.5)
 186:         self.color_idx = random.randint(0, 3)
```

### `vision/__init__.py`

- Lines: `0`
- Code lines (rough): `0`
- Comment lines (rough): `0`
- SHA256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Depth assessment: `package-marker`
- Import check status: `OK`
- Imports: `<none>`
- Classes: `<none>`
- Top-level functions: `<none>`
- Snippet:
```python

```

### `vision/screen_analyzer.py`

- Lines: `287`
- Code lines (rough): `234`
- Comment lines (rough): `6`
- SHA256: `49116c27633ae817b27abab7450531afbf2b32920e4971553cb0110945807579`
- Depth assessment: `mixed`
- Import check status: `OK`
- Module docstring: vision/screen_analyzer.py
- Imports: `dataclasses, logging, typing`
- Classes: `DetectedWindow, TextRegion, UIElementRegion, ScreenState, ScreenAnalyzer`
- Top-level functions: `_ocr_tesseract, _ocr_easyocr, _run_ocr, _detect_windows_cv2, _classify_element, _detect_ui_elements_cv2`
- Snippet:
```python
  44: class DetectedWindow:
  45:     title: str
  46:     bounds: Tuple[int, int, int, int]   # (left, top, right, bottom)
  47:     confidence: float = 1.0
  48: 
  49: 
  50: @dataclass
  51: class TextRegion:
  52:     text: str
  53:     bounds: Tuple[int, int, int, int]
  54:     confidence: float = 1.0
```

### `vision/vision_system.py`

- Lines: `555`
- Code lines (rough): `459`
- Comment lines (rough): `26`
- SHA256: `2bd15087898e539fba23a3b9e0a0133a9156c117574a5e670441af6678bdf622`
- Depth assessment: `wrapper-heavy`
- Import check status: `OK`
- Module docstring: Vision System — Real screen capture, OCR, element detection, image comparison.
- Imports: `base64, core.runtime_paths, datetime, hashlib, io, logging, os, platform, time, typing`
- Classes: `VisionSystem`
- Top-level functions: `<none>`
- Snippet:
```python
  57: class VisionSystem:
  58:     """
  59:     Real computer-vision layer.
  60:     Captures screen, reads text, locates UI elements, compares images.
  61:     """
  62: 
  63:     def __init__(self):
  64:         self._screenshot_dir = str(ensure_runtime_dir("screenshots"))
  65:         self._last_screenshot: Optional["Image.Image"] = None
  66:         self._easyocr_reader = None
  67:         self._cache: Dict[str, Dict] = {}
```
