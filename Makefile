# Thin wrappers over tools/cli.py. Nothing here computes locally.
PY ?= python3
CLI := $(PY) tools/cli.py
STAGE ?= ingest
SIZE ?= small
RUN ?=
RUNFLAG := $(if $(RUN),--run-id $(RUN),)
FORCEFLAG := $(if $(FORCE),--force,)

.PHONY: fmt help provision run pipeline exec status logs runs download release lint test paper qa package smoke

help:
	@echo "make provision                 # verify cloud toolchain"
	@echo "make run STAGE=q1 SIZE=medium  # run one stage (RUN=<id> to continue a run, FORCE=1 to rerun)"
	@echo "make pipeline                  # ingest,validate,lint,test in one container"
	@echo "make status | logs STAGE=q1 | runs | download STAGE=results"
	@echo "make paper | qa | package | release VERSION=v1.0.0"

provision:
	$(CLI) provision

run:
	$(CLI) run $(STAGE) $(RUNFLAG) --size $(SIZE) $(FORCEFLAG)

pipeline:
	$(CLI) run ingest,validate,lint,test $(RUNFLAG) --size $(SIZE) $(FORCEFLAG)

exec:
	$(CLI) exec --code '$(CODE)' $(RUNFLAG)

status:
	$(CLI) status $(RUNFLAG)

logs:
	$(CLI) logs $(STAGE) $(RUNFLAG)

runs:
	$(CLI) runs

download:
	$(CLI) download $(RUNFLAG) $(if $(STAGE),--stage $(STAGE),)

lint:
	$(CLI) run lint $(RUNFLAG) $(FORCEFLAG)

test:
	$(CLI) run test $(RUNFLAG) $(FORCEFLAG)

paper:
	$(CLI) run paper $(RUNFLAG) --size $(SIZE) $(FORCEFLAG)

qa:
	$(CLI) run qa $(RUNFLAG) $(FORCEFLAG)

package:
	$(CLI) run package $(RUNFLAG) $(FORCEFLAG)

release:
	$(CLI) run release $(RUNFLAG) $(FORCEFLAG) && $(CLI) release --version $(VERSION) $(RUNFLAG) --force

smoke:
	$(CLI) run ingest,validate,lint,test,paper,qa,package,release --new-run --param require_results=false --param allow_missing_results=true

fmt:
	$(CLI) fmt $(RUNFLAG)
