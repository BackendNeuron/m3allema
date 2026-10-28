"""The public eval suite: real tasks, real models, checked automatically.

Each case is a YAML file: a task, the files it starts with, how approvals are
answered, and checks on what happened (files written, tools called or never
called, approvals asked, the answer). ``m3allema eval`` runs every case in a
throwaway copy of a workspace with that workspace's own models and keys, and
reports the pass rate per category.

The cases ship with the package (``m3allema/evals/cases``) so anyone can
reproduce the published numbers.
"""

from m3allema.evals.cases import EvalCase, load_cases
from m3allema.evals.runner import CaseResult, SuiteReport, run_suite

__all__ = ["CaseResult", "EvalCase", "SuiteReport", "load_cases", "run_suite"]
