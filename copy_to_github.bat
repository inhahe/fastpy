@echo off
REM Copy fastpy project files to D:\utils\fastpy for GitHub push.
REM Excludes: .obj, .exe, .pdb, __pycache__, .hypothesis, .pytest_cache,
REM           python.txt, sessionname.txt, todo.txt, CLAUDE.md,
REM           SESSION_SUMMARY.md (session-specific, not for public repo)

set SRC=D:\visual studio projects\fastpy
set DST=D:\utils\fastpy

echo Copying fastpy to %DST%...

REM Create destination if it doesn't exist (do NOT delete existing files)
if not exist "%DST%" mkdir "%DST%"

REM Root files
copy "%SRC%\.gitignore" "%DST%\"
copy "%SRC%\pyproject.toml" "%DST%\"
copy "%SRC%\BENCHMARK_REPORT.md" "%DST%\"
copy "%SRC%\BENCHMARK_RESULTS.txt" "%DST%\"
copy "%SRC%\FUTURE_OPTIMIZATIONS.md" "%DST%\"
copy "%SRC%\UNIMPLEMENTED.md" "%DST%\"
copy "%SRC%\audit_features.py" "%DST%\"

REM Compiler
mkdir "%DST%\compiler"
copy "%SRC%\compiler\__init__.py" "%DST%\compiler\"
copy "%SRC%\compiler\__main__.py" "%DST%\compiler\"
copy "%SRC%\compiler\codegen.py" "%DST%\compiler\"
copy "%SRC%\compiler\pipeline.py" "%DST%\compiler\"
copy "%SRC%\compiler\toolchain.py" "%DST%\compiler\"

REM Runtime (source only, no .obj)
mkdir "%DST%\runtime"
copy "%SRC%\runtime\objects.c" "%DST%\runtime\"
copy "%SRC%\runtime\objects.h" "%DST%\runtime\"
copy "%SRC%\runtime\runtime.c" "%DST%\runtime\"
copy "%SRC%\runtime\cpython_bridge.c" "%DST%\runtime\"
copy "%SRC%\runtime\build_runtime.bat" "%DST%\runtime\"

REM fastpy package
mkdir "%DST%\fastpy"
copy "%SRC%\fastpy\__init__.py" "%DST%\fastpy\"
copy "%SRC%\fastpy\ints.py" "%DST%\fastpy\"

REM Tests
mkdir "%DST%\tests"
copy "%SRC%\tests\__init__.py" "%DST%\tests\"
copy "%SRC%\tests\conftest.py" "%DST%\tests\"
copy "%SRC%\tests\harness.py" "%DST%\tests\"
copy "%SRC%\tests\test_differential.py" "%DST%\tests\"
copy "%SRC%\tests\test_generated.py" "%DST%\tests\"
copy "%SRC%\tests\test_shim.py" "%DST%\tests\"

mkdir "%DST%\tests\generator"
copy "%SRC%\tests\generator\__init__.py" "%DST%\tests\generator\"
copy "%SRC%\tests\generator\gen.py" "%DST%\tests\generator\"

mkdir "%DST%\tests\programs"
copy "%SRC%\tests\programs\*.py" "%DST%\tests\programs\"

mkdir "%DST%\tests\regressions"
copy "%SRC%\tests\regressions\*.py" "%DST%\tests\regressions\"

REM Benchmarks
mkdir "%DST%\benchmarks"
copy "%SRC%\benchmarks\alloc_bench.py" "%DST%\benchmarks\"
copy "%SRC%\benchmarks\compile_cpp.py" "%DST%\benchmarks\"
copy "%SRC%\benchmarks\run_comparison.py" "%DST%\benchmarks\"

REM Tools (empty for now)
mkdir "%DST%\tools"

echo.
echo Done. Files copied to %DST%
echo.
echo To push to GitHub:
echo   cd %DST%
echo   git init
echo   git add -A
echo   git commit -m "Initial commit"
echo   git remote add origin https://github.com/YOUR_USERNAME/fastpy.git
echo   git push -u origin master
