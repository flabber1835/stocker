"""Exact broker/trial namespaces that are never immutable strategy inputs.

Unknown namespaces remain economic inputs. Classification changes neither
execution authority nor the independent broker and trial evidence guards.
"""

PAPER_CURSOR_PREFIXES = (
    'informational-paper-mirror:v1:', 'broker-observation:v4:',
    'terminal-recovery-witness:v3:', 'broker-cash-activity:v1:',
    'broker-cash-plan:v1:', 'preopen-share-unit-authority:v1:',
    'plan-target-projection:v2:', 'dual-regenesis-broker-handover:v2:',
    'trial-account:v2:', 'trial-verification:v3:', 'trial-fill-interval:v1:',
    'trial-close-nav:v1:', 'paper-performance-invalid:v1:',
    'protected-buy-funding:v1:',
    'issuer-admission-enrollment:v1:', 'issuer-reference-snapshot:v1:',
    'issuer-plan-admission:v1:', 'issuer-episode-claim:v1:',
    'issuer-entry-shortfall:v1:',
)
PAPER_CURSOR_NAMES = ('broker-recovery-db-incarnation:v1',)
