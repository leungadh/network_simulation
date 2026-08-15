.PHONY: help pki nets csrx up config traffic verify check-order logs down reset clean

RUN_ID  ?= stage0-$(shell date +%Y%m%d-%H%M%S)
SEED    ?= 1337
PROJECT := netsim-stage0

# Read prefixes via the shell rather than `include .env`, so make never has to
# parse a file that is meant for docker.
# The guard matters: sourcing a missing file is a special-builtin failure that
# exits a non-interactive shell, so an unguarded `. ./.env` returns empty.
TRUST   := $(shell [ -f ./.env ] && . ./.env; echo $${TRUST_PREFIX:-10.20})
MGMT    := $(shell [ -f ./.env ] && . ./.env; echo $${MGMT_PREFIX:-172.30.0})
UNTRUST := $(shell [ -f ./.env ] && . ./.env; echo $${UNTRUST_PREFIX:-203.0.113})

help:
	@echo "Stage 0 — walking skeleton"
	@echo
	@echo "  make pki          lab CA + server certificate (once)"
	@echo "  make check-order  prove docker honours interface connect order"
	@echo "  make up           networks, sink, cSRX (ordered), web"
	@echo "  make config       push the Junos bootstrap config"
	@echo "  make traffic      run the workers and follow them"
	@echo "  make verify       check the Stage 0 exit criteria"
	@echo "  make down         stop and remove everything"
	@echo "  make reset        down + wipe outputs (keeps PKI)"
	@echo
	@echo "  trust=$(TRUST).0.0/16  mgmt=$(MGMT).0/24  untrust=$(UNTRUST).0/24"
	@echo "  RUN_ID=$(RUN_ID)  SEED=$(SEED)"

pki:
	@chmod +x pki/make-ca.sh csrx/apply-config.sh csrx/launch.sh
	@./pki/make-ca.sh

# `compose create` brings up the three networks and builds images without
# starting anything, so cSRX can be attached in a controlled order afterwards.
nets:
	@mkdir -p out
	RUN_ID=$(RUN_ID) SEED=$(SEED) docker compose build
	RUN_ID=$(RUN_ID) SEED=$(SEED) docker compose create

# Sanity check on the assumption everything else rests on: that connecting
# networks one at a time to a running container yields eth0, eth1, eth2 in call
# order. Uses a throwaway alpine container, costs about ten seconds.
check-order: nets
	@docker rm -f netsim-ordertest >/dev/null 2>&1 || true
	@docker run -d --name netsim-ordertest \
		--network $(PROJECT)_mgmt --ip $(MGMT).99 alpine sleep 120 >/dev/null
	@docker network connect --ip $(TRUST).0.99   $(PROJECT)_trust   netsim-ordertest
	@docker network connect --ip $(UNTRUST).99   $(PROJECT)_untrust netsim-ordertest
	@echo "expected:  eth0=$(MGMT).99  eth1=$(TRUST).0.99  eth2=$(UNTRUST).99"
	@echo "actual:"
	@docker exec netsim-ordertest ip addr \
		| awk '/^[0-9]+: /{gsub(/[:@].*/,"",$$2); i=$$2} /inet /{split($$2,a,"/"); if (i!="lo") print "  " i " = " a[1]}'
	@docker rm -f netsim-ordertest >/dev/null
	@echo
	@echo "If those match, connect ordering is reliable on this docker."

csrx:
	@./csrx/launch.sh

up: pki nets csrx
	docker compose start syslog-sink
	docker compose start web
	@echo
	@echo "==> cSRX is up and ordered. Next: make config"

config:
	@./csrx/apply-config.sh

traffic:
	RUN_ID=$(RUN_ID) SEED=$(SEED) docker compose start workstation
	@docker compose logs -f workstation

run: up config traffic verify

verify:
	@python3 verify.py

logs:
	docker compose logs -f

down:
	-docker rm -f netsim-csrx netsim-ordertest 2>/dev/null
	docker compose down --remove-orphans

reset: down
	rm -rf out
	@echo "==> outputs wiped. PKI kept — delete pki/*.crt pki/*.key to regenerate."

clean: down
	rm -rf out pki/*.crt pki/*.key pki/*.srl
	docker compose down --rmi local --volumes --remove-orphans
