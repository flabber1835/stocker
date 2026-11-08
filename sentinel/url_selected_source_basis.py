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
RETAINED_PREDECESSORS = {
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
PROFILE_SHA256 = '702b65d985082572d3d7b1c3affe8b22c571b32e56194338fa61e26d9b6716a1'
PROFILE = Path(__file__).with_name('url-selected-trading-transition.json')
_SCHEMA = 'sentinel.url-selected-trading-transition/24'
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


def _expand_retained(candidate, records):
    """Single-level deltas share validated paths, never independent pins."""
    if not isinstance(records, dict) or set(records) != set(RETAINED_PREDECESSORS):
        raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
    result = {}
    for revision, record in records.items():
        if not isinstance(record, dict) or set(record) != {'source_sha256', 'overrides', 'removed'}:
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        overrides = _source_map(record['overrides'])
        removed = record['removed']
        if (not isinstance(removed, list) or len(removed) > len(candidate)
                or any(not isinstance(name, str) for name in removed)
                or removed != sorted(set(removed)) or not set(removed) <= set(candidate)
                or set(removed) & set(overrides)
                or any(candidate.get(name) == digest for name, digest in overrides.items())):
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        removed_names = set(removed)
        files = {name: digest for name, digest in candidate.items() if name not in removed_names}
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
            'retained_predecessors'}
            or value['schema'] != _SCHEMA or value['authority_effect'] != 'NONE'
            or value['base_revision'] != BASE_REVISION
            or value['base_source_sha256'] != BASE_SOURCE_SHA256
            or value['structural_profile_sha256'] != STRUCTURAL_PROFILE_SHA256
            or structural.TRANSITION_SHA256 != STRUCTURAL_PROFILE_SHA256
            or _normalized(Path(__file__).read_bytes()) != value['module_sha256']):
        raise ValueError('URL_SOURCE_PROFILE_SHAPE_CHANGED')
    baseline = _source_map(value['base_files'])
    candidate = _source_map(value['candidate_files'])
    sealed = structural._profile()
    if sealed is None:
        raise ValueError('URL_SOURCE_PREDECESSOR_UNSEALED')
    expected = dict(sealed['candidate_files'])
    expected['structural_refactor_source_basis.py'] = _sha(Path(structural.__file__).read_bytes())
    retained = _expand_retained(candidate, value['retained_predecessors'])
    value = {**value, 'retained_predecessors': retained}
    for revision, (count, expected_sha) in RETAINED_PREDECESSORS.items():
        record = retained[revision]
        if (not isinstance(record, dict) or set(record) != {'source_sha256', 'files'}
                or record['source_sha256'] != expected_sha
                or len(record['files']) != count
                or _validated_closure(record['files']) != expected_sha):
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        if revision in {REVIEWED_PREDECESSOR_REVISION, INSTALLED_PREDECESSOR_REVISION,
                        DASHBOARD_PREDECESSOR_REVISION, PAPER_RELEASE_PREDECESSOR_REVISION,
                        VERIFIER_PREDECESSOR_REVISION, OPERATIONAL_PREDECESSOR_REVISION,
                        PATCH_PREDECESSOR_REVISION, LOCAL_PROBE_PREDECESSOR_REVISION,
                        PREPARATION_PREDECESSOR_REVISION, CHECKPOINT_ACCESS_PREDECESSOR_REVISION,
                        FEED_DISPLAY_PREDECESSOR_REVISION, STARTUP_PREDECESSOR_REVISION,
                        EFFICIENCY_PREDECESSOR_REVISION, DIAGNOSTIC_PREDECESSOR_REVISION,
                        ROOT_CAUSE_PREDECESSOR_REVISION,
                        READ_COST_PREDECESSOR_REVISION,
                        LIVENESS_PREDECESSOR_REVISION,
                        IDENTITY_AVAILABILITY_PREDECESSOR_REVISION,
                        WORK_COORDINATION_PREDECESSOR_REVISION,
                        PANEL_PRESENTATION_PREDECESSOR_REVISION,
                        STARTUP_PROFILE_PREDECESSOR_REVISION}:
            if not set(record['files']) <= set(candidate) | {_SELF}:
                raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        elif set(record['files']) - set(baseline):
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
    if (len(baseline) != 422 or _validated_closure(baseline) != BASE_SOURCE_SHA256
            or baseline != expected or set(baseline) - set(candidate)
            or _SELF in baseline or _SELF in candidate):
        raise ValueError('URL_SOURCE_COMPLETE_MAP_CHANGED')
    return value


def predecessor_view(actual: Mapping[str, str], *, previous=None) -> Mapping[str, str]:
    """Translate only the complete sealed candidate; retain actual identities."""
    value = _profile()
    if value is None:
        return actual
    expected = dict(value['candidate_files'])
    expected[_SELF] = _sha(Path(__file__).read_bytes())
    if actual != expected:
        return actual
    for record in value['retained_predecessors'].values():
        retained = record['files']
        if previous == retained:
            return retained
    return value['base_files']
