# Signed PAPER installation with independent backup policy

Decision: 2026-10-24, before implementation, extending
`paper-backed-release-20261024.md`. Keep the existing owner-authorized PAPER
account/runtime policy while independently selecting `REQUIRED_V1` backups.
Canonical Compose forwards that non-secret context; its signed immutable image
selector and ordinary archive overlay remain authoritative. The legacy local
image/archive-off overlay is not part of a full signed installation.

The software installer remains independent of broker credentials, source GO,
trading hours and financial activation. It installs the panel, broker-free
verifier and configured notification sender after fencing and schema readiness.
It creates the automation, shadow and GET-only collector containers dormant.
The collector starts only in activation after the attested shadow is resumed;
its account credentials never enter the verifier, panel or sender. The final
activation verifies collector and verifier liveness in addition to the existing
shadow/automation/leader/account checks. This does not grant a collector any
submission, cancellation, source publication or push-signing authority.

Before a database configuration/schema transition, the coordinator stops the
existing verifier and collector as well as financial writers. It targets only
the two constant Sentinel Compose role labels and exact observed container IDs,
using finite process shutdown. Ordinary availability fencing need not stop
read-only diagnostics. Restart the verifier as an operator service after schema
readiness, and the collector only at financial activation. A failed or absent
role cannot be hidden by producing an installation or activation receipt.

Bootstrap discovery is observation only. Its one-shot status reader uses Compose
`run --no-deps`, so reading the existing account identity cannot start or recreate
PostgreSQL from a new checkout's archive command or mounts before the deployment
fence. If the existing database is unavailable, discovery returns no observation;
it does not start dependencies or invent ownership. PostgreSQL configuration and
mount changes remain owned by the subsequent fenced transition. First-install
receipt-secret provisioning retains its separate empty-history contract; this
upgrade preserves the existing authenticated receipt key.

The semantic restore remains broker-free on its private network and
server-enforced read-only database. Forward the actual owner PAPER mode/account,
backup policy, protected DAY BUY policy, exact source/image/test identity and
reviewed shadow context into its exact runtime. These are the original reviewed
inputs, not a replacement admission or a synthetic historical certificate.
The restore receives the existing receipt key and isolated database password by
environment-variable name, never literal command arguments. It receives no
broker, provider, signer-file or push credentials, and never contacts Alpaca.

The host literal parser rejects unknown durability selections and an enabled
durability selection without the exact owner PAPER mode/account. Default empty
selection retains old suspended deployments and their isolated fixtures; it is
not the backed release's selection. An exact PAPER endpoint and 100-basis-point
protected BUY policy remain required for owner mode. Runtime validators remain
the final authority for actual binding, source, image, account and backup media.

## Operator procedure

After required exact-head CI passes, merge the PR and wait for successful main
qualification and protected signed publication. Use the clean merged `main`
checkout on the Linux/WSL host and its safe literal environment. Preserve the
actual account binding, receipt/signing authority, canonical book, plans,
commands, notifications, source history and PostgreSQL volume/system identity.
Set the explicit backup selection through the supported environment writer.
Provision and independently validate the actual backup media before relying on
its marker. Never source the environment or copy credentials into reports.

The public command is:

```text
bash scripts/sentinel-autonomous-deploy.sh --mode dual --activate-when-ready
```

Software success is immutable `INSTALLED/FENCED`, not trading permission. Its
separate activation coordinator must earn current retained-book/source admission,
fresh signed PAPER authority, exact saved-plan reconciliation, continuous archive
and exact-image full semantic/physical recovery proof before kill release.
Existing schema needs no repeated physical copy merely to install software.
Maintenance handoff and retention remain under the canonical media lock and
their existing actual-current-image proof requirements.

The archive-off to archive-on transition may narrowly recreate only Sentinel
PostgreSQL while financial writers are fenced. Preserve its exact existing
volume and physical system identity. Do not use `down`, global Docker/WSL resets,
initial-account flags, a new strategy genesis or an old command replay.

Qualification uses targeted host/Compose/restore environment and lifecycle tests,
including missing-role, image/context, credential isolation and guard-removal
falsifiers. CI remains software evidence; native financial/provider and historical
economic acceptance retain their separate scopes. The backtest stays untouched
and LIVE endpoints remain forbidden.
