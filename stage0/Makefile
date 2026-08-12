.PHONY: help pki up config run verify logs down clean reset

RUN_ID ?= stage0-$(shell date +%Y%m%d-%H%M%S)
SEED   ?= 1337

help:
	@echo "Stage 0 — walking skeleton"
	@echo
	@echo "  make pki      generate the lab CA and server certificate (once)"
	@echo "  make up       build and start cSRX, syslog sink, web, workstation"
	@echo "  make config   push the Junos bootstrap config to cSRX"
	@echo "  make run      full sequence: pki -> up -> config -> traffic -> verify"
	@echo "  make verify   check the Stage 0 exit criteria"
	@echo "  make logs     tail all container logs"
	@echo "  make down     stop everything"
	@echo "  make reset    stop, wipe outputs, keep images"
	@echo
	@echo "  RUN_ID=$(RUN_ID)"
	@echo "  SEED=$(SEED)"

pki:
	@chmod +x pki/make-ca.sh csrx/apply-config.sh
	@./pki/make-ca.sh

up: pki
	@mkdir -p out
	RUN_ID=$(RUN_ID) SEED=$(SEED) docker compose up -d --build
	@echo "==> waiting for cSRX to settle"

config:
	@./csrx/apply-config.sh

# The workstation container exits when DURATION_S elapses, so this blocks
# until the traffic run is finished.
traffic:
	@echo "==> running traffic; this takes DURATION_S seconds"
	@docker compose logs -f workstation

run: up config traffic verify

verify:
	@python3 verify.py

logs:
	docker compose logs -f

down:
	docker compose down --remove-orphans

reset: down
	rm -rf out
	@echo "==> outputs wiped. PKI kept — delete pki/*.crt pki/*.key to regenerate."

clean: down
	rm -rf out pki/*.crt pki/*.key pki/*.srl
	docker compose down --rmi local --volumes --remove-orphans
