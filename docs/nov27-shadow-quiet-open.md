# SHADOW maintenance during market open

On November 27 the broker-free worker ran full verification at 06:33 Pacific while execution was submitting orders. It had just verified the same published session before the bell. The supervisor scheduled the work because its ordinary ten-minute interval elapsed.

The supervisor can postpone this periodic work until the end of the first ten minutes of an XNYS session. Only a successful full worker that observed the same authenticated publication before and after its run and wrote a new passing readiness row can earn this scheduling privilege. The ordinary proof still expires on its original clocks. At expiry the supervisor must independently reobserve the signed health projection, published storage identities and exact readiness row before waiting again. During the reservation it repeats that observation at most 30 seconds apart. A missing, changed, unhealthy or unobservable subject, a clock reversal, or the next acquisition deadline immediately returns control to the full worker. The supervisor keeps servicing its heartbeat. Optional retention can resume with the worker after the reservation.

The exchange calendar and the authenticated projection's causal health deadline bound the reservation. Both UTC and monotonic time limit each wait. Startup, an incomplete publication, and a failed worker have no earned reservation. The scheduler writes no readiness evidence and never extends the lifetime of any health or financial proof. Shadow scheduling has no dependency on broker or account state.

## Private qualification

The deterministic November 27 replay starts the worker at 06:23:32 Pacific. Its ordinary proof expires at 06:33:32. With unchanged evidence the next full worker becomes due at 06:40. The same replay returns to full work at the first changed or unavailable observation, or at the earlier health or acquisition deadline. A restart and Thanksgiving retain their ordinary wake times.

The private PostgreSQL fixture passed all 80 cases in `tests/sentinel/test_shadow_health_projection.py` and `tests/sentinel/test_close_scheduling_root_causes.py`. The final focused rerun passed all 13 original-deadline and opening cases. Removing the reservation in memory reproduced the 06:33:32 wake and failed the unchanged-case test. Bypassing the exact evidence comparison made the changed and missing evidence tests fail. The replay exercises scheduling with a simulated clock. Its result does not measure broker latency.
