"""Independent expansion of the reviewed wire format for mutation fixtures."""
import json

from scripts.sentinel_source_history import encoded as encoded_profile
from sentinel import url_selected_source_basis as basis

__all__ = ['encoded_profile', 'expanded_profile', 'pre_market_history']


# The exact historical set before the market-buy successor was added.
_PRE_MARKET_REVISIONS = (
    '047b3910cbb107fd303d214b4945069bdc688948',
    '1842da067bd5f23bf8fc9ca88859e8208d8b302e',
    '1e7f4b181fbcb998b3086833ab813c21b1c2ca8e',
    '2059a359616a719e816003a48ec925868eec90e1',
    '21dfb0e8508d8d924a8b29a121977b1502997a0c',
    '2714afbb25fd169295358e035cefff59db2bf67d',
    '277160861e2353d8ad93d15da8e2615ebdb11c18',
    '29ff5f6592a46e89f13ed5d8416503071dc74ccf',
    '2e5e856c34e50958810a51f89e32b20db6a776a2',
    '34a28504a87610fd5c159115fc0b75017ae944ea',
    '35e3a118a8ee4d4efea5857f6e96d4dd8e23724a',
    '3f7a8eb072cdc661a2800d1a9bf409b687a34f32',
    '403617ec3df4ba0950a989fa140038802f7e7b6e',
    '4122aa29bc86dcf5c4e5d6a91047030a95bf9890',
    '42d775b6952138191f89deb5054f97c079624bc2',
    '430462d951653469157b5746830c0002f10f41fe',
    '4a08f5961a2dd0d5b174509b6afa4aa7d61d88a3',
    '4a395bfb4f13ba0f34fa0121fa62991fe7b38fed',
    '4bca82da1daff430b4f087493e4f200d2e9719dd',
    '4c13138360be48ca67255cea3b363b7b9abdb7a4',
    '4c90f4eebb660ee31947739d149a461f7576bcb9',
    '4dd0a32473caf25faac0a6e57491aaa5bed56ef2',
    '5ea4452570ebf526714fe64320001fb275418f1a',
    '64da9cccb49040acc4f32434bcdf6c31b7b6259e',
    '67458b20746979d08b8091f4519122bca528174f',
    '69c4d175356c1b4fffa680a39f886fa29f9053e1',
    '71b7c2a113dca8882f4cbf7a03d79f771e383092',
    '75b7c14f32f2e710561ef86a2d3d0782a019b355',
    '7d267e004b894b4d98ccad977bbbc041dcf4b11c',
    '8fafcfae9c46f471a834d7bd221497d6d940732a',
    '9484f7ec9612148f0496320db01a838696979719',
    '953351dc005b49db768d8462f727f92ffb77b58f',
    '9d0743834b63a6705b3638a291a8b32f390a9eca',
    'a0a82c6ad9211fdcf9fdad9faa801b8af65239ea',
    'b0d516022b1cc20375d987e7cf94236ce061710f',
    'ba05fe76950fe6d976e08edaadfd88a9e39dec0e',
    'bdb975c88c90a80c1ee7c98aed6dceeee12c8fc5',
    'c0d4ed7b6888e63c9d49584c6fcf063c6950f8f9',
    'c2569a4cb5085db15e24222478a1d5c98c53c74f',
    'e4d8671cb84af325fb5000cf8eaa2a4e0cf454c7',
    'e97a15753a71cb7e4e033db6171f1a2ee0e15955',
    'f58c22fba3d3f88d410084d051ca86b7d99562df',
    'fcfbd7b1e8bd1134ad14563347ab9df0980c545f',
)


def pre_market_history(profile):
    return {revision: profile['retained_predecessors'][revision]
            for revision in _PRE_MARKET_REVISIONS}


def expanded_profile():
    value = json.loads(basis.PROFILE.read_bytes())
    anchor = value['candidate_files']
    records = {}
    for revision, record in value['retained_predecessors'].items():
        files = dict(anchor)
        for name in record['removed']:
            del files[name]
        files.update(record['overrides'])
        records[revision] = dict(source_sha256=record['source_sha256'], files=files)
    return {**value, 'retained_predecessors': records}
