# Backup verification renewal headroom

The November 11 opening rehearsal observed nine successful native backup proof
renewals. The tightest published 7.16 seconds before the previous byte proof
expired. The elapsed pass was 141.60 seconds. The backed PAPER patch starts the
existing full verification 180 seconds before expiry, up from 150 seconds.
With the same pass timing and scheduling delay, that leaves 37.16 seconds.

Use the same threshold in the host scheduler and maintenance proof owner. A
single threshold applies across the day and avoids a second exchange calendar
in the host maintenance path. It starts byte verification 30 seconds earlier
per receipt and may increase verification I/O. The original primary clock,
300-second byte lifetime, 600-second dashboard evidence lifetime, serial proof
ownership, two byte passes and existing restore checks remain the same.
An ordinary reader can still use the authenticated current receipt during a
renewal. A failed or expired receipt still refuses admission.

Qualify the host due time against the actual primary proof clock and exercise
both byte passes at the new boundary against private PostgreSQL. Exercise
ordinary proof reuse, retry and expiry, and show that the former threshold fails
the updated qualification. Apply the backed local PAPER handoff from the exact
installed `a81a9e406` predecessor. A changed implementation must establish a
fresh proof under the existing owner. Verify the saved opening plan, then
observe a scheduled native renewal and its margin. Rebind the armed opening
trace to the installed image and use the same renewal lead for its timing.
