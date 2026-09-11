"""Problem D stages. Science stages (detect, resolve, pack, resolve_interval, results, figures, tables) go here.

Conventions (see docs/ENGINEERING_STANDARD.md):
  * every stage is ``@stage(name, deps=(...))`` and returns a JSON-serialisable metrics dict;
  * outputs go only to ``ctx.out(...)``; paper numbers via ``ctx.number("Key", value)``;
  * ``results`` writes result*.xlsx with ``forge.xlsx.write_result`` from the organisers' templates;
  * every optimisation result must be re-checked by an independent validator before it is written.
"""

from __future__ import annotations

from typing import Any

from forge.context import StageContext
from forge.runner import stage
from pipelines.common.validation import run_validation
from pipelines.d.contracts import INPUT_CONTRACTS


@stage("validate", deps=("ingest",), description="Validate the 150 frequency-use plans against their contract")
def validate(ctx: StageContext) -> dict[str, Any]:
    return run_validation(ctx, INPUT_CONTRACTS)
