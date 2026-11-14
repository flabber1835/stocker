"""One complete URL-selected trading source edge, with no financial authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from sentinel import structural_refactor_source_basis as structural

BASE_REVISION = 'e790d2120d3e0d69b0c7a8935ab2de8d9d2c4666'
BASE_SOURCE_SHA256 = '6d83f60c1503637cf0f6f8b6757d41ca47d5e1afa768da99c01a82d98b4c62db'
RETAINED_REVISION = '403617ec3df4ba0950a989fa140038802f7e7b6e'
RETAINED_SOURCE_SHA256 = 'd83a9932ae32e0d87adde8691fcc36a7a8c1d93658f2c0ce954a211363918691'
PREVIOUS_BASE_REVISION = '71b7c2a113dca8882f4cbf7a03d79f771e383092'
REVIEWED_PREDECESSOR_REVISION = 'bdb975c88c90a80c1ee7c98aed6dceeee12c8fc5'
DASHBOARD_PREDECESSOR_REVISION = 'f58c22fba3d3f88d410084d051ca86b7d99562df'
INSTALLED_PREDECESSOR_REVISION = '2e5e856c34e50958810a51f89e32b20db6a776a2'
PAPER_RELEASE_PREDECESSOR_REVISION = 'fcfbd7b1e8bd1134ad14563347ab9df0980c545f'
VERIFIER_PREDECESSOR_REVISION = 'b0d516022b1cc20375d987e7cf94236ce061710f'
OPERATIONAL_PREDECESSOR_REVISION = '4122aa29bc86dcf5c4e5d6a91047030a95bf9890'
PATCH_PREDECESSOR_REVISION = '35e3a118a8ee4d4efea5857f6e96d4dd8e23724a'
LOCAL_PROBE_PREDECESSOR_REVISION = '4a395bfb4f13ba0f34fa0121fa62991fe7b38fed'
PREPARATION_PREDECESSOR_REVISION = '4a08f5961a2dd0d5b174509b6afa4aa7d61d88a3'
CHECKPOINT_ACCESS_PREDECESSOR_REVISION = '67458b20746979d08b8091f4519122bca528174f'
FEED_DISPLAY_PREDECESSOR_REVISION = 'e97a15753a71cb7e4e033db6171f1a2ee0e15955'
STARTUP_PREDECESSOR_REVISION = '64da9cccb49040acc4f32434bcdf6c31b7b6259e'
EFFICIENCY_PREDECESSOR_REVISION = 'c0d4ed7b6888e63c9d49584c6fcf063c6950f8f9'
DIAGNOSTIC_PREDECESSOR_REVISION = '8fafcfae9c46f471a834d7bd221497d6d940732a'
ROOT_CAUSE_PREDECESSOR_REVISION = 'ba05fe76950fe6d976e08edaadfd88a9e39dec0e'
READ_COST_PREDECESSOR_REVISION = '29ff5f6592a46e89f13ed5d8416503071dc74ccf'
LIVENESS_PREDECESSOR_REVISION = 'c2569a4cb5085db15e24222478a1d5c98c53c74f'
IDENTITY_AVAILABILITY_PREDECESSOR_REVISION = '34a28504a87610fd5c159115fc0b75017ae944ea'
WORK_COORDINATION_PREDECESSOR_REVISION = '4bca82da1daff430b4f087493e4f200d2e9719dd'
PANEL_PRESENTATION_PREDECESSOR_REVISION = 'a0a82c6ad9211fdcf9fdad9faa801b8af65239ea'
STARTUP_PROFILE_PREDECESSOR_REVISION = '430462d951653469157b5746830c0002f10f41fe'
ACTIVATION_HEALTH_PREDECESSOR_REVISION = '2714afbb25fd169295358e035cefff59db2bf67d'
PLAN_WORK_PREDECESSOR_REVISION = '1e7f4b181fbcb998b3086833ab813c21b1c2ca8e'
BACKUP_RENEWAL_PREDECESSOR_REVISION = '5ea4452570ebf526714fe64320001fb275418f1a'
OPENING_OBSERVATION_PREDECESSOR_REVISION = '2059a359616a719e816003a48ec925868eec90e1'
BOUNDARY_DISPLAY_PREDECESSOR_REVISION = '953351dc005b49db768d8462f727f92ffb77b58f'
DISPLAY_DEPENDENCY_PREDECESSOR_REVISION = '7d267e004b894b4d98ccad977bbbc041dcf4b11c'
DISPLAY_SEQUENCE_PREDECESSOR_REVISION = '4c13138360be48ca67255cea3b363b7b9abdb7a4'
CLOSE_TRACE_PREDECESSOR_REVISION = '69c4d175356c1b4fffa680a39f886fa29f9053e1'
ACCOUNT_CLOCK_PREDECESSOR_REVISION = '4c90f4eebb660ee31947739d149a461f7576bcb9'
INTEGRITY_WORK_PREDECESSOR_REVISION = '277160861e2353d8ad93d15da8e2615ebdb11c18'
BACKUP_DEADLINE_PREDECESSOR_REVISION = '4dd0a32473caf25faac0a6e57491aaa5bed56ef2'
MAINTENANCE_CONTINUITY_PREDECESSOR_REVISION = '9484f7ec9612148f0496320db01a838696979719'
OPENING_REPAIR_PREDECESSOR_REVISION = 'e4d8671cb84af325fb5000cf8eaa2a4e0cf454c7'
TRANSPORT_RESOLUTION_PREDECESSOR_REVISION = '1842da067bd5f23bf8fc9ca88859e8208d8b302e'
RETIREMENT_RENEWAL_PREDECESSOR_REVISION = '9d0743834b63a6705b3638a291a8b32f390a9eca'
INSTALL_CRITICAL_PATH_PREDECESSOR_REVISION = '21dfb0e8508d8d924a8b29a121977b1502997a0c'
CLOSE_ROOT_PREDECESSOR_REVISION = '42d775b6952138191f89deb5054f97c079624bc2'
BACKUP_REFRESH_PREDECESSOR_REVISION = '3f7a8eb072cdc661a2800d1a9bf409b687a34f32'
BACKUP_MARGIN_PREDECESSOR_REVISION = '047b3910cbb107fd303d214b4945069bdc688948'
OPENING_STABILITY_PREDECESSOR_REVISION = '75b7c14f32f2e710561ef86a2d3d0782a019b355'
MARKET_BUY_PREDECESSOR_REVISION = '5a49fa1b0e658bbb59dccda4089bb3ec1aada0e3'
CLOSE_RELIABILITY_PREDECESSOR_REVISION = '1692c0421084198e3cba03d098d2d0f92adbb79d'
SIMPLIFICATION_PREDECESSOR_REVISION = 'd75e75a01051662e8948254ebbd562a15c8fac3e'
BACKUP_HEADROOM_PREDECESSOR_REVISION = 'a81a9e406997e4057f92c2be4b33ba89a060e038'
OPENING_RECOVERY_PREDECESSOR_REVISION = 'fad555c0ea0449a9225b01c8f6d96e22140b35b3'
CASH_CORRECTION_PREDECESSOR_REVISION = '509b66c5f50ffbe4b22331a471c1d021c9dde99d'
OPEN_CLOSE_DASHBOARD_PREDECESSOR_REVISION = '35761cbbb2232c0fcb51cd37c97cdf5c3851ca17'
ROLLING_GO_INDEX_PREDECESSOR_REVISION = '5ebacfb46d8fbc15e3b698b11bb610d951565d92'
NATIVE_FEE_POSTING_DELAY_PREDECESSOR_REVISION = 'e9ef8b51259898a84f4b2c21f8e601e9ed9a5922'
OPENING_OUTCOMES_PREDECESSOR_REVISION = 'aed1a26c335281169c6d8067b1ce2e7de1632053'
ZERO_SHARE_RETRY_PREDECESSOR_REVISION = '0ca281a0f7f8f03a02407b297e3d0383461bc1d3'
NOV13_CLOSE_PREDECESSOR_REVISION = 'e8a51971a9e7479bdd6c9c5c66326f2397d9bab9'
FRACTIONAL_PREDECESSOR_REVISION = 'aed1a26c335281169c6d8067b1ce2e7de1632053'
NOV13_INSTALLED_REVISION = 'e6e1274d879103e9282c3ad2d7427560ca3b7290'
RETAINED_PREDECESSORS = {
    NOV13_INSTALLED_REVISION: (477, '57b631f4b8320a19c8efa6dbb99dfd15ff3a9852f7fc0f0b07565e353977af99'),
    NOV13_CLOSE_PREDECESSOR_REVISION: (477, 'ee5019fc2738ed6d39b6cf5cdb63e7fdd8749177dff8ac525c2fe0ae47e87a70'),
    ZERO_SHARE_RETRY_PREDECESSOR_REVISION: (477, 'f4debda5997d32763f75dec7b301391951d54ce600fdec9d59929b33245a762f'),
    FRACTIONAL_PREDECESSOR_REVISION: (476, 'a765d57aaee204f0e5b734fd6d34ef8092ce4c4c4d0ca29b7f9fdf9b158551d2'),
    NATIVE_FEE_POSTING_DELAY_PREDECESSOR_REVISION: (475, '9b8784f7b1a97757c100fc3ece7fee0969712b8d5e4badd1bf726ff1cf345f28'),
    ROLLING_GO_INDEX_PREDECESSOR_REVISION: (475, 'a2b9ae096cb8bb52ea61491fc793cdabddf3d0a52b4b2a6ce42222b0b0d31e72'),
    OPEN_CLOSE_DASHBOARD_PREDECESSOR_REVISION: (475, '5d85fbb62053aca94a44a3db971876efd826b6ed8027b98da14826e3b3f8100c'),
    CASH_CORRECTION_PREDECESSOR_REVISION: (475, 'f95dd91f021b25965c8307ed90f636edc6bb66fe4f5a1c65e2591933bc98ea11'),
    OPENING_RECOVERY_PREDECESSOR_REVISION: (475, '129def6620017e734a6733dd9cfc541f8fd9a12f52f8227c9f3737e444d5f1fe'),
    BACKUP_HEADROOM_PREDECESSOR_REVISION: (475, '43794042e2f39be91712bbd5dfe764a411976fa8b9105a9a83b9cc44c634d151'),
    SIMPLIFICATION_PREDECESSOR_REVISION: (473, '6e5c9464b95d991f8af2887e22cddaf3f3348b0c5deb0ade7dd960208f811772'),
    CLOSE_RELIABILITY_PREDECESSOR_REVISION: (471, '9b7907bf1bbd7080607802f329604e7c554d3d5da6ae005cfa2532ca7129ef43'),
    MARKET_BUY_PREDECESSOR_REVISION: (469, '082bc5ae6789dea75a193b4c49ba51b3e1123b49505bec62344de151afa09544'),
    OPENING_STABILITY_PREDECESSOR_REVISION: (469, '81e23cc8b17e0ad3b754e1b972b2bbe3f3927419fc19115ec0e6dfd15ad1f0e5'),
    BACKUP_MARGIN_PREDECESSOR_REVISION: (469, '3cd7fe2e6195939cec67a2e459ac542b6b30ba24b0ca7f9226bc4467f43e1726'),
    BACKUP_REFRESH_PREDECESSOR_REVISION: (469, 'a7b294d88bdcabf4499ddbb00d07bb4946ed82b086571133cb4c0596c3daeb11'),
    CLOSE_ROOT_PREDECESSOR_REVISION: (469, '890c1546a6ed20243517e263d5b6755e8e89039997fa7447aa4eef30dc20a702'),
    INSTALL_CRITICAL_PATH_PREDECESSOR_REVISION: (469, '1e01510061f93445999f81fb503d70255e46be3fc46a40337a1886a28bc7ce9e'),
    RETIREMENT_RENEWAL_PREDECESSOR_REVISION: (469, '361372ad62cdb8b567089cde38da4ef09da1aaa293d33b1a7606e7eb175fb9b5'),
    TRANSPORT_RESOLUTION_PREDECESSOR_REVISION: (469, 'd91cc2fa70a92fc893a29571343b767776d82d1a863c8efe4ca38103a7344e55'),
    OPENING_REPAIR_PREDECESSOR_REVISION: (468, '396f96370ede595c548245f042315e7b016a2ff96a339d1b40ad0c90472f3895'),
    MAINTENANCE_CONTINUITY_PREDECESSOR_REVISION: (468, '229d162def187d350ab21e6b2f1ea92647a6b36291d4cfed532859dc8a5d6747'),
    BACKUP_DEADLINE_PREDECESSOR_REVISION: (468, '646f1551ab2cd51e61c69e9d528b1979cf5a1dc6f861e1a1d842514f757f9e61'),
    INTEGRITY_WORK_PREDECESSOR_REVISION: (466, 'c4cdbfa7dca223924b047587710750062eec1dd107c38e2964bc1ec125dd56bc'),
    ACCOUNT_CLOCK_PREDECESSOR_REVISION: (466, 'f24c3543ce5b2f25d63d409b5d9b174b4273ec6fafe6fc4a817c4a9952f33332'),
    CLOSE_TRACE_PREDECESSOR_REVISION: (465, 'cf1c4270e33e79725188018aa7b15a6b27a0c814d86784c1a9050bc5140866b3'),
    DISPLAY_SEQUENCE_PREDECESSOR_REVISION: (465, '108be080769643dac94a1f092633adb38661b52c6776ef7a999df9ad51a7be05'),
    DISPLAY_DEPENDENCY_PREDECESSOR_REVISION: (464, 'e9bbe9e5df9acd4d8c0397112d8b5ec9ea7640ff70d926b4a8ee1ba6f609cdf2'),
    BOUNDARY_DISPLAY_PREDECESSOR_REVISION: (464, 'a8e082c1ae48ad56927d8a1a1c867eec25e59a1b67546685f71a4bb5b751969d'),
    OPENING_OBSERVATION_PREDECESSOR_REVISION: (464, 'cfd26b1b2fe1b6ec122d9f74f3c80ce9a34b2425fdb5827c2a52ff75249f63ee'),
    BACKUP_RENEWAL_PREDECESSOR_REVISION: (464, 'b8dc59db31e58612c7d3f633657f6a6558b5fde01af5881c28eae293f1f6c26f'),
    PLAN_WORK_PREDECESSOR_REVISION: (463, '17e4297b1d60a397b73994d8259252d8fd9275beb0f2657816fc357301a3de9b'),
    ACTIVATION_HEALTH_PREDECESSOR_REVISION: (463, 'ec90eb9779d0ea2b0b3c7a65dd4e2219347c9809c54a610a08e6f2716dc4f4a5'),
    STARTUP_PROFILE_PREDECESSOR_REVISION: (463, 'fbacab07df6d2cc5410ad2e3ec3825b7e50a576ab2be0382e8dc37da123e8a5a'),
    PANEL_PRESENTATION_PREDECESSOR_REVISION: (463, '9385294419b070cf3955f0cc3eb3370442883f8113b8cc4dd8f5b64beece4d4f'),
    WORK_COORDINATION_PREDECESSOR_REVISION: (460, '09c34f464748a92aaa11f6290b34d3fbd0fdf699f5b3e7372bb1b865b42d08f2'),
    IDENTITY_AVAILABILITY_PREDECESSOR_REVISION: (460, 'e7d7971f85feb8e4432589d06cf796e4395dc2b1c2d7eddf4f5f38877d5ee73c'),
    LIVENESS_PREDECESSOR_REVISION: (460, 'f736ee435a581843342b64420e371ae1e8169d138121aa6454fc623437f50581'),
    READ_COST_PREDECESSOR_REVISION: (456, 'a51ce3e5b875a0e359160d9e76e73b50156fba244411546e741a14f4839d0c46'),
    ROOT_CAUSE_PREDECESSOR_REVISION: (456, '7706a3683dbee27c684291f520517f2e6f2447f3de4662dbd9b7b3b111692929'),
    DIAGNOSTIC_PREDECESSOR_REVISION: (456, '92dcbcf6559efb0d19476438dae0a653850d44afc7bb7dc7b69294b38f5035b5'),
    EFFICIENCY_PREDECESSOR_REVISION: (455, 'abe9a2628cc3d46e43a73e9b811e5855c89f3af74619aca87fd765402c8bfc95'),
    STARTUP_PREDECESSOR_REVISION: (455, '5470089498b2e6341865fd5483732c07f347e0019de71376dfdbbc8b2121c344'),
    FEED_DISPLAY_PREDECESSOR_REVISION: (454, 'c3eb52854101901c854cdf84b944ba5e0abcb0e077824ded15ca714b10161eab'),
    CHECKPOINT_ACCESS_PREDECESSOR_REVISION: (453, 'f4eaa5729cee9c2ce5794e4fa334c945dbf2ab2cadd55a77aa35a8b1abe61121'),
    PREPARATION_PREDECESSOR_REVISION: (451, '9888f64b30c02da6b06091c52a6961d91282a5473142cdf4519b865bc6459f46'),
    LOCAL_PROBE_PREDECESSOR_REVISION: (451, '2778b44660897768e9f808e4f26ac16847e158feba06f3b5187a3ab9defb8552'),
    PATCH_PREDECESSOR_REVISION: (451, 'ea3e4e163241a2075bf5b49fa965b384e65bf2f8456a7e346e0fe8bba38978f8'),
    OPERATIONAL_PREDECESSOR_REVISION: (442, '18de9f4c50f1695aeaa11cdc59081267ab1274f318ab9abc3e470a568ad48e42'),
    VERIFIER_PREDECESSOR_REVISION: (442, 'db2228d6def65283cb75ac3da8f3250a99fb3f180600f9fd9e52b46cf6da0ee8'),
    PAPER_RELEASE_PREDECESSOR_REVISION: (442, '95b41c4029df447215be2f04bcce5a25c7a4fe629e130cc37a673badc22cedca'),
    DASHBOARD_PREDECESSOR_REVISION: (440, 'a84f981e687970d230b197025a0b4260e9587aaf6381a7ecc64022761cfa02fa'),
    RETAINED_REVISION: (421, RETAINED_SOURCE_SHA256),
    PREVIOUS_BASE_REVISION: (422, '85f353c936459255c048aedc366272ca4c6f3053f654a006da61a42af2688352'),
    REVIEWED_PREDECESSOR_REVISION: (434, 'a8b6cce6e00654f402fd74735b66e0711331c44b3ea171e0241a40230b4096a4'),
    INSTALLED_PREDECESSOR_REVISION: (434, '85165e291f835307e86d45a1c678d44529ce42d1d46713614147c676ade7c47b'),
}
STRUCTURAL_PROFILE_SHA256 = '139d811983db0777eb6a92949e7e6adbe1c12d063c05d40c461f918cc741c5a0'
PROFILE_SHA256 = '36c911d2d0ae1c93622aa00318c4512ef5e030da5a967fc4099fd2cf5d674a98'
PROFILE = Path(__file__).with_name('url-selected-trading-transition.json')
_SCHEMA = 'sentinel.url-selected-trading-transition/57'
_SELF = 'url_selected_source_basis.py'


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('URL_SOURCE_PROFILE_DUPLICATE_KEY')
        result[key] = value
    return result


def _source_map(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) > 1024:
        raise ValueError('URL_SOURCE_MAP_CHANGED')
    result = dict(value)
    for name, digest in result.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ValueError('URL_SOURCE_MAP_CHANGED')
        path = Path(name)
        if (path.is_absolute() or path.drive or '..' in path.parts
                or path.as_posix() != name or '\\' in name
                or '__pycache__' in path.parts or not name.endswith('.py')
                or re.fullmatch('[0-9a-f]{64}', digest) is None):
            raise ValueError('URL_SOURCE_MAP_CHANGED')
    return result


def _closure(files: Mapping[str, str]) -> str:
    return _validated_closure(_source_map(files))


def _validated_closure(files: Mapping[str, str]) -> str:
    """Hash an already path/digest-validated complete inventory."""
    result = hashlib.sha256()
    for name, digest in sorted(files.items()):
        result.update(name.encode() + b'\0' + digest.encode() + b'\n')
    return result.hexdigest()


def _expand_retained(anchor, records):
    """Single-level deltas share validated paths, never independent pins."""
    if not isinstance(records, dict) or set(records) != set(RETAINED_PREDECESSORS):
        raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
    result = {}
    for revision, record in records.items():
        if not isinstance(record, dict) or set(record) != {'source_sha256', 'overrides', 'removed'}:
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        overrides = _source_map(record['overrides'])
        removed = record['removed']
        if (not isinstance(removed, list) or len(removed) > len(anchor)
                or any(not isinstance(name, str) for name in removed)
                or removed != sorted(set(removed)) or not set(removed) <= set(anchor)
                or set(removed) & set(overrides)
                or any(anchor.get(name) == digest for name, digest in overrides.items())):
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        removed_names = set(removed)
        files = {name: digest for name, digest in anchor.items() if name not in removed_names}
        files.update(overrides)
        if len(files) > 1024:
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        result[revision] = dict(source_sha256=record['source_sha256'], files=files)
    return result


def _normalized(raw: bytes) -> str:
    normalized, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0' * 64 + b"'", raw, flags=re.M)
    if count != 1:
        raise ValueError('URL_SOURCE_IMPLEMENTATION_CHANGED')
    return _sha(normalized)


def _profile() -> dict | None:
    if PROFILE_SHA256 == '0' * 64:
        return None
    raw = PROFILE.read_bytes()
    if len(raw) > 1_000_000 or _sha(raw) != PROFILE_SHA256:
        raise ValueError('URL_SOURCE_PROFILE_CHANGED')
    value = json.loads(raw, object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite profile')))
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'authority_effect', 'base_revision', 'base_source_sha256',
            'base_files', 'candidate_files', 'module_sha256', 'structural_profile_sha256',
            'retained_predecessors', 'retained_anchor_files'}
            or value['schema'] != _SCHEMA or value['authority_effect'] != 'NONE'
            or value['base_revision'] != BASE_REVISION
            or value['base_source_sha256'] != BASE_SOURCE_SHA256
            or value['structural_profile_sha256'] != STRUCTURAL_PROFILE_SHA256
            or structural.TRANSITION_SHA256 != STRUCTURAL_PROFILE_SHA256
            or _normalized(Path(__file__).read_bytes()) != value['module_sha256']):
        raise ValueError('URL_SOURCE_PROFILE_SHAPE_CHANGED')
    baseline = _source_map(value['base_files'])
    candidate = _source_map(value['candidate_files'])
    anchor = _source_map(value['retained_anchor_files'])
    if (len(anchor), _validated_closure(anchor)) != RETAINED_PREDECESSORS[FRACTIONAL_PREDECESSOR_REVISION]:
        raise ValueError('URL_SOURCE_RETAINED_ANCHOR_CHANGED')
    sealed = structural._profile()
    if sealed is None:
        raise ValueError('URL_SOURCE_PREDECESSOR_UNSEALED')
    expected = dict(sealed['candidate_files'])
    expected['structural_refactor_source_basis.py'] = _sha(Path(structural.__file__).read_bytes())
    retained = _expand_retained(anchor, value['retained_predecessors'])
    value = {**value, 'retained_predecessors': retained}
    for revision, (count, expected_sha) in RETAINED_PREDECESSORS.items():
        record = retained[revision]
        if (not isinstance(record, dict) or set(record) != {'source_sha256', 'files'}
                or record['source_sha256'] != expected_sha
                or len(record['files']) != count
                or _validated_closure(record['files']) != expected_sha):
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        if revision not in {PREVIOUS_BASE_REVISION, RETAINED_REVISION}:
            if not set(record['files']) <= set(candidate) | {_SELF}:
                raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        elif set(record['files']) - set(baseline):
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
    if (len(baseline) != 422 or _validated_closure(baseline) != BASE_SOURCE_SHA256
            or baseline != expected or set(baseline) - set(candidate)
            or _SELF in baseline or _SELF in candidate):
        raise ValueError('URL_SOURCE_COMPLETE_MAP_CHANGED')
    return value


def predecessor_views(actual: Mapping[str, str], *, previous=None):
    """Authenticate the candidate once and return its predecessor and base views."""
    value = _profile()
    if value is None:
        return actual, actual
    expected = dict(value['candidate_files'])
    expected[_SELF] = _sha(Path(__file__).read_bytes())
    if actual != expected:
        return actual, actual
    base = value['base_files']
    for record in value['retained_predecessors'].values():
        retained = record['files']
        if previous == retained:
            return retained, base
    return base, base


def predecessor_view(actual: Mapping[str, str], *, previous=None) -> Mapping[str, str]:
    """Translate only the complete sealed candidate; retain actual identities."""
    return predecessor_views(actual, previous=previous)[0]
