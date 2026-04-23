from setuptools import setup, Extension

setup(
    name='fastpy',
    packages=['fastpy'],
    ext_modules=[
        Extension('fastpy._fastints', ['fastpy/_fastints.c']),
    ],
)
