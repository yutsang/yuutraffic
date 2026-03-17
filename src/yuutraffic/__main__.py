"""YuuTraffic - Hong Kong Public Transport Analytics.
Run with: yuutraffic  or  python -m yuutraffic
Precompute routing: yuutraffic precompute  or  python -m yuutraffic precompute
"""

import os
import sys


def main():
    _pkg_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.abspath(os.path.join(_pkg_dir, "..", ".."))
    os.chdir(_project_root)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    _src = os.path.join(_project_root, "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)

    if len(sys.argv) > 1 and sys.argv[1] == "precompute":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        from yuutraffic.precompute import main as precompute_main

        precompute_main()
    else:
        from yuutraffic.launcher import main as launcher_main

        launcher_main()


if __name__ == "__main__":
    main()
