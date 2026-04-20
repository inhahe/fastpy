@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" 1>NUL 2>NUL
if errorlevel 1 (
    call "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat" 1>NUL 2>NUL
)
cd /d "D:\visual studio projects\fastpy\runtime"
cl.exe /c /O2 /nologo runtime.c /Foruntime.obj
if errorlevel 1 (
    echo COMPILE_FAILED runtime.c
    exit /b 1
)
cl.exe /c /O2 /nologo objects.c /Foobjects.obj
if errorlevel 1 (
    echo COMPILE_FAILED objects.c
    exit /b 1
)
cl.exe /c /O2 /nologo /I "D:\python314\include" cpython_bridge.c /Focpython_bridge.obj
if errorlevel 1 (
    echo COMPILE_FAILED cpython_bridge.c
    exit /b 1
)
cl.exe /c /O2 /nologo threading.c /Fothreading.obj
if errorlevel 1 (
    echo COMPILE_FAILED threading.c
    exit /b 1
)
cl.exe /c /O2 /nologo gc.c /Fogc.obj
if errorlevel 1 (
    echo COMPILE_FAILED gc.c
    exit /b 1
)
echo COMPILE_OK
