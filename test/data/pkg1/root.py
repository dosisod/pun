# should not be inlined
import sys
from sys import argv

from test.data.pkg1.a import f

f()
