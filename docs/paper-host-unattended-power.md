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
