.PHONY: help pki nets csrx up config traffic verify check-order logs down reset clean

RUN_ID  ?= run-$(shell date +%Y%m%d-%H%M%S)
SEED    ?= 1337
PROJECT := netsim

# Read prefixes via the shell rather than `include .env`, so make never has to
# parse a file that is meant for docker.
# The guard matters: sourcing a missing file is a special-builtin failure that
# exits a non-interactive shell, so an unguarded `. ./.env` returns empty.
TRUST   := $(shell [ -f ./.env ] && . ./.env; echo $${TRUST_PREFIX:-10.20})
MGMT    := $(shell [ -f ./.env ] && . ./.env; echo $${MGMT_PREFIX:-172.30.0})
UNTRUST := $(shell [ -f ./.env ] && . ./.env; echo $${UNTRUST_PREFIX:-203.0.113})

# One switch, two docker settings. Egress requires internal=false AND
# masquerade=true; setting only one produces a container that can transmit but
# never receive replies, which looks exactly like "no internet".
TELEMETRY := $(shell [ -f ./.env ] && . ./.env; echo $${TELEMETRY_PREFIX:-172.32.0})
GF_PORT   := $(shell [ -f ./.env ] && . ./.env; echo $${GRAFANA_PORT:-3000})

MGMT_EGRESS     := $(shell [ -f ./.env ] && . ./.env; echo $${MGMT_EGRESS:-false})
MGMT_INTERNAL   := $(if $(filter true,$(MGMT_EGRESS)),false,true)
MGMT_MASQUERADE := $(if $(filter true,$(MGMT_EGRESS)),true,false)
export MGMT_INTERNAL
export MGMT_MASQUERADE

help:
	@echo "Stage 1 — walking skeleton"
	@echo
	@echo "  make pki          lab CA + server certificate (once)"
	@echo "  make signatures   install the AppID signature package (see csrx/signatures/)"
	@echo "  make signatures-online  download it instead (needs MGMT_INTERNAL=false)"
	@echo "  make check-order  prove docker honours interface connect order"
	@echo "  make up           networks, sink, cSRX (ordered), web"
	@echo "  make config       push the Junos bootstrap config"
	@echo "  make traffic      run the workers and follow them"
	@echo "  make verify       check the exit criteria (from ClickHouse)"
	@echo "  make runs         per-run health summary"
	@echo "  make dashboard      regenerate and reload the Grafana dashboard"
	@echo "  make dashboard-open open it in a browser"
	@echo "  make sql Q=...    ad-hoc ClickHouse query"
	@echo "  make vector-check compile-check vector.yaml without starting anything"
	@echo "  make status       what is running, and is the AppID database intact"
	@echo "  make down         stop and remove everything (DESTROYS the AppID database)"
	@echo "  make reset        down + wipe outputs (keeps PKI)"
	@echo
	@echo "  trust=$(TRUST).0.0/16  mgmt=$(MGMT).0/24  untrust=$(UNTRUST).0/24"
	@echo "  mgmt egress=$(MGMT_EGRESS)  (internal=$(MGMT_INTERNAL) masquerade=$(MGMT_MASQUERADE))"
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

# Install the AppID signature database from csrx/signatures/. cSRX ships with
# none, so without this every session is classified UNKNOWN.
signatures:
	@./csrx/install-signatures.sh

# Online download. Needs MGMT_INTERNAL=false in .env and `make down && make up`
# so the management bridge is recreated with egress.
signatures-online:
	@echo "--- mgmt egress: $(MGMT_EGRESS) (internal=$(MGMT_INTERNAL) masq=$(MGMT_MASQUERADE)) ---"
	@[ "$(MGMT_EGRESS)" = "true" ] || { echo "!! set MGMT_EGRESS=true in .env, then: make down && make up"; exit 1; }
	@echo '--- default route inside cSRX ---'
	@docker exec netsim-csrx ip route | sed 's/^/    /'
	@echo
	@echo '--- can cSRX reach the internet? ---'
	@docker exec netsim-csrx ping -c 2 -W 3 8.8.8.8 || \
		{ echo; echo "!! no egress. Set MGMT_INTERNAL=false in .env, then:"; \
		  echo "     make down && make up"; exit 1; }
	@echo
	@echo '--- can it resolve the download server? ---'
	@docker exec netsim-csrx getent hosts signatures.juniper.net || \
		echo "!! DNS failed — add 'set system name-server 8.8.8.8' to bootstrap.set"
	@echo
	docker exec -it netsim-csrx cli -c 'request services application-identification download'
	@sleep 5
	docker exec -it netsim-csrx cli -c 'request services application-identification download status'
	docker exec -it netsim-csrx cli -c 'request services application-identification install'
	@sleep 10
	docker exec -it netsim-csrx cli -c 'request services application-identification install status'
	docker exec -it netsim-csrx cli -c 'show services application-identification status'

up: pki nets csrx
	docker compose up -d clickhouse
	docker compose up -d vector
	docker compose up -d grafana
	docker compose start web
	@echo
	@# The signature database lives in the container filesystem, so recreating
	@# cSRX destroys it. Reinstall whenever a package is available; absence is
	@# not fatal, it just means AppID reports UNKNOWN.
	@SOFT_FAIL=0 ./csrx/install-signatures.sh || true
	@echo
	@echo "==> cSRX is up and ordered. Next: make config"
	@echo "    Grafana: http://localhost:$(GF_PORT)  (anonymous viewer access)"

config:
	@./csrx/apply-config.sh

# Recreate BOTH the sink and the workstation with the same RUN_ID.
#
# RUN_ID is baked into each container's environment at create time. The sink
# stamps it onto flows.csv and the engine stamps it onto intents.jsonl — if the
# two containers are created by different make invocations they get different
# ids, and the two halves of the ground truth can never be correlated. This is
# the only place a run id is minted.
traffic:
	@echo "$(RUN_ID)" > out/current_run_id
	@echo "==> run_id: $(RUN_ID)"
	@# Vector stamps run_id onto every flow row, so it is recreated alongside
	@# the engine. Two containers minting their own ids was a real defect.
	RUN_ID=$(RUN_ID) SEED=$(SEED) docker compose up -d --force-recreate vector
	@sleep 2
	RUN_ID=$(RUN_ID) SEED=$(SEED) docker compose up -d --force-recreate workstation
	@docker compose logs -f workstation

# Score the run recorded by the last `make traffic`, from ClickHouse.
verify:
	@RUN_ID=$$(cat out/current_run_id 2>/dev/null) GRAFANA_PORT=$(GF_PORT) python3 verify_sql.py

# Stage 1's CSV-based verifier. Only meaningful with the legacy python sink:
#   docker compose --profile legacy up -d syslog-sink
verify-csv:
	@RUN_ID=$$(cat out/current_run_id 2>/dev/null) python3 verify.py

# Open the dashboard (or just browse to http://localhost:$(GF_PORT)).
dashboard-open:
	@echo "==> http://localhost:$(GF_PORT)/d/netsim-stage2"
	-@xdg-open "http://localhost:$(GF_PORT)/d/netsim-stage2" >/dev/null 2>&1 || true

# Regenerate the Grafana dashboard from its generator, then reload it.
dashboard:
	cd telemetry/grafana && python3 make_dashboard.py \
		&& mv netsim-stage2.json dashboards/netsim-stage2.json
	@docker restart netsim-grafana >/dev/null 2>&1 || true
	@echo "==> http://localhost:$(GF_PORT)"

# Ad-hoc query:  make sql Q="SELECT count() FROM netsim.flows"
CH_USER := $(shell [ -f ./.env ] && . ./.env; echo $${CLICKHOUSE_USER:-netsim})
CH_PASS := $(shell [ -f ./.env ] && . ./.env; echo $${CLICKHOUSE_PASSWORD:-netsim})

sql:
	@curl -sS "http://127.0.0.1:8123/" \
		-H "X-ClickHouse-User: $(CH_USER)" -H "X-ClickHouse-Key: $(CH_PASS)" \
		--data-binary "$${Q:-SELECT 1}"

# Per-run health straight from the view every later stage consumes.
runs:
	@curl -sS "http://127.0.0.1:8123/" \
		-H "X-ClickHouse-User: $(CH_USER)" -H "X-ClickHouse-Key: $(CH_PASS)" \
		--data-binary "SELECT * FROM netsim.run_summary FORMAT PrettyCompact"

# Compile-check the Vector config WITHOUT touching the running stack.
#
# A VRL syntax error is fatal to the entire config, not just the offending
# transform — one bad expression in the RT_FLOW parser also killed the intents
# pipeline, which has nothing to do with cSRX. Both sources went to zero and
# the container exited 78. Run this after any edit to vector.yaml.
vector-check:
	@docker run --rm \
		-v "$$(pwd)/telemetry/vector/vector.yaml:/etc/vector/vector.yaml:ro" \
		-e RUN_ID=check -e CLICKHOUSE_USER=$(CH_USER) -e CLICKHOUSE_PASSWORD=$(CH_PASS) \
		timberio/vector:0.41.1-alpine \
		validate --no-environment --config-yaml /etc/vector/vector.yaml \
		&& echo "==> vector config OK"

# Diagnose source-port capture, the join key the labelled dataset rests on.
probe-port:
	docker compose build workstation
	docker compose run --rm --entrypoint python workstation -u /app/probe_port.py

# Walk the data path hop by hop. Answers "where do packets stop?" without
# depending on the workstation container being up.
path-check:
	@echo '--- 1. interfaces (stderr shown: cSRX omits some Junos commands) ---'
	-@docker exec netsim-csrx cli -c 'show interfaces terse'
	@echo
	@echo '--- 2. configured interfaces ---'
	-@docker exec netsim-csrx cli -c 'show configuration interfaces'
	@echo
	@echo '--- 3. zones and policy ---'
	-@docker exec netsim-csrx cli -c 'show configuration security zones'
	-@docker exec netsim-csrx cli -c 'show configuration security policies'
	@echo
	@echo '--- 4. TRUST side: can cSRX reach the workstation? ---'
	-@docker exec netsim-csrx cli -c 'ping $(TRUST).0.100 count 3 wait 2'
	@echo
	@echo '--- 5. UNTRUST side: can cSRX reach the web server? ---'
	-@docker exec netsim-csrx cli -c 'ping $(UNTRUST).10 count 3 wait 2'
	@echo
	@echo '--- 6. did nginx see ANY request? ---'
	-@docker logs netsim-web 2>&1 | tail -12
	@echo
	@echo '--- 7. sessions ---'
	-@docker exec netsim-csrx cli -c 'show security flow session summary'

# Watch the untrust side while traffic runs: does the SYN actually arrive at
# the web server, and does it answer? Run in one terminal, `make traffic` in
# another.
tcpdump-web:
	docker compose build web
	docker compose up -d web
	docker exec netsim-web tcpdump -i eth0 -n -c 40 'tcp port 443 or icmp'

# First-hop reachability without depending on the workstation being up.
ping-gw:
	@docker run --rm --network $(PROJECT)_trust --ip $(TRUST).1.99 \
		alpine sh -c 'ip route; echo; ping -c 3 -W 2 $(TRUST).0.1'


run: up config traffic verify

# What is actually running, and is the AppID database still there? Run this
# first when picking the lab up after a break or a reboot.
status:
	@echo '--- containers ---'
	@docker ps -a --filter name=netsim --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
	@echo
	@echo '--- networks ---'
	@docker network ls --filter name=$(PROJECT) --format '  {{.Name}}'
	@echo
	@echo '--- cSRX dataplane ---'
	@docker exec netsim-csrx pgrep srxpfe >/dev/null 2>&1 \
		&& echo '  srxpfe running' || echo '  srxpfe NOT running'
	@echo
	@echo '--- AppID signature database (destroyed by make down) ---'
	-@docker exec netsim-csrx cli -c 'show services application-identification status' 2>/dev/null \
		| grep -E 'Application package version|Release date' | sed 's/^/  /'
	@echo
	@echo '--- telemetry ---'
	-@curl -sS --max-time 3 "http://127.0.0.1:8123/ping" 2>/dev/null | sed 's/^/  clickhouse: /' || echo '  clickhouse: unreachable'
	-@curl -sS --max-time 3 -o /dev/null -w '  grafana:    HTTP %{http_code}\n' "http://127.0.0.1:$(GF_PORT)/api/health" 2>/dev/null || echo '  grafana:    unreachable'
	-@curl -sS --max-time 3 "http://127.0.0.1:8123/" \
		-H "X-ClickHouse-User: $(CH_USER)" -H "X-ClickHouse-Key: $(CH_PASS)" \
		--data-binary "SELECT count() FROM netsim.flows" 2>/dev/null | sed 's/^/  flow rows:  /'
	@echo
	@echo '--- last run ---'
	@echo "  run_id: $$(cat out/current_run_id 2>/dev/null || echo '(none)')"
	@echo "  intents: $$(wc -l < out/intents.jsonl 2>/dev/null || echo 0) lines"
	@echo "  flows:   $$(wc -l < out/flows.csv 2>/dev/null || echo 0) lines"

logs:
	docker compose logs -f

# Sweep by NAME, not just by compose project.
#
# cSRX is launched outside compose, and a compose project rename leaves the
# previous project's containers stranded — `docker compose down` only knows
# about the project named in docker-compose.yml. The name filter is anchored to
# "netsim-" so it cannot touch other labs on this host.
down:
	-@docker ps -aq --filter "name=^netsim-" | xargs -r docker rm -f
	-@docker compose down --remove-orphans 2>/dev/null
	@# Networks from a previous project name would keep holding our subnets.
	@# Docker refuses to remove one still in use, so this is safe.
	-@docker network ls -q --filter "name=netsim" | xargs -r docker network rm 2>/dev/null
	@echo "==> down. Note: this destroyed the AppID signature database."
	@echo "    make up reinstalls it from csrx/signatures/ if a package is there."

reset: down
	rm -rf out
	@echo "==> outputs wiped. PKI kept — delete pki/*.crt pki/*.key to regenerate."

clean: down
	rm -rf out pki/*.crt pki/*.key pki/*.srl
	docker compose down --rmi local --volumes --remove-orphans
