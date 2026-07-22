# Regression: custom exception with super().__init__(msg) stored the wrong
# message.  str(e) showed the first constructor arg instead of the arg
# passed to super().__init__().

# 1. Multi-arg exception: code is first arg, msg is second
class AppError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code

try:
    raise AppError(404, "not found")
except AppError as e:
    print(e.code)
    print(str(e))

# 2. Three-arg exception
class DetailError(Exception):
    def __init__(self, code, msg, extra):
        super().__init__(msg)
        self.code = code
        self.extra = extra

try:
    raise DetailError(500, "server error", True)
except DetailError as e:
    print(str(e))
    print(e.code)
    print(e.extra)

# 3. Single-arg exception (regression check)
class SimpleError(Exception):
    def __init__(self, msg):
        super().__init__(msg)

try:
    raise SimpleError("oops")
except SimpleError as e:
    print(str(e))
