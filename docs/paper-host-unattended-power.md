# Windows host availability for unattended PAPER

The October 26 investigation found a Windows Modern Standby entry at 15:30:55
Pacific following a lid wake at 15:29:17. The active Balanced scheme already
disabled ordinary AC sleep and AC hibernation and selected no action on AC lid
close. Its separate hidden unattended sleep timeout remained 120 seconds on AC.
Database-wide simultaneous statement timeouts and leadership interruptions were
also observed. The power event establishes a host-availability risk; it does not
prove that every later database timeout was caused by sleep.

For this dedicated laptop while connected to mains power, disable only the AC
unattended sleep timeout in the current scheme. Record the original scheme and
setting, apply the supported powercfg setting, reactivate the same scheme, and
read back the actual AC/DC values. Preserve battery sleep, battery lid action,
critical-battery protection, screen timeout and all trading controls. Rollback
restores the recorded AC value. No reboot, WSL/Docker restart or application
restart is part of this operation.

Do not treat the setting change as trading qualification. Verify actual
leadership continuity, current source and book, reconciliation, the next-open
plan and installed application health independently. Explicit user sleep, loss
of power, host updates and other system stalls can still interrupt services.

## Bounded verification-reader pause during owned recovery

Severe host paging persisted after the power setting change. A broker-free
foreground publisher is already repairing the latched incident, while the old
background verifier independently repeats expensive reads of the retained
history. During this inspected recovery only, pause the exact predecessor
verifier to reduce competing work. Preserve its container/image and every
database/control fact; this is a normal stop of a read-only application role.

Record the inspected identity, stop time and reason outside the qualified
checkout. Register a bounded 20-minute automatic restart before stopping it.
Resume it sooner once the foreground recovery exits, including failure. The
foreground publisher must still earn its complete current-source/book proof;
the pause grants no financial verification, authority or green status. All six
healthy roles remain required before application handoff and final readiness.
