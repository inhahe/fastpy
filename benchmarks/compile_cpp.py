"""Helper to compile C++ files using MSVC with /O2 optimization."""
import subprocess, os, tempfile

VCVARS = r'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat'

def compile_cpp(src_path, exe_path):
    """Compile a C++ source file to an optimized executable."""
    bat = tempfile.NamedTemporaryFile(suffix='.bat', delete=False, mode='w')
    bat.write('@echo off\n')
    bat.write(f'call "{VCVARS}" >nul 2>&1\n')
    bat.write(f'cl /nologo /O2 /EHsc "{src_path}" /Fe:"{exe_path}"\n')
    bat.close()
    result = subprocess.run([bat.name], capture_output=True, text=True, shell=True)
    os.unlink(bat.name)
    if not os.path.exists(exe_path):
        print(f"Compile failed: {result.stderr[:200]}")
        return False
    return True

if __name__ == "__main__":
    # Test
    src = os.path.join(tempfile.gettempdir(), "test_cpp.cpp")
    exe = os.path.join(tempfile.gettempdir(), "test_cpp.exe")
    with open(src, 'w') as f:
        f.write('#include <stdio.h>\nint main() { printf("hello from C++\\n"); return 0; }\n')
    if compile_cpp(src, exe):
        out = subprocess.run([exe], capture_output=True, text=True)
        print(f"OK: {out.stdout.strip()}")
    else:
        print("FAILED")
