# Signed CLI commands must not recreate PostgreSQL

Decision: 2026-11-17. During read-only close monitoring, the existing
`scripts/sentinel-authorized-cli.sh inspect-paper-account` command invoked
`docker compose run` with its declared dependencies. Compose recreated the
running PostgreSQL service before the signed CLI refused because no
administrative certificate was active. The data directory and PAPER fence
survived, but a read-only account inspection must not change service state.
The exact configuration difference that triggered recreation is not yet
established; the observed dependency side effect is sufficient to correct
the wrapper.

The host wrapper first observes, without starting or updating services, that
the existing Compose PostgreSQL service is running and healthy. If it is absent,
unhealthy, ambiguous or Docker is unavailable, the wrapper refuses. It then
runs the existing `sentinel-authority-permissions` helper explicitly with
`--no-deps`, preserving the public certificate and directory read grants.
Finally it runs the named signed CLI command with `--no-deps`. The wrapper may
create only the two requested one-shot containers, never a dependent database,
shadow, automation or execution service. A readiness race after its health
check causes the command to fail under its normal database and authority gates;
the wrapper does not retry by starting PostgreSQL.

Keep the immutable image, signed authority, PAPER account, execution membrane
and disabled/kill requirements unchanged. This wrapper does not grant an
administrative certificate or broker permission. The host activation
coordinator already uses explicit dependency ownership and `--no-deps`; its
fenced recovery route retains that path.

Qualify the exact script with a fake Docker executable: prove a healthy
existing PostgreSQL yields only `ps`, `inspect`, the no-dependency permission
helper and the no-dependency signed command, with caller arguments intact.
An absent/unhealthy database or a failed helper must stop before the signed
command. A falsifier that removes either `--no-deps` must fail the command
sequence assertion. No production host command is part of this qualification.
