# should not be inlined
import sys

print("hello from pkg1.a!")


def f():
    print("Hello from pkg1.a.f!")


f()
