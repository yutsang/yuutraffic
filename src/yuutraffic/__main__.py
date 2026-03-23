"""YuuTraffic CLI — two commands:

  yuutraffic           Launch the Streamlit app
  yuutraffic --update  Initialise DB if needed, refresh KMB + Citybus + GMB + MTR Bus +
                       red minibus, then incremental map geometry (OSM)

Advanced: python -m yuutraffic.data_updater (partial flags) · python -m yuutraffic.precompute
"""

import argparse
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
        print(
            "The `precompute` subcommand was removed. Use:\n  yuutraffic --update",
            file=sys.stderr,
        )
        sys.exit(2)

    parser = argparse.ArgumentParser(
        prog="yuutraffic",
        description="Hong Kong public transport explorer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  yuutraffic           Launch the web UI\n"
            "  yuutraffic --update  Refresh DB + maps (skips heavy work if catalog looks complete; see conf)"
        ),
    )
    parser.add_argument(
        "--update",
        "-u",
        action="store_true",
        help="Refresh DB + maps when needed; skips API/geometry if catalog row counts look complete (see conf).",
    )
    args = parser.parse_args()

    if args.update:
        from yuutraffic.cli_update import run_update

        sys.exit(run_update(project_root=_project_root))

    from yuutraffic.launcher import main as launcher_main

    launcher_main()


if __name__ == "__main__":
    main()
