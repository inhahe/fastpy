@echo off
setlocal enabledelayedexpansion
REM Build the fastpy C runtime on Windows.
REM
REM Usage:
REM   build_runtime.bat                             Build for default Python
REM   build_runtime.bat D:\python314\python.exe     Build for a specific Python
REM
REM Shared files (objects, runtime, threading, gc, bigint) go in runtime/.
REM Per-version cpython_bridge.obj goes in runtime/py3XX/.
REM
REM NOTE: For multi-version builds, prefer using the Python toolchain:
REM   python -c "from compiler.toolchain import ensure_runtime_built; ensure_runtime_built()"
REM which handles MSVC quoting, response files, and version discovery automatically.

call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" 1>NUL 2>NUL
if errorlevel 1 (
    call "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat" 1>NUL 2>NUL
)

cd /d "%~dp0"

REM --- Build shared (Python-independent) runtime files ---
if not exist runtime.obj (
    cl.exe /c /O2 /nologo runtime.c /Foruntime.obj
    if errorlevel 1 (
        echo COMPILE_FAILED runtime.c
        exit /b 1
    )
)

if not exist objects.obj (
    cl.exe /c /O2 /nologo objects.c /Foobjects.obj
    if errorlevel 1 (
        echo COMPILE_FAILED objects.c
        exit /b 1
    )
)

if not exist threading.obj (
    cl.exe /c /O2 /nologo threading.c /Fothreading.obj
    if errorlevel 1 (
        echo COMPILE_FAILED threading.c
        exit /b 1
    )
)

if not exist gc.obj (
    cl.exe /c /O2 /nologo gc.c /Fogc.obj
    if errorlevel 1 (
        echo COMPILE_FAILED gc.c
        exit /b 1
    )
)

if not exist bigint.obj (
    cl.exe /c /O2 /nologo bigint.c /Fobigint.obj
    if errorlevel 1 (
        echo COMPILE_FAILED bigint.c
        exit /b 1
    )
)

REM --- Build cpython_bridge for target Python ---
REM Uses a cl.exe response file to avoid cmd.exe quote/backslash issues.

if "%~1"=="" (
    echo Building cpython_bridge for default Python...
    call :build_bridge_for_python python.exe
) else (
    echo Building cpython_bridge for %~1 ...
    call :build_bridge_for_python "%~1"
)

echo COMPILE_OK
exit /b 0


REM ============================================================
REM Subroutine: build cpython_bridge.obj for a given Python exe
REM ============================================================
:build_bridge_for_python
set "PYEXE=%~1"

REM Use a Python probe script to get version info and write a cl.exe
REM response file. This avoids all batch quoting issues.
set "_PROBE=%TEMP%\_fpy_probe.py"
set "_RSP=%~dp0_bridge_cl.rsp"

>"%_PROBE%" (
    echo import sys, sysconfig, os
    echo ver = f"{sys.version_info.major}{sys.version_info.minor}"
    echo inc = sysconfig.get_path("include"^)
    echo pfx = sys.prefix
    echo pfx_esc = pfx.replace("\\", "\\\\"^)
    echo script_dir = r"%~dp0"
    echo outdir = os.path.join(script_dir, f"py{ver}"^)
    echo os.makedirs(outdir, exist_ok=True^)
    echo out_obj = os.path.join(outdir, "cpython_bridge.obj"^)
    echo rsp = r"%_RSP%"
    echo # Write info for batch
    echo info_file = os.path.join(os.environ.get("TEMP", "."^), "_fpy_info.bat"^)
    echo with open(info_file, "w"^) as f:
    echo     f.write(f"set PYVER={ver}\n"^)
    echo     f.write(f"set OUT_OBJ={out_obj}\n"^)
    echo # Write response file for cl.exe
    echo with open(rsp, "w"^) as f:
    echo     f.write(f"/c /O2 /nologo\n"^)
    echo     f.write(f'/I "{inc}"\n'^)
    echo     f.write(f'/DPYTHON_HOME_STR=\\"{pfx_esc}\\"\n'^)
    echo     f.write("cpython_bridge.c\n"^)
    echo     f.write(f'/Fo"{out_obj}"\n'^)
)

"%PYEXE%" "%_PROBE%" 2>NUL
if errorlevel 1 (
    echo WARNING: Could not probe %PYEXE%, skipping.
    del "%_PROBE%" 2>NUL
    exit /b 0
)
del "%_PROBE%" 2>NUL

REM Source the info variables
set "_INFO=%TEMP%\_fpy_info.bat"
call "%_INFO%"
del "%_INFO%" 2>NUL

if "%PYVER%"=="" (
    echo WARNING: Could not determine version for %PYEXE%, skipping.
    del "%_RSP%" 2>NUL
    exit /b 0
)

REM Skip if already built
if exist "%OUT_OBJ%" (
    echo   py%PYVER%\cpython_bridge.obj already exists, skipping.
    del "%_RSP%" 2>NUL
    exit /b 0
)

echo   Compiling cpython_bridge.c for Python %PYVER% ...
cl.exe @"%_RSP%"
set "_CLRC=%errorlevel%"
del "%_RSP%" 2>NUL

if not "%_CLRC%"=="0" (
    echo COMPILE_FAILED cpython_bridge.c [Python %PYVER%]
    exit /b 1
)

REM Maintain legacy flat cpython_bridge.obj for backward compatibility
if not exist cpython_bridge.obj (
    copy "%OUT_OBJ%" cpython_bridge.obj >NUL
)

exit /b 0
