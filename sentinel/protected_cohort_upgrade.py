"""Exact protected-cohort execution/monitoring successor; no financial authority."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '1b3ee2862a68aff0b426e1127a916eb8f9a0ad5bda3135b06710ca5c73c281c2'
PROFILE = Path(__file__).with_name('protected-cohort-runtime-upgrade.json')
BASE_REVISION = '52b2bd7be846023f924122865a2b16ea1983041d'
BASE_FILES = {'alert_service.py': '668f3e36fb2196c11bb40c777e2c6330ed993509b2491b8d8af613593c5d68be', 'automation/health.py': 'd9258c571a803aaf2b61219d16b2976d8d02d67dc401bd68e4d044aed20d4bb7', 'automation/model.py': 'dc3157a02e996be34c9b76b818a6787811d404b5e953d41af8c9522b60ad4430', 'automation/service.py': 'a50bf6c3f87fef76035540c20635441802c3cff98af1b5738e3ce2da6ba5b36c', 'automation_runtime.py': '18324b00f88b82664aeb6049edbc6ca711b0c608687078468e2f6898337c7ff8', 'cli/paper.py': '2f4c143adda925b4afeac860b59b3dbaabc2bbc50a8c5a1d2d0d86c734d4e675', 'core/rolling_inputs.py': '2195344583fdf3753bf5a0809dfed699a55f7055e531e80fb6a613dd930c89a2', 'execution/executor.py': 'c84580e4a5d2992216f93c2b4178b05fd568706ed0c8beeb0309dbf6f5e1572e', 'execution/protected_funding.py': '87b8d4b3146db5b41b5a010872f22d96ecedbc3bbaaa4180b709c9223676f2bc', 'feed/_publication_impl.py': '79c5c7e12b314c0bc795a3d071d97664df16ef5f2b98b57bf6eb525071fcb2c9', 'feed/readers.py': 'c1fa3937bfc60b36f61f92558dfa1d408e00247397467636392fbb5a48e1b0c2', 'feed/readiness_scope.py': '99978175164320decfd893b0f1d8d28d98d0ce7c591a85a48222da03d6e9a2a2', 'feed/rolling_go_health.py': 'dd8de011ff06eb756012ad9e70208827f05dd8b509f7e2a7304f15c9e9d7d680', 'feed/rolling_schema.py': 'ed86f692a0bce7b0e942661cb51d4a0debb55ac281d32fe711d52324feeb3ae0', 'feed/rolling_store.py': '3e12084449e525b10fa4c645f904ac2706d41fd2fc60461db38a0a77dcac85bb', 'feed/runtime_schema.py': '2798474440848ce63824ba20eb30123a5ca97fc0fbeb461ef2fca00a60b39d18', 'identity.py': '92a2933e4f9c43deee239f7ba16d4897e629e3d7e0c256712f5ff90412b894f7', 'opening_latency_upgrade.py': 'f54d24b1e7199b6c0f454da52dbc8d5dddac4f6205926cff4c80c807e1819612', 'panel/model.py': 'd5fb0b67299b71d85ba5a204060945104dc52fb1eee666227d1d80a11d1ec931', 'panel/sources.py': '8cf8b522719cb1f1925309240f7d6b21fd157588971dd55f2c748988bb067b10', 'paper/execution.py': '8f4812e10708ad704b9e4094e3325a93ea671699a41e166ed6e7659b1f25cc83', 'paper/recovery.py': '99d57d5f932661da7f5fd61a23c561a8a91e4ac5eb1b3d0abd3284400a646939', 'runtime_admission.py': '4ffe676cc4fdc6c1515f7862c4cf70b38b22d92d52f23d569c55eb03726ff12e'}
RETAINED_PROFILES = {'autonomy-runtime-upgrade.json': '09c9f7738ec5849284f239a07385af15faacb2c434b1d5e6ead31003622a9da9', 'callback-liveness-upgrade.json': 'b7f8f033a61aa06eb24fcbf0cecca000d892830e20dd619a354e780cc6741fc0', 'clock-sampling-runtime-upgrade.json': '885ce3556ee3eae0aab3a02af313dc20ecc5e28ceff9fffe0d1c96192b809372', 'close-cycle-upgrade.json': '644d297796a7bb277d83c2e5936e29e21f3f5aeffdebd4e3cf0608d94302e3be', 'dashboard-monitor-upgrade.json': '1f9929e8ae0c9b739c28dd9115eeaf9a6c69c8ce4036d3b0382a7d6898ecbc69', 'dual-plan-renewal-upgrade.json': '6d8ba8f4b362cb39b100ab94fa8dfba2c4e8f6cd16232a3bc9fd6d8826d574d4', 'idle-leader-runtime-upgrade.json': 'c037285eda8aba76adcf6be1fa8bbe97d5bc0f36a49123dcdce7fd8017dd9acb', 'native-read-runtime-upgrade.json': '200f95d633527d829504ea77ce40994c8c06567303f0b1e4af2178bfd1b3591b', 'open-time-upgrade.json': '282a161b42c8966ff6c6a75094d5085a3e9c6a42b11163fe6c3ffc8baf297b3d', 'operational-liveness-upgrade.json': '3fd11d20e942a9eaf2c00684b7d6d1444cc1e91cf9528f9106e131e5bd15fb4b', 'operational-runtime-upgrade.json': '86d02b45ce868506668cb0e7cd330c047651f371f433926f7c2d8eb498e0f618', 'paper-composition-upgrade.json': 'bf41ee4968143f9cb42e844b1854dc7f3dd840ecfb674135e447b1b458e731a2', 'retained-readiness-upgrade.json': 'c190835a70e44aace35bd1bb3e8cf619c1bf55ce9d9f966f88a931efcf1a66e0', 'shadow-ui-upgrade.json': '1f3fe126b1cdffdf1e18eb88945d63be4b8bbe21de8bd86aa1c050919b59aa10', 'startup-contention-upgrade.json': 'a1131aa56c53dfeda652b798e8ec1042b58f8abe13819e02d0c9de84ce9f0920', 'unsent-recovery-upgrade.json': '2d59b3e68df1368f0f8f8ca4644f5f1a8334867fdbb0893ae216a7035faf1672', 'opening-latency-runtime-upgrade.json': 'c15470418da30f2b842481eb605305f750d17cbaec94d72796aa00f44849f73d'}
OPENING_CHECKER_NORMALIZED_SHA256 = '3e7739a8f1580db9eaa29e9c730821430b7e33b32fc8fd0dc94d9a496370c76c'
WITNESSES_SHA256 = 'a036f387878300f15f44c9995f8189acc4c7eaae8048439ff287473a6bc77b8e'
SCOPE = frozenset(BASE_FILES)
ADDITIONS = frozenset({'protected_cohort_upgrade.py'})

def _normalized(content):
    value, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0'*64 + b"'", content, flags=re.M)
    if count != 1:
        raise ValueError('PROTECTED_COHORT_IMPLEMENTATION_CHANGED')
    return hashlib.sha256(value).hexdigest()

def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('PROTECTED_COHORT_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema','authority_effect','base_revision','files',
                      'additions','module_sha256','retained_profiles','predecessor_witnesses',
                      'opening_checker_normalized_sha256'}
            or value['schema'] != 'sentinel.protected-cohort-runtime-upgrade/1'
            or value['authority_effect'] != 'NONE'
            or value['base_revision'] != BASE_REVISION
            or set(value['files']) != SCOPE or set(value['additions']) != ADDITIONS
            or value['retained_profiles'] != RETAINED_PROFILES
            or value['opening_checker_normalized_sha256'] != OPENING_CHECKER_NORMALIZED_SHA256
            or hashlib.sha256(json.dumps(value['predecessor_witnesses'],
                sort_keys=True,separators=(',',':')).encode()).hexdigest() != WITNESSES_SHA256):
        raise ValueError('PROTECTED_COHORT_PROFILE_SHAPE_CHANGED')
    retained = []
    for name, expected in RETAINED_PROFILES.items():
        raw = PROFILE.with_name(name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('PROTECTED_COHORT_RETAINED_PROFILE_CHANGED')
        retained.append(json.loads(raw))
    for name, record in value['files'].items():
        before = {BASE_FILES[name]}
        for previous in retained:
            old = previous.get('files',{}).get(name)
            if old is not None:
                before.update((*old['before'],old['after']))
        for witness in value['predecessor_witnesses']:
            if name in witness['files']:
                before.add(witness['files'][name])
        if (set(record) != {'before','after'} or record['before'] != sorted(before)
                or not isinstance(record['after'],str)
                or not re.fullmatch('[0-9a-f]{64}',record['after'])):
            raise ValueError('PROTECTED_COHORT_SOURCE_RECORD_CHANGED')
    if (value['module_sha256'] != value['additions']['protected_cohort_upgrade.py']
            or _normalized(Path(__file__).read_bytes()) != value['module_sha256']):
        raise ValueError('PROTECTED_COHORT_IMPLEMENTATION_CHANGED')
    return value

def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']

def require_opening_checker_successor(normalized_sha):
    value = profile()
    actual = PROFILE.with_name('opening_latency_upgrade.py').read_bytes()
    if (normalized_sha != OPENING_CHECKER_NORMALIZED_SHA256
            or hashlib.sha256(actual).hexdigest()
            != value['files']['opening_latency_upgrade.py']['after']):
        raise ValueError('OPENING_LATENCY_IMPLEMENTATION_CHANGED')

def additions_allowed(actual):
    value = profile()
    expected = {**value['additions'],
        'protected_cohort_upgrade.py':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return set(ADDITIONS) if all(actual.get(name) == expected[name] for name in ADDITIONS) else set()
