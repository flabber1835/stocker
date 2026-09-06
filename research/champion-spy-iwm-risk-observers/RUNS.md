# SPY / IWM experiment run ledger

RESEARCH / NOT CERTIFIED. No economic result is promoted by this ledger.

| Purpose | Run | Exact source | Scope |
|---|---|---|---|
| Observer data freeze | https://github.com/flabber1835/stocker/actions/runs/34011985844 | 3b138b63b2e24616f883cf4ae7f594e082f3e327 | Completed successfully; SPY/IWM retained SFP and official VIX input package |
| Fresh full 20-year replay | https://github.com/flabber1835/stocker/actions/runs/34012654549/job/101431000914 | 465e3ae20f6730d4dd31b96548a7232ee8f3c278 | Accepted full20 execution; 81 variants plus Champion and Native controls |
| Independent 5-year replay | https://github.com/flabber1835/stocker/actions/runs/34012815223 | efe05b3c55f90e87e74d7fecd65635c907784d1d | Accepted fresh5 execution, with pre-warmup lifecycle reconstruction |
| Superseded preliminary fresh5 | https://github.com/flabber1835/stocker/actions/runs/34012654549/job/101431000798 | 465e3ae20f6730d4dd31b96548a7232ee8f3c278 | Diagnostic only; omits pre-warmup retirement-state reconstruction |

Runtime for both accepted runs: 887f479b15ad861313da666ad698034d3847121c. Both consume the same canonical and external observer package identities. The full20 source remains untouched by the fresh-only lifecycle refinement.

The two initial matrix jobs passed all targeted baseline tests, the 27 observer tests and full source assembly. The four additional lifecycle tests passed locally; the dedicated fresh5 workflow rechecks all 31 observer/lifecycle tests with the frozen runtime before its economic replay.

Completed-run status, final metrics, reference parity and final artifact hashes must be read from the actual runner artifacts. Pending tasks include comparison of fixed central points and complete parameter distributions, identical-window fresh5-versus-trailing5 attribution, episode-level tradeoffs, graphs and additional rolling independent launch robustness. No best-performing point has been selected.

## Artifact locations

Data freeze artifact: champion-spy-iwm-observer-data-34011985844-1, ID 9982753298, ZIP SHA256 f1d2333b0326345f1e86e791f546001a8a23b34a2436aa70c3eb55b9085af51d.

Expected economic artifact names (availability requires successful upload):
- champion-spy-iwm-observers-34012654549-1-full20
- champion-spy-iwm-fresh-launch-34012815223-1

The lifecycle helper and its tests change only independent-launch eligibility-state initialization. A fresh portfolio still requires historical security lifecycle knowledge; it must not inherit earlier portfolio decisions.
