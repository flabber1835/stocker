"""Sentinel's command-line entrypoint.

The CLI keeps four authorities visibly separate: read-only inspection,
paper-plan preparation with durable database writes but no broker mutation, the
one-time administrative legacy handover, and separately confirmed paper-plan
execution. The exact activation sequence and command arguments live only in
`docs/sentinel-paper-activation.md`.

The old JSONL-backed `plan` command is RETIRED and only names its replacements.
`inspect-paper-account` is the exact inherited-book view, while
`migration-plan` prints the read-only target delta. Both require signed
administrative authority and read the named paper account, but neither exposes
a broker mutation.
`prepare-paper-plan` is a different
dry-run boundary: it never mutates the broker, but it intentionally advances
canonical database state and adopts the latest durable plan.

`establish-ownership` is RETIRED and survives only to refuse and name its
replacement: it classified an account as a legacy Stocker book whenever a JSONL
file said nothing, so losing one file on one volume re-armed a liquidation
against a Wealth Core book. Ordinary startup now has no liquidation path at all,
and the binding lives in PostgreSQL beside the state it protects.

Exit codes are meant for a supervisor:

```text
0  the requested inspection, preparation, migration, or execution step completed
1  configuration refused (live endpoint, missing credentials)
2  ownership, readiness, reconciliation, or current-plan authority is not
   established — a human is needed, and the requested transition did not proceed
```
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import inspect
import sys

from sentinel.cli import (
    _shared, account, authority, automation, feed, paper, status,
)
from sentinel.config import (
    LiveEndpointRefused, MissingCredentials, SentinelConfig,
)


EXIT_CONFIG = _shared.EXIT_CONFIG
EXIT_NOT_ESTABLISHED = _shared.EXIT_NOT_ESTABLISHED
EXIT_OK = _shared.EXIT_OK
require_authorized_runtime = _shared.require_authorized_runtime
setup_logging = _shared.setup_logging


ROUTES = {
    "status": status.cmd_status,
    "shadow-status": status.cmd_shadow_status,
    "shadow-run": status.cmd_shadow_run,
    "feed-status": feed.cmd_feed_status,
    "feed-seed": feed.cmd_feed_seed,
    "feed-daily": feed.cmd_feed_daily,
    "migration-plan": account._migration_plan,
    "target-book": account.cmd_target_book,
    "compare-paper-warmup": paper.cmd_compare_paper_warmup,
    "create-paper-observation-candidate": (
        authority.cmd_create_paper_observation_candidate),
    "create-empty-paper-binding-candidate": (
        authority.cmd_create_empty_paper_binding_candidate),
    "check-data": feed.cmd_check_data,
    "rejection-audit": feed.cmd_rejection_audit,
    "feed-repair": feed.cmd_feed_repair,
    "identity": feed.cmd_identity,
    "plan": account._plan,
    "inspect-paper-account": paper._inspect_paper_account,
    "inspect-empty-paper-account": paper._inspect_empty_paper_account,
    "bind-empty-paper-account": paper._bind_empty_paper_account,
    "prepare-paper-plan": paper._prepare_paper_plan,
    "current-paper-plan": paper._current_paper_plan,
    "execute-paper-plan": paper._execute_paper_plan,
    "install-administrative-certificate": (
        authority._install_administrative_certificate),
    "activate-administrative-certificate": (
        authority._activate_administrative_certificate),
    "revoke-administrative-certificate": (
        authority._revoke_administrative_certificate),
    "install-system-certificate": authority._install_system_certificate,
    "activate-system-certificate": authority._activate_system_certificate,
    "rotate-system-certificate": authority._activate_system_certificate,
    "revoke-system-certificate": authority._revoke_system_certificate,
    "revoke-system-key": authority._revoke_system_key,
    "set-paper-rollout-mode": authority._set_paper_rollout_mode,
    "automation-status": automation._automation_status,
    "automation-health": automation._automation_status,
    "activate-paper-automation": automation._activate_paper_automation,
    "release-paper-automation-kill-switch": (
        automation._release_paper_automation_kill),
    "engage-paper-automation-kill-switch": (
        automation._remove_automation_authority),
    "deactivate-paper-automation": automation._remove_automation_authority,
    "acknowledge-paper-alert": automation._acknowledge_paper_alert,
    "automation-run": automation._automation_run,
    "migrate-account": account._migrate_account,
    "adopt-restored-account": account._adopt_restored,
    "establish-ownership": account._establish,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "status", help="print canonical binding and audit status; no broker")
    sub.add_parser(
        "shadow-status",
        help="verify and print broker-free shadow NAV/return; no broker")
    shadow_run = sub.add_parser(
        "shadow-run",
        help="dedicated broker-free reviewed shadow service")
    shadow_run.add_argument("--preflight", action="store_true")
    shadow_run.add_argument("--once", action="store_true")
    fs = sub.add_parser("feed-status", help="ingest progress, readable MID-RUN")
    fs.add_argument("--limit", type=int, default=5)
    sd = sub.add_parser("feed-seed", help="load the full Sharadar history (hours)")
    sd.add_argument("--from", dest="date_from", default=None)
    sd.add_argument("--to", dest="date_to", default=None)
    daily = sub.add_parser(
        "feed-daily", help="fetch since the stored frontier",
        description=(
            "Fetch and publish through one explicit fully closed "
            "XNYS session."),
        usage="sentinel feed-daily [-h] --through YYYY-MM-DD")
    daily.add_argument(
        "--through", action="append", metavar="YYYY-MM-DD",
        help="required closed XNYS session boundary")
    mp = sub.add_parser("migration-plan",
                        help="legacy broker book vs the Wealth Core target")
    mp.add_argument("--sessions", type=int, default=252)
    mp.add_argument("--deployment-id", required=True)
    mp.add_argument("--expect-account", required=True)
    bs = sub.add_parser("target-book",
                        help="warm up Wealth Core and print today's target")
    bs.add_argument("--cash", type=float, default=100_000.0)
    bs.add_argument("--sessions", type=int, default=252)
    compare_warmup = sub.add_parser(
        "compare-paper-warmup",
        help="compare retained current target/migration 252+1 warmups")
    compare_warmup.add_argument("--target-book", required=True)
    compare_warmup.add_argument("--migration-plan", required=True)
    candidate = sub.add_parser(
        "create-paper-observation-candidate",
        help="emit broker-free PAPER_OBSERVATION_ONLY claims/evidence")
    candidate.add_argument("--certificate-id", required=True)
    candidate.add_argument("--issuer-generation", type=int, required=True)
    candidate.add_argument("--deployment-id", required=True)
    candidate.add_argument("--expect-account", required=True)
    candidate.add_argument("--not-before", required=True)
    candidate.add_argument("--expires-at", default=None)
    candidate.add_argument("--maximum-exposure", required=True)
    candidate.add_argument("--cash", type=float, required=True)
    candidate.add_argument("--reviewer", required=True)
    candidate.add_argument("--ticket", required=True)
    empty_candidate = sub.add_parser(
        "create-empty-paper-binding-candidate",
        help="emit broker-free attended ADMIN_BIND_EMPTY claims/evidence")
    empty_candidate.add_argument("--certificate-id", required=True)
    empty_candidate.add_argument("--issuer-generation", type=int, required=True)
    empty_candidate.add_argument("--deployment-id", required=True)
    empty_candidate.add_argument("--expect-account", required=True)
    empty_candidate.add_argument("--not-before", required=True)
    empty_candidate.add_argument("--expires-at", default=None)
    empty_candidate.add_argument("--reviewer", required=True)
    empty_candidate.add_argument("--ticket", required=True)
    cd = sub.add_parser("check-data",
                        help="the Wealth Core data contract, per CHECK")
    cd.add_argument("--today", default=None)
    ra = sub.add_parser("rejection-audit",
                        help="could a REFUSED price row have changed this "
                             "interval's answer? exits non-zero unless CLEAR")
    ra.add_argument("--start", required=True)
    ra.add_argument("--end", required=True)
    ra.add_argument("--book", default=None,
                    help="JSON file with {\"held\": [...], "
                         "\"pending_terminal\": [...]} — the replay's own "
                         "state, which is where these should come from rather "
                         "than a human retyping a ticker list")
    ra.add_argument("--held", default=None,
                    help="comma-separated tickers the run held, which make an "
                         "intersecting rejection MATERIAL outright")
    ra.add_argument("--pending-terminal", default=None,
                    help="comma-separated tickers with a pending terminal "
                         "episode during the interval")
    ra.add_argument("--assert-no-holdings", action="store_true",
                    help="assert the book was EMPTY over this interval (true "
                         "before the first bootstrap). Explicit on purpose: "
                         "supplying nothing means UNKNOWN, not empty, and "
                         "every ticker then reads UNDETERMINED")
    rp = sub.add_parser("feed-repair",
                        help="find (and optionally fix) stored split ratios "
                             "that CONTRADICT the ACTIONS feed")
    rp.add_argument("--start", required=True)
    rp.add_argument("--end", required=True)
    rp.add_argument("--apply", action="store_true",
                    help="actually rewrite the ratios. DRY BY DEFAULT: this "
                         "command changes SHARE COUNTS, and the one operation "
                         "in the package permitted to LOWER a split ratio "
                         "should not be the convenient one")
    idp = sub.add_parser("identity",
                         help="what this environment and corpus ARE — the "
                              "record a certified run is reproducible from")
    idp.add_argument("--start", default=None,
                     help="hash the corpus over this window (with --end)")
    idp.add_argument("--end", default=None)
    idp.add_argument("--require-certified", action="store_true",
                     help="exit non-zero unless both the environment and "
                          "installed deployment identity are certified")
    idp.add_argument(
        "--require-environment-compatible", action="store_true",
        help="build/rehearsal-only gate: require the reviewed interpreter, "
             "dependencies and sources without claiming deployment binding")
    sub.add_parser("plan", help="retired; refuses and names safe replacements")
    inspect = sub.add_parser(
        "inspect-paper-account",
        help="read the exact named paper account and inherited open book")
    inspect.add_argument("--deployment-id", required=True)
    inspect.add_argument("--expect-account", required=True)
    empty_inspect = sub.add_parser(
        "inspect-empty-paper-account",
        help="read the exact pre-binding paper account; no mutation methods")
    empty_inspect.add_argument("--deployment-id", required=True)
    empty_inspect.add_argument("--expect-account", required=True)
    empty_bind = sub.add_parser(
        "bind-empty-paper-account",
        help="one-time ADMIN_BIND_EMPTY stable-flat enrollment")
    empty_bind.add_argument("--deployment-id", required=True)
    empty_bind.add_argument("--expect-account", required=True)
    empty_bind.add_argument("--notes", default=None)
    prep = sub.add_parser(
        "prepare-paper-plan",
        help="advance state and adopt one durable current paper plan; dry run")
    prep.add_argument("--through", required=True)
    prep.add_argument("--warmup-sessions", type=int, default=252)
    prep.add_argument("--expect-account", required=True)
    prep.add_argument(
        "--reviewed-informational-dual", action="store_true",
        help="size only from the exact reviewed shadow state; no broker mutation")
    sub.add_parser(
        "current-paper-plan",
        help="inspect the durable current paper plan; contacts no broker")
    execute = sub.add_parser(
        "execute-paper-plan",
        help="submit only the confirmed durable current plan to Alpaca paper")
    execute.add_argument("--confirm-paper-account", required=True)
    execute.add_argument("--confirm-plan-id", required=True)
    execute.add_argument("--confirm-effective-session", required=True)
    execute.add_argument(
        "--confirm-submit-paper-orders", action="store_true", required=True)
    install_admin = sub.add_parser(
        "install-administrative-certificate",
        help="stage offline-signed inherited-account authority; no broker")
    install_admin.add_argument("--certificate", required=True)
    install_admin.add_argument("--confirm-certificate-sha256", required=True)
    install_admin.add_argument("--deployment-id", required=True)
    install_admin.add_argument("--expect-account", required=True)
    install_admin.add_argument("--takeover-epoch", type=int, required=True)
    install_admin.add_argument("--reason", required=True)
    install_admin.add_argument(
        "--confirm-install-administrative-certificate",
        action="store_true", required=True)
    activate_admin = sub.add_parser(
        "activate-administrative-certificate",
        help="activate exact staged inherited-account authority; no broker")
    activate_admin.add_argument("--certificate-sha256", required=True)
    activate_admin.add_argument("--deployment-id", required=True)
    activate_admin.add_argument("--expect-account", required=True)
    activate_admin.add_argument("--takeover-epoch", type=int, required=True)
    activate_admin.add_argument(
        "--confirm-supersedes-certificate-sha256", default=None)
    activate_admin.add_argument("--reason", required=True)
    activate_admin.add_argument(
        "--confirm-activate-administrative-certificate",
        action="store_true", required=True)
    revoke_admin = sub.add_parser(
        "revoke-administrative-certificate",
        help="revoke active inherited-account authority; no broker")
    revoke_admin.add_argument("--certificate-sha256", required=True)
    revoke_admin.add_argument("--reason", required=True)
    revoke_admin.add_argument(
        "--confirm-revoke-administrative-certificate",
        action="store_true", required=True)
    install_cert = sub.add_parser(
        "install-system-certificate",
        help="verify and stage one offline-signed paper certificate; no broker")
    install_cert.add_argument("--certificate", required=True)
    install_cert.add_argument("--confirm-certificate-sha256", required=True)
    install_cert.add_argument("--reason", required=True)
    install_cert.add_argument(
        "--confirm-install-alpaca-paper-execution-certificate",
        action="store_true", required=True)
    activate_cert = sub.add_parser(
        "activate-system-certificate",
        help="activate or rotate to one staged paper certificate; no broker")
    activate_cert.add_argument("--certificate-sha256", required=True)
    activate_cert.add_argument("--confirm-paper-account", required=True)
    activate_cert.add_argument("--confirm-deployment-id", required=True)
    activate_cert.add_argument("--reason", required=True)
    activate_cert.add_argument(
        "--confirm-activate-alpaca-paper-execution-certificate",
        action="store_true", required=True)
    activate_cert.add_argument(
        "--confirm-controller-rollout", action="store_true")
    activate_cert.add_argument(
        "--confirm-pinned-rollout-may-increase-exposure",
        action="store_true")
    rotate_cert = sub.add_parser(
        "rotate-system-certificate",
        help="rotate from the exact active certificate to one staged replacement")
    rotate_cert.add_argument("--certificate-sha256", required=True)
    rotate_cert.add_argument(
        "--confirm-supersedes-certificate-sha256", required=True)
    rotate_cert.add_argument("--confirm-paper-account", required=True)
    rotate_cert.add_argument("--confirm-deployment-id", required=True)
    rotate_cert.add_argument("--reason", required=True)
    rotate_cert.add_argument(
        "--confirm-rotate-alpaca-paper-execution-certificate",
        action="store_true", required=True)
    rotate_cert.add_argument(
        "--confirm-controller-rollout", action="store_true")
    rotate_cert.add_argument(
        "--confirm-pinned-rollout-may-increase-exposure",
        action="store_true")
    revoke_cert = sub.add_parser(
        "revoke-system-certificate",
        help="revoke the exact active execution certificate; no broker")
    revoke_cert.add_argument("--certificate-sha256", required=True)
    revoke_cert.add_argument("--reason", required=True)
    revoke_cert.add_argument(
        "--confirm-revoke-system-certificate",
        action="store_true", required=True)
    revoke_key = sub.add_parser(
        "revoke-system-key",
        help="durably revoke one installed Ed25519 key; no broker")
    revoke_key.add_argument("--key-id", required=True)
    revoke_key.add_argument("--reason", required=True)
    revoke_key.add_argument(
        "--confirm-revoke-system-key", action="store_true", required=True)
    rollout = sub.add_parser(
        "set-paper-rollout-mode",
        help="change exposure mode explicitly; PINNED_1_00 may increase risk",
        description=(
            "Change the durable paper rollout mode without broker contact. "
            "PINNED_1_00 forces 100% Wealth Core exposure and may increase "
            "exposure and risk from the current controller allocation."))
    rollout.add_argument(
        "--mode", required=True,
        choices=("PINNED_1_00", "CONTROLLER"))
    rollout.add_argument("--reason", required=True)
    rollout.add_argument(
        "--confirm-controller-rollout", action="store_true",
        help="confirm the separately authorized controller transition")
    rollout.add_argument(
        "--confirm-pinned-rollout-may-increase-exposure",
        action="store_true",
        help=(
            "acknowledge that forcing 100%% Wealth Core exposure may "
            "increase risk"))
    sub.add_parser(
        "automation-status",
        help="show durable automation/cycle/lease/alert state; no broker")
    sub.add_parser(
        "automation-health",
        help="SELECT-only supervisor health; disabled/killed is healthy")
    activate_automation = sub.add_parser(
        "activate-paper-automation",
        help="bind unattended paper authority; leaves kill switch engaged")
    activate_automation.add_argument("--confirm-paper-account", required=True)
    activate_automation.add_argument("--confirm-deployment-id", required=True)
    activate_automation.add_argument(
        "--confirm-certificate-sha256", required=True)
    activate_automation.add_argument(
        "--confirm-old-writer-fenced", action="store_true", required=True)
    activate_automation.add_argument("--actor", required=True)
    activate_automation.add_argument("--reason", required=True)
    activate_automation.add_argument(
        "--confirm-enable-unattended-alpaca-paper-automation",
        action="store_true", required=True)
    release_automation = sub.add_parser(
        "release-paper-automation-kill-switch",
        help="separately release the enabled paper automation kill switch")
    release_automation.add_argument("--confirm-paper-account", required=True)
    release_automation.add_argument("--confirm-deployment-id", required=True)
    release_automation.add_argument(
        "--confirm-certificate-sha256", required=True)
    release_automation.add_argument("--actor", required=True)
    release_automation.add_argument("--reason", required=True)
    release_automation.add_argument(
        "--confirm-release-unattended-paper-kill-switch",
        action="store_true", required=True)
    kill_automation = sub.add_parser(
        "engage-paper-automation-kill-switch",
        help="fence automation immediately; never cancels or liquidates")
    kill_automation.add_argument("--actor", required=True)
    kill_automation.add_argument("--reason", required=True)
    deactivate_automation = sub.add_parser(
        "deactivate-paper-automation",
        help="disable/fence automation without broker contact")
    deactivate_automation.add_argument("--actor", required=True)
    deactivate_automation.add_argument("--reason", required=True)
    ack_alert = sub.add_parser(
        "acknowledge-paper-alert",
        help="durably acknowledge one automation alert")
    ack_alert.add_argument("--alert-id", required=True)
    ack_alert.add_argument("--actor", required=True)
    ack_alert.add_argument("--acknowledgement", required=True)
    sub.add_parser(
        "automation-run",
        help="persistent Stage 4 scheduler; inert until enabled and unkilled")
    mig = sub.add_parser("migrate-account",
                         help="ONE-TIME administrative handover: remove the "
                              "legacy book and BIND this account")
    mig.add_argument("--deployment-id", required=True,
                     help="stable identity for this appliance; it is hashed "
                          "into every command key, so changing it later "
                          "orphans in-flight commands")
    mig.add_argument("--expect-account", required=True,
                     help="refuse unless the broker reports this account id")
    mig.add_argument("--notes", default=None)
    mig.add_argument("--max-cycles", type=int, default=None)
    mig.add_argument("--poll-seconds", type=float, default=None)
    ado = sub.add_parser("adopt-restored-account",
                         help="increment the takeover epoch on a REPLACEMENT "
                              "host (revoke the old credentials FIRST)")
    ado.add_argument("--confirm-old-credentials-revoked", action="store_true")
    ado.add_argument("--confirm-paper-account", default=None)
    ado.add_argument("--notes", default=None)
    est = sub.add_parser("establish-ownership",
                         help="RETIRED — use migrate-account")
    est.add_argument("--max-cycles", type=int, default=None)
    est.add_argument("--poll-seconds", type=float, default=None)


    return parser


def _run_handler(handler, config: SentinelConfig | None, args) -> int:
    result = handler(config, args)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "feed-daily":
        boundary_refusal = feed.prepare_feed_daily(args)
        if boundary_refusal is not None:
            return boundary_refusal

    setup_logging(args.verbose)

    if args.command == "shadow-run":
        return _run_handler(ROUTES[args.command], None, args)

    surface_refusal = require_authorized_runtime(args.command)
    if surface_refusal is not None:
        return surface_refusal

    try:
        config = SentinelConfig.from_env()
    except (LiveEndpointRefused, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.command in ("establish-ownership", "migrate-account"):
        if args.max_cycles is not None:
            config = replace(config, max_cycles=args.max_cycles)
        if args.poll_seconds is not None:
            config = replace(config, poll_seconds=args.poll_seconds)

    try:
        return _run_handler(ROUTES[args.command], config, args)
    except (LiveEndpointRefused, MissingCredentials) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_CONFIG
