"""python -m test  →  unittest discover -s test/demo -p '*_test.py'

unittest's default pattern test*.py misses phase7_*_test.py.
"""
from .run import main

raise SystemExit(main())
