# Wealth Core V1 cleaned-position audit

## Purpose

Read-only audit of the frozen `virtual-slot-free-cash` Wealth Core experiment from Actions run `34259200904` / source commit `23c47f32c8f2174c7fb51b24a825d112fcf323d9`.

The audit adds observability only. It MUST reproduce the completed free-cash experiment's economic outputs byte-for-byte:

- generated free-cash source SHA-256 before audit instrumentation: `740d353a223ab63112d5fb9c6eed1e6d7f8e69b1a6d2f46b83773df8f49daba6`
- `daily.csv` SHA-256: `bf1ecdc2917de2122904be2bb94b246d06e2a6927ad262a843333ee9d91823d1`
- `summary.json` SHA-256: `753943497976027746b130d3afbe8365765800ab15d7284f993c3319bcbc984a`

Any mismatch fails the audit.

## Required evidence

For every real Wealth Core holding episode, emit slot index, security ID/ticker, entry and exit dates, entry execution quantity/price/value/weight, minimum and maximum marked dollar value and portfolio weight while held, final marked value/weight, and exit reason. Also preserve raw daily position snapshots and real trade/terminal events.

## Micro-position assertions

The cleaned experiment's frozen rule remains: a real entry must not execute below 1% of intended entry capital. The audit must confirm `real_micro_executions == 0` and report the minimum real entry funding fraction.

A real position may later fall below 1% of portfolio value because its price falls. That is reported as observed path behavior and is not conflated with the prohibited microscopic-entry defect.

## Scope

Pure Wealth Core only. Sentinel metrics and allocations are not used for the audit result.