"""
[INPUT]: N/A (python -m agri_guard_edge_survey)
[OUTPUT]: CLI exit code.
[POS]: Module entry for `python -m agri_guard_edge_survey`.
[PROTOCOL]:
 1. Delegate to cli.cli() only.
"""

from agri_guard_edge_survey.cli import cli

if __name__ == "__main__":
    cli()
