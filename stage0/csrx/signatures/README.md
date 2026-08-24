# Application signature packages

Drop the Juniper application signature package here (`*.tgz`), then run:

```bash
make signatures
```

**Nothing in this directory is committed.** The package is licensed Juniper
software and large; `.gitignore` excludes it.

cSRX ships with no signature database, so without one AppID classifies every
session as `UNKNOWN`. The lab is airgapped by design, so the online download
cannot reach `signatures.juniper.net` — `csrx/install-signatures.sh` uses the
offline path (`request services application-identification offline-download`,
available from Junos 24.4R1).

The database lives in the container filesystem, so `make down` destroys it.
`make up` reinstalls automatically whenever a package is present here.
