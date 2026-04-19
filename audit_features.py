"""Audit all Python 3.14 features against the fastpy compiler."""
import subprocess, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compiler.pipeline import compile_source

tests = {
    # === GENERATORS & ITERATORS ===
    'yield basic': 'def gen():\n    yield 1\n    yield 2\nfor x in gen(): print(x)',
    'yield from': 'def g(): yield from [1,2,3]\nprint(list(g()))',
    'gen expr iter': 'g=(x*x for x in range(5))\nfor v in g: print(v)',
    'send to gen': 'def g():\n    x=yield\n    yield x*2\nc=g();next(c);print(c.send(5))',
    # === ASYNC ===
    'async def': 'import asyncio\nasync def f(): return 1\nprint(asyncio.run(f()))',
    'await': 'import asyncio\nasync def f():\n    await asyncio.sleep(0)\n    return 1\nprint(asyncio.run(f()))',
    # === MATCH/CASE ===
    'match literal': 'x=2\nmatch x:\n    case 1: print("one")\n    case 2: print("two")',
    'match capture': 'x=(1,2)\nmatch x:\n    case (a,b): print(a,b)',
    'match guard': 'x=5\nmatch x:\n    case n if n>3: print("big")\n    case _: print("small")',
    'match or': 'x=2\nmatch x:\n    case 1|2|3: print("small")',
    # === DUNDER METHODS ===
    '__getitem__': 'class C:\n    def __getitem__(self,i): return i*2\nprint(C()[5])',
    '__setitem__': 'class C:\n    def __init__(self): self.d={}\n    def __setitem__(self,k,v): self.d[k]=v\nc=C();c["x"]=1;print(c.d["x"])',
    '__delitem__': 'class C:\n    def __delitem__(self,k): print(f"del {k}")\nc=C();del c["x"]',
    '__len__': 'class C:\n    def __len__(self): return 42\nprint(len(C()))',
    '__bool__': 'class C:\n    def __bool__(self): return False\nprint(bool(C()))',
    '__contains__': 'class C:\n    def __contains__(self,x): return x>0\nprint(1 in C())',
    '__iter__/__next__': 'class R:\n    def __init__(self,n): self.n=n;self.i=0\n    def __iter__(self): return self\n    def __next__(self):\n        if self.i>=self.n: raise StopIteration\n        self.i+=1;return self.i\nfor x in R(3): print(x)',
    '__call__': 'class C:\n    def __call__(self,x): return x*2\nprint(C()(5))',
    '__hash__': 'class C:\n    def __hash__(self): return 42\nprint(hash(C()))',
    '__repr__': 'class C:\n    def __repr__(self): return "C()"\nprint(repr(C()))',
    '__sub__': 'class V:\n    def __init__(self,x): self.x=x\n    def __sub__(self,o): return V(self.x-o.x)\n    def __str__(self): return str(self.x)\nprint(V(5)-V(3))',
    '__mul__': 'class V:\n    def __init__(self,x): self.x=x\n    def __mul__(self,o): return V(self.x*o.x)\n    def __str__(self): return str(self.x)\nprint(V(3)*V(4))',
    '__neg__': 'class V:\n    def __init__(self,x): self.x=x\n    def __neg__(self): return V(-self.x)\n    def __str__(self): return str(self.x)\nprint(-V(5))',
    '__eq__ custom': 'class C:\n    def __init__(self,v): self.v=v\n    def __eq__(self,o): return self.v==o.v\nprint(C(1)==C(1))',
    '__lt__ custom': 'class C:\n    def __init__(self,v): self.v=v\n    def __lt__(self,o): return self.v<o.v\nprint(C(1)<C(2))',
    # === PROPERTY / DESCRIPTORS ===
    '@property get': 'class C:\n    def __init__(self): self._x=5\n    @property\n    def x(self): return self._x\nprint(C().x)',
    '@property set': 'class C:\n    def __init__(self): self._x=0\n    @property\n    def x(self): return self._x\n    @x.setter\n    def x(self,v): self._x=v\nc=C();c.x=5;print(c.x)',
    # === DECORATORS ===
    'user decorator': 'def d(f):\n    def w(*a): return f(*a)\n    return w\n@d\ndef add(a,b): return a+b\nprint(add(1,2))',
    'deco with args': 'def rep(n):\n    def d(f):\n        def w(): [f() for _ in range(n)]\n        return w\n    return d\n@rep(3)\ndef hi(): print("hi")\nhi()',
    # === STAR EXPRESSIONS ===
    'print *list': 'print(*[1,2,3])',
    '*args call': 'def f(a,b,c): return a+b+c\nprint(f(*[1,2,3]))',
    '**kwargs call': 'def f(a=0,b=0): return a+b\nprint(f(**{"a":1,"b":2}))',
    '*mid unpack': 'a,*b,c=[1,2,3,4,5]\nprint(a,b,c)',
    # === TYPES ===
    'bytes literal': 'b=b"hello"\nprint(len(b))',
    'bytearray': 'b=bytearray(b"hello")\nprint(len(b))',
    'complex': 'c=complex(1,2)\nprint(c.real)',
    'frozenset': 'f=frozenset([1,2,3])\nprint(3 in f)',
    # === CLASSES ===
    'nested class': 'class A:\n    class B:\n        x=1\nprint(A.B.x)',
    'metaclass': 'class M(type): pass\nclass C(metaclass=M): pass\nprint(type(C).__name__)',
    '__slots__ py': 'class C:\n    __slots__=["x"]\n    def __init__(self): self.x=1\nprint(C().x)',
    # === EXCEPTIONS ===
    'raise from': 'try:\n    try: raise ValueError("a")\n    except ValueError as e: raise RuntimeError("b") from e\nexcept RuntimeError as e: print(e)',
    'except group': 'try:\n    raise ExceptionGroup("g",[ValueError("a")])\nexcept* ValueError: print("caught")',
    'bare raise': 'try:\n    try: raise ValueError("x")\n    except: raise\nexcept ValueError as e: print(e)',
    # === COMPREHENSIONS ===
    'set comp': 'print(sorted({x%3 for x in range(10)}))',
    'dict comp filter': 's={i:i*i for i in range(10) if i%2==0}\nfor k in sorted(s): print(k,s[k])',
    # === STRING ===
    'fstring =': 'x=42\nprint(f"{x=}")',
    'fstring !r': 'x="hi"\nprint(f"{x!r}")',
    'raw string': 'print(r"\\n")',
    # === MISC ===
    'walrus': 'if (n:=10)>5: print(n)',
    'type hints': 'def f(x:int)->int: return x+1\nprint(f(5))',
    'chained cmp': 'print(1<2<3)',
    'ternary': 'x=5\nprint("big" if x>3 else "small")',
    'multi assign': 'a=b=c=10\nprint(a,b,c)',
    'tuple swap': 'a,b=1,2\na,b=b,a\nprint(a,b)',
    'for else': 'for i in range(3): pass\nelse: print("done")',
    'while else': 'i=0\nwhile i<3: i+=1\nelse: print("done")',
    'assert msg': 'try:\n    assert False,"oops"\nexcept AssertionError as e:\n    print(e)',
    'global': 'x=0\ndef f(): global x;x=10\nf()\nprint(x)',
    'nonlocal': 'def f():\n    x=0\n    def g(): nonlocal x;x=5\n    g();return x\nprint(f())',
    'lambda 3arg': 'f=lambda x,y,z:x+y+z\nprint(f(1,2,3))',
    'list *=': 'a=[1,2]\na*=3\nprint(a)',
    'slice obj': 'print([1,2,3,4,5][1:4])',
    'ellipsis': 'x=...\nprint(x is ...)',
    'dict |=': 'd={"a":1}\nd.update({"b":2})\nprint(sorted(d.keys()))',
    'import module': 'import math\nprint(math.sqrt(4.0))',
    'from import': 'from math import sqrt\nprint(sqrt(9.0))',
}

passed = 0
failed_list = []
for name, src in tests.items():
    try:
        r = compile_source(src)
        if r.success:
            out = subprocess.run([str(r.executable)], capture_output=True, text=True, timeout=5)
            cp = subprocess.run([sys.executable, '-c', src], capture_output=True, text=True, timeout=5)
            if out.stdout.strip() == cp.stdout.strip() and out.returncode == cp.returncode:
                passed += 1
                continue
            else:
                reason = f'wrong output: got [{out.stdout.strip()[:30]}] expected [{cp.stdout.strip()[:30]}]'
                if out.returncode != 0:
                    reason = f'crash (rc={out.returncode})'
        else:
            err = str(r.errors[0])[:60] if r.errors else '?'
            reason = f'compile: {err}'
    except subprocess.TimeoutExpired:
        reason = 'timeout (hang)'
    except Exception as e:
        reason = f'error: {str(e)[:50]}'
    failed_list.append((name, reason, src))

total = passed + len(failed_list)
print(f'{passed}/{total} features working\n')
print('MISSING FEATURES:')
for name, reason, src in failed_list:
    print(f'  {name:25s}  {reason}')
