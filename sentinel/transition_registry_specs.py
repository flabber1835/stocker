"""Immutable historical transition witnesses; no authority or successor inference."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileSpec:
    key: str
    checker: str
    filename: str
    sha256: str
    checker_sha256: str
    keys: frozenset[str]


PROFILES = (
    ProfileSpec('legacy_economic', 'economic_migration', 'forward-cash-migration.json',
        'c241c1c6ea7dc302c783469fbf4f0d7684ab25c52851d49f1c00544f898c2f01', '5f8630d4c6991e357bd6725aad6f800287871b5079f68866698beacc943d573e',
        frozenset(('additions', 'files', 'schema'))),
    ProfileSpec('economic', 'economic_migration', 'forward-cash-migration-v2.json',
        '5d7bd8183d1cf479f144ac711c40704eb33dbe2d160e0b84dba5097af9036520', '5f8630d4c6991e357bd6725aad6f800287871b5079f68866698beacc943d573e',
        frozenset(('additions', 'files', 'from_policies', 'schema', 'to_policy'))),
    ProfileSpec('execution', 'execution_upgrade', 'paper-composition-upgrade.json',
        'bf41ee4968143f9cb42e844b1854dc7f3dd840ecfb674135e447b1b458e731a2', '9e65d218356e49ecc185e918c537b6182ba26641bba20f3345cfac086701494a',
        frozenset(('files', 'module_sha256', 'schema'))),
    ProfileSpec('readiness', 'retained_readiness_upgrade', 'retained-readiness-upgrade.json',
        'c190835a70e44aace35bd1bb3e8cf619c1bf55ce9d9f966f88a931efcf1a66e0', '44938aef8030a216c5e867486a1f125dbb4792cb86069962296d152ac6658eb7',
        frozenset(('files', 'module_sha256', 'schema'))),
    ProfileSpec('renewal', 'dual_plan_renewal_upgrade', 'dual-plan-renewal-upgrade.json',
        '6d8ba8f4b362cb39b100ab94fa8dfba2c4e8f6cd16232a3bc9fd6d8826d574d4', '70de1efda4b68ea42c3750d24d0330314f5ea00aac6a1ff15bc79499183c3ca9',
        frozenset(('files', 'module_sha256', 'schema'))),
    ProfileSpec('liveness', 'operational_liveness_upgrade', 'operational-liveness-upgrade.json',
        '3fd11d20e942a9eaf2c00684b7d6d1444cc1e91cf9528f9106e131e5bd15fb4b', '6c8fb8ba99d67c55c8571580606cc100c16b8276246016d13bece098b3824d45',
        frozenset(('files', 'module_sha256', 'schema'))),
    ProfileSpec('operational', 'operational_runtime_upgrade', 'operational-runtime-upgrade.json',
        '86d02b45ce868506668cb0e7cd330c047651f371f433926f7c2d8eb498e0f618', '26a1b3cc6c6816e954f1ea6be053d845a3a7fadd42275130d4bdf64a215bca48',
        frozenset(('additions', 'files', 'module_sha256', 'schema'))),
    ProfileSpec('callback', 'callback_liveness_upgrade', 'callback-liveness-upgrade.json',
        'b7f8f033a61aa06eb24fcbf0cecca000d892830e20dd619a354e780cc6741fc0', '2a68a45b3cf9a4b0ea0e727de23899f49d608b97b4f119b207d1ca765ae2b1f1',
        frozenset(('files', 'module_sha256', 'schema'))),
    ProfileSpec('startup', 'startup_contention_upgrade', 'startup-contention-upgrade.json',
        'a1131aa56c53dfeda652b798e8ec1042b58f8abe13819e02d0c9de84ce9f0920', 'fac86d07c3628146e13873910bbdf68e8c09f3ca981bc74fad738e3052d847c8',
        frozenset(('files', 'module_sha256', 'schema'))),
    ProfileSpec('recovery', 'unsent_recovery_upgrade', 'unsent-recovery-upgrade.json',
        '2d59b3e68df1368f0f8f8ca4644f5f1a8334867fdbb0893ae216a7035faf1672', '6fd45eb7cebb7ed47abed560a6420178443b861c6115cfd179ad1dcfc5651b9e',
        frozenset(('additions', 'files', 'module_sha256', 'schema'))),
    ProfileSpec('ui', 'shadow_ui_upgrade', 'shadow-ui-upgrade.json',
        '1f3fe126b1cdffdf1e18eb88945d63be4b8bbe21de8bd86aa1c050919b59aa10', 'e6f59359b6ec5ae1d5d9fc4125eb174122c1336a0b08c4f0827b9fe9bc368b9a',
        frozenset(('additions', 'files', 'module_sha256', 'schema'))),
    ProfileSpec('monitor', 'dashboard_monitor_upgrade', 'dashboard-monitor-upgrade.json',
        '1f9929e8ae0c9b739c28dd9115eeaf9a6c69c8ce4036d3b0382a7d6898ecbc69', 'c4f97b1ae7a657e89d8ac3a54fde85cce2a2898715fc1401875cccec56c031da',
        frozenset(('additions', 'files', 'module_sha256', 'schema'))),
    ProfileSpec('open_time', 'open_time_upgrade', 'open-time-upgrade.json',
        '282a161b42c8966ff6c6a75094d5085a3e9c6a42b11163fe6c3ffc8baf297b3d', '806f51e51e1d0bb0bb7c56799ef8608e8bf54cf4b9548e2ca76fe23c8ed4b843',
        frozenset(('additions', 'files', 'module_sha256', 'schema'))),
    ProfileSpec('close_cycle', 'close_cycle_upgrade', 'close-cycle-upgrade.json',
        '644d297796a7bb277d83c2e5936e29e21f3f5aeffdebd4e3cf0608d94302e3be', '486027dafeba53fd14ae734e3d48fb5dbc5800ff350dc6ab87ffeebc61ea35d4',
        frozenset(('additions', 'files', 'module_sha256', 'schema'))),
    ProfileSpec('autonomy', 'autonomy_runtime_upgrade', 'autonomy-runtime-upgrade.json',
        '09c9f7738ec5849284f239a07385af15faacb2c434b1d5e6ead31003622a9da9', '9a25f82d6e9f73f699be5773cdd2982f9f5e9032d23eb00dee4ae5b8907a691f',
        frozenset(('additions', 'admission_sha256', 'files', 'module_sha256', 'schema'))),
    ProfileSpec('native_read', 'native_read_upgrade', 'native-read-runtime-upgrade.json',
        '200f95d633527d829504ea77ce40994c8c06567303f0b1e4af2178bfd1b3591b', '6dfae675ef72e28f765c1d33a3702899bd86b6c45833a4daded73216a772c4e7',
        frozenset(('additions', 'admission_predecessor_witnesses', 'authority_effect', 'autonomy_checker_normalized_sha256', 'files', 'module_sha256', 'original_admission_sha256', 'original_checker_normalized_sha256', 'original_checker_sha256', 'original_profile_sha256', 'schema'))),
    ProfileSpec('clock_sampling', 'clock_sampling_upgrade', 'clock-sampling-runtime-upgrade.json',
        '885ce3556ee3eae0aab3a02af313dc20ecc5e28ceff9fffe0d1c96192b809372', '2aedd9e6e8dcbfa11baa02c9f26e5a215a6f60ecf211f9cb15be9109cde0afdb',
        frozenset(('additions', 'authority_effect', 'autonomy_checker_normalized_sha256', 'files', 'module_sha256', 'native_checker_sha256', 'retained_profiles', 'schema'))),
    ProfileSpec('idle_leader', 'idle_leader_upgrade', 'idle-leader-runtime-upgrade.json',
        'c037285eda8aba76adcf6be1fa8bbe97d5bc0f36a49123dcdce7fd8017dd9acb', '62c75da24a6861bfb570b98bad7e951acca0e790bb8752db3db88703b5db1685',
        frozenset(('additions', 'authority_effect', 'base_revision', 'clock_checker_normalized_sha256', 'files', 'module_sha256', 'retained_profiles', 'schema'))),
    ProfileSpec('opening_latency', 'opening_latency_upgrade', 'opening-latency-runtime-upgrade.json',
        'c15470418da30f2b842481eb605305f750d17cbaec94d72796aa00f44849f73d', '1fc0319a95d18d39fce23626e28f9861a77f93e3be3c6bb588d6cb4d8b11138f',
        frozenset(('additions', 'authority_effect', 'base_revision', 'files', 'idle_checker_normalized_sha256', 'module_sha256', 'predecessor_witnesses', 'retained_profiles', 'schema'))),
    ProfileSpec('protected_cohort', 'protected_cohort_upgrade', 'protected-cohort-runtime-upgrade.json',
        '02fc951631085a411ee3c7f4d8def27d08a97d23d7f2dacecc575343c83188ec', 'cef5b24fe29a64a7d7a86f16602639fbd59c46d95dd6be8fa2c0bbadd54b7dff',
        frozenset(('additions', 'authority_effect', 'base_revision', 'files', 'module_sha256', 'opening_checker_normalized_sha256', 'predecessor_witnesses', 'retained_profiles', 'schema'))),
)
