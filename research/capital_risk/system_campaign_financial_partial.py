"""Authenticate stopped financial evidence and reproduce recorded reporting only."""
import ast
from copy import deepcopy
from decimal import Decimal, localcontext
import gzip
import json
from pathlib import Path
import re
from types import SimpleNamespace
import zipfile
from contextlib import contextmanager, nullcontext, ExitStack

from full_system_benchmark import need, save
from full_system_core import hosted
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from stage import PROTOCOL, IMAGE
from system_campaign_facts import digest, sha
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_parallel_discovery import check_parent
import system_campaign_factual_admit as crypto

HERE = Path(__file__).parent
ORIGINALS = 'system-campaign-parallel-discovery-parents.json'
CRYPTO_SHA = '63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'
FORMAT = 'FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1'
FRESH_FORMAT = 'FRESH_CANDIDATE_SIX_MEMBER_ZIP/1'
FRESH_REQUEST = 'system-campaign-fresh-origin-request.json'
FRESH_TARGET_SHA = '0aaa2967a245b4eefc9097fd84b6227a0f99717c65dc88b21b2736aeecdf2d1d'
FRESH_REQUEST_SHA = '13d68690a7e940bc52d1060098a04d577932f292b30418a29cbfc2346f242b0d'
INITIAL_PREFIX_TARGETS = {
    'P03': '6ddbfef83b3f4d69922cd65deabe7ab8d54db983fca9652c89c0e4948e99fb18',
    'P05': 'd56ad992d8086d0815cbeabc57dd2bec5971e9bff051e2bd65ab4d37799c3faf',
    'P06': '651d13b0bbc442d44f4735374c56bdb2e49b6d6275b5f7e2d875705c0db75436',
    'P11': '14678692a6ed71a18c7ded8b66e4146148a8608403fcfb9a05c744797c3e869e',
}
INITIAL_PREFIX_AXES = {
    'P03': (82, '2018-04-30'),
    'P05': (21, '2018-01-31'),
    'P06': (21, '2018-01-31'),
    'P11': (21, '2018-01-31'),
}
ROOTS = 'system-campaign-financial-admitted-parents.json'
ADMISSIONS = {
    'P03': '4c56c4240f1e5f36c91e76f5033ba9748d1217879043885e415727894b67fad1',
    'P11': '01d9f480ee14644206c37d7c7c9ed46da55ed000056042e85f59f41d74440ecf',
    'P06': '28c768af0d50047f04ddd6924c1500bf768cc138f41808cd1c0a0b5321eb64b8',
    'P05': 'ca722bb750ee34ed6f7db8e114b1561f4988f08385fccd91ddc2d0867f1ba209',
    'P00': 'a666dc395e4c3d6e84ae7402967e28befa65052d84d6da68d5df52b8bc9970bc',
    'P04': 'c43253a987d6e930f3a60b14e85a52fd0c05f768c6113132d0448d1fc8d99a9a',
    'P07': 'd9c73a5ceebdc806feeae4338034626c0c3b4aef42309f3849d69c20cfbf8f7b',
    'P10': '3e73749345802edc681eb20d1adbaf741bebab3df9ea7bcc7ff4ac453a50b0e9',
}
COMPLETED_ADMISSIONS = { 'P11': '39a62ec7297f0a0c784447970a7ddf39d7a199cf9231e57b0f7cfc13091451ec','P04': '301789ec44be3eabc3d4c7985a456f48f46f35b6db976ef60902ba93644d04e9', 'P00': '65637d23029e0817822c169e7d424e00cd75a01703cb22a6aeb1b3f69b390f83', 'P10': '6e20b57099843380d9436d7a60c25c313abe53785f9db40049f59b411c9e8105'}
COMPLETION_METADATA = { 'P11': ((42033015471, '023bbb7f40a2d357831635cb311df184416d1cea', 13416758632), (63, 126, 3, 103)),
    'P04': ((41873209115, 'bc86a3c7b929e405aa0513d75b35850752579847', 13344609868), (186, 372, 9, 103)),
    'P00': ((41850177338, '7f8a9902b8e334ec155e6155f3df444c456c73eb', 13336350083), (273, 546, 13, 103)),
    'P10': ((41813568077, '9689c5fecc5462a5d65370fc5564fe447a8a92f8', 13313801504), (564, 1128, 27, 103)),
}
PRIOR_ADMISSIONS = {
    'P04': '11c64d8c83d26c8e381ddc4e306829e896f3996c423c394d50c5b2d2d0307492',
    'P07': '760e41a64a8e2fdf497c96919a5aef9eaa34a9faddee26bc9b5cee843b2ab8fa',
    'P10': 'c3e9784fdaee742284dc4f7d90aaecbcb541cb50f699dabbb17e8c250f68815c',
}
ADMISSION_CLOCKS = {
    'P03': {'4c56c4240f1e5f36c91e76f5033ba9748d1217879043885e415727894b67fad1': (42163448952, 'aae0c6b12c2320df63f417bcd63818707d7fd93d'), '2dfc5b30f486d40f97ab4f93c21ae75862714f0d0b410bd56228b137370329d0': (42026897600, '629f6cb2e614faf46fab2d4ee49ff9183534489c'), 'bd698ea48738875baa59796f671ccf7439885976a5b439bf4d9bd4cddeb9164f': (41972375545, 'e5a41017ce88df64fa0742160830b85d7b705dc0'), 'e49c8db66e8f579cb75334ff3931b98e78032e35dafee6002fea437457c77544': (41954531435, 'd782d34c7cfa0fae28b4d5067db2db746ffe8428'), '8ecd29cc5e697485482e80c159d89a2a32f1ed94d00740c93cd7241a6518f0fe': (41948522427, 'a0592dde1a91ac14f47896bbba6882f93e0c2b8b'), 'a89d9976ab0621b14d921fe9079784d62d835d9634b9ed423d66060d925eb3cd': (41940774529, 'ec14a901cdc3d95cd131a179f0cf6b70ec618bec'), '84381db5458891e421209047b2933c8182c981ccc106743ab5f9ca946fa135a7': (41926234636, '491059f67d4089366f35351cecb35a1b0472ec66'), '9a17edfdacaf8ffe75ead2e0b12bd2650e19b4cbd948526317703a842b89141f': (41910889751, '9ed72678cdb29ca8ccc9382fad2241a5cf4f0379'), '70ebc8c3f1378bf7b18a84326bdb172fc5bdd120c9e24b6feb8dbc9f01293002': (41906687252, '769b29b0f4502304840bc3bd6dd18b4f529f61da'), '65b4309305ed9a62a6dfd9db12070d124dcc7e5efcc1a582555386ff5c7dbd9c': (41880115517, '2e9c7f584e3c351eb80f7ce5e6fb6d41c1c18768')},
    'P11': {'01d9f480ee14644206c37d7c7c9ed46da55ed000056042e85f59f41d74440ecf': (42008422821, 'e570f3f2e20c22193299875a7b380cd063d36cb3'), '4a8df8bc01d3bbf40621bf30797fa36d2139dff9369e3f3e2791305922e1002a': (41981587623, '6fb3a5429d24194b3c4df49677885d761f0647b4'), 'ab8b38df9778710adafbeabdd6deea6491d498a55138be00da5cce11da8b94be': (41969552655, 'edfcbafc746d39bb39f6913e1b8471975d5f8c81'), '901485e00d7d7046894a817817da94c5173dcf5aec2c91a6d120aa8b5d96d81a': (41948522427, 'a0592dde1a91ac14f47896bbba6882f93e0c2b8b'), '98721a1b50ebb8a28c4ca9f7572d0722dcb6091da7b3f2fbba68d3b3ce768004': (41937085037, 'd7479158261809b56b2c50fa9e6d271d3f75c8c9'), '769391316b8f6f06dd5c33094759356f894d313c37d2629e82c12ee7e1c75fae': (41930626478, 'd466fc599fb631fbb18fb86421115534e1ce1eda'), 'a2cd1c0d680f78f93d021de662f6dff7def0cb4add2ed15c28349acc8670f3d2': (41923826375, '0993a90790bd5708a1df2fa3f27fe05db875e1a4'), '524ad7d5c2ca46bd48d6fdd7066c788ba557e62116246a1fae9b00845a106e58': (41906687252, '769b29b0f4502304840bc3bd6dd18b4f529f61da'), '6e3e47e8010e83eff94c228d31f4222d9a1fbce27013b87d1fae41d8b02ad517': (41894539616, '08ba5f1e1f8f114d81d5d94016242da163921725'), '33320498ba5db684738471b48b0ed3e66ebf78fe5b2b9dc24a34be047cdbf3ed': (41869499928, '4615284d77f1edef54abadaeccc877bf21c9bdb2'), '6d6cb4beb530ba6f26323cc4c988984631639f4439728144e4e6f11c5787128c': (41846392431, 'c5a96301d911d6657494738161d88152d7690fd3')},
    'P06': {'28c768af0d50047f04ddd6924c1500bf768cc138f41808cd1c0a0b5321eb64b8': (42180922941, '6b8e7dca981edb0ecd174e1b23ba48aa6636ffab'), '41520825b51f125272ed44bb01ca58905fe7b170005fc1a1c4a72856bf01263f': (42168036006, '427afef0beaa69f44487cbb1f6f8cb556d59a095'), '947662b7b86089285e5d7360221ff3a6d931173bccbce6ac8884341d396c763e': (42026897600, '629f6cb2e614faf46fab2d4ee49ff9183534489c'), '492d237b92b995ee1fdc1f6e81049f62688df5981cd5b72f493245c695fb6fc9': (41996816448, '26aa75d0c96a9d26021a85901f6523b2c74ac740'), 'f8be3c331ac12f211c630078d128278c155eb99a98afaff81bc8219e435094aa': (41975953317, '0991526a6db5d32d41359994e85f3c5740449e8b'), 'c83fbf2782f14d67bbdc82e687ef34c5c9e1dfd9769c0381dee1b3198c8d323e': (41963276143, 'fdb6fa283509008385a3ce06ce44fdd5cb527e6a'), 'ddc313079ef6bf40cc81cd79d6927859cad9172c7d107b60119b69064c0cdad5': (41956759896, 'fc585a6d57b93dce1af0dac9e427ec6174908694'), 'b5159227c4bdbaebb7a246062cb73cf5e3190b0805c9f4f3b93e15a6193765ec': (41947440911, '5f090ecfcdb4330be4d02cf2f19f7ac6f5389ddb'), '45a6bf68f61ddd5eaa2852faddc26dea4541b49d5e477c614416dd13f4172bb2': (41869499928, '4615284d77f1edef54abadaeccc877bf21c9bdb2'), 'f7421f89b0f7af3abac7cec3c475eb19a18b0c3cfe7094929e55248121125e18': (41846392431, 'c5a96301d911d6657494738161d88152d7690fd3')},
    'P05': {'ca722bb750ee34ed6f7db8e114b1561f4988f08385fccd91ddc2d0867f1ba209': (42266389339, '190fb8dd0024ff82e9021507c33113a37e73aec5'), 'baabf01e4e070faea5c03fb0055fa715ac075a0175d5bdcc24b356a922cb1026': (42170906119, '703132f9e161a923c1338bb4cdc8b9a833d367ca'), 'e50bb7bb725c4636ad882b8b36b69aa1de9b7decc90fc611aa922f27b3e602c6': (42153827086, '67e59a497da92234e5b9aa85c84aff51159cf655'), 'fbc6821ce4ae8beb5e24805d8f2b10a2b5f0941b6f9c15e21c1ae7b3ce121add': (42141444469, '1352dc2b0e336f8c741a4126e81022d99e977c8f'), '402b9ce10942fca4dcaac829303c6426a83a6a894ecf35d9cf472c4d84a8bb8d': (42118147846, '24a72192b6dff9c46fb44bc7ba690ab7cc8ccece'), 'c3cb03f790d12d7d69b29da38727b3e24f7e7be411be70a22118470c3583b29f': (42063242108, '776e4ba71b9bab64162915b2a741364434801dc1'), 'bb544ebebf83b35219a33ddb30141404c9df6243f5736eee1a069a8420ba96d5': (42023552646, 'e2becac42d7774ea5031a909abd026c61e46fef5'), '798631a219bbd2926c6e2a6633bdf71ab1cc5e013094c343bdfc86deee9045b7': (41981587623, '6fb3a5429d24194b3c4df49677885d761f0647b4'), 'b1b4db73909f584bf7704cf33158eacc9ce1f8a8cbe212785d8f9b3404e6dede': (41969552655, 'edfcbafc746d39bb39f6913e1b8471975d5f8c81'), 'b2377e959fb5351f80b80ad4e045a93b7495bc52c323fa5ef6ddcc770ac3e5bf': (41959654419, '273ef4cb90c0cfba5e048f268c8f798e414bc3ce'), 'a19ff05c0685ab37fc886c3ddcde7b958e083b60af9904087ba1822937a65078': (41947440911, '5f090ecfcdb4330be4d02cf2f19f7ac6f5389ddb'), '792cbf186292d30e81c370941b97083ce31a5226d19009e40771de16c1250951': (41937085037, 'd7479158261809b56b2c50fa9e6d271d3f75c8c9'), '95087a57a75a2747966d9e2afdf5c6c729409381dd8f2d42b011b8218bf37519': (41921472717, 'c9de9b5c2b34bf369544b8394f915c167019ea4d'), '986666fa60c8c97f8ce6173a557d8773f7e1c578a44de7066f46239cfcea36f4': (41915636893, '1b6029e476f87c453e45b7e27403f83da32df11a'), 'b4294c0c98f8fbf0668ba3235a264a56a30ead83a4c97b89035e7d2bec6384f5': (41891185379, '1ba6755b4b0d9bb03a699e54fc7f61a13cc052f7'), 'cdd16c9f0b0ceef3cd8122ef586e23c43c2ebfe662d7cd0a9cb38430a271781a': (41878282620, '5e3c556b1023053f214daf0a77c8a4fc3491b439'), 'b5135e817ef9359ce83922fbe9200cfc32033628d2ff98fec1673e8d9ebd2197': (41846392431, 'c5a96301d911d6657494738161d88152d7690fd3')},
    'P00': {'a666dc395e4c3d6e84ae7402967e28befa65052d84d6da68d5df52b8bc9970bc': (41834686720, 'eb872aebb9d724162d6ace803501fac383c799c4'), 'c08cec7a7dc2b9fe84f9318c81b2874f25ae45fd9126f80e00deee70ee3f4694': (41796544434, '3035b8c9b70af4174fc0e83b9a85f6853a754795')},
    'P04': {
        'c43253a987d6e930f3a60b14e85a52fd0c05f768c6113132d0448d1fc8d99a9a': (41855117019, '375fc428e0b119bc5b705be8f41bed0df7c516b2'),
        'd3840804886e14e60bb193b8123b29c282be82ca049e18107b33423a7b210521': (41839831877, '3d9d0d4b8b96f7d5b5e3c667a35d6ece77ac1e16'),
        'dfcd3aee60ebd3ea7fdc073454af662170a14960f9b034cae6177431ea6c8e2c': (41827835979, '08382e11758c1813f5d40747108564064638cbbb'),
        '58036453b01d009fc05f3626e735bc16c0bd1787f2ca951aeeb936ac57a4da45': (41789942448, '1a4773b535f6aa2e9ab6e49adcfb247f062d4e52'),
        '11c64d8c83d26c8e381ddc4e306829e896f3996c423c394d50c5b2d2d0307492': (41754595229, 'cec7f49da4edf5ca4dd760e3b593451624c1d063'),
        '7177334f71ec924d37810189a9c8f94e6f00073f5808a3aa1ec4647801a51986': (41776035604, 'e5bc98c38b4b1983de82ff30dc77711f7f9cc31c'),
        'c0e9c671daa7a620f8d0fede0ba548a6edf5d669da99a083a7df65aebd301156': (41769843340, 'eb7d24f2466498062d0b32054ab086fc3d243253'),
    },
    'P07': {'d9c73a5ceebdc806feeae4338034626c0c3b4aef42309f3849d69c20cfbf8f7b': (42178048589, '5c22eb3ea156cabcbb723a3ddc67d680d3128bc0'), '475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d': (42109777144, 'b195f9c17a02d2fa154126d046f3a4eeffaea490'), '75e0e1cfee3007e1ff47a638e62597ed49820c1ecc8a7c1cfc7675c9db800719': (42078149007, '554095dbe35cc76d114cc6b6fce20c63dd99a8d8'), '532e1e4ca1317d3631235cb0316860112a355ab1b4cf4f61704f5583245540fd': (41989856333, 'c7021b1731f7e643ff01958b618176ddb709d674'), 'ad8b330eaed295dac664c4ea7392e8eb38956cb78765f51a2f4e05d6515a1c95': (41975953317, '0991526a6db5d32d41359994e85f3c5740449e8b'), '3cbfc7cce74b9c9401b4ca06ca685f7fc1b2fd19e4a6ae16fc4829c4d6ba1ec0': (41975953317, '0991526a6db5d32d41359994e85f3c5740449e8b'), '9524b5ab97174248bd1171b00b6e5ac667546171f176a1d2b87ecd4f8cea23b4': (41960544108, 'ff5f0b2721802b8fb61b9966e1c267ec06c7aba5'), '99c02d182abd329b1e94bde8a8ec1d1ad2f7a9883220fb2e79a9e9766f96300b': (41933809866, '04432f8e604d7313cf0a618d7118be1a973d9473'), '8b3bbe1f16e0daa175d031ca9a95fab95755dea50b33b66c36061af4ba77a998': (41894539616, '08ba5f1e1f8f114d81d5d94016242da163921725'),
        '672a0a0a7560d1b3d4658e6c0e79c3f4259391ac4a7f2d3ecb58e505f5132ef3': (41889291908, 'b5a640008abec4ae92f53ee556d9bf571219ec08'),
        'f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776': (41852967218, '5b12190964523b300bc587a811a18076124ace22'),
        '2293655ea9e4c520c66e016a33c9d33b78f12ceb09c50a371bc84b76c0eef543': (41825451226, '0f026df6b4358280479417857bf0521f5cd2685b'),
        '30552e338938b213e0dcfe5ef06ca6defcca8d0627126cf39cfd63b2982c9e03': (41819198754, 'b190e5f67b7f3ef24eeb7d6f7631b2c97b010c87'),
        '46fd68cb0d747c8c5ca004e979f49f89c02d505ef69069af7e086bd18b18268d': (41787444086, 'b089f323d9537e34011325a2884d9ad44555db1c'),
        '760e41a64a8e2fdf497c96919a5aef9eaa34a9faddee26bc9b5cee843b2ab8fa': (41754595229, 'cec7f49da4edf5ca4dd760e3b593451624c1d063'),
        'c3b3695de955721404aa8b1eb04f2f272efa4f3bd01c8bdd5fac10b92995811c': (41769843340, 'eb7d24f2466498062d0b32054ab086fc3d243253'),
    },
    'P10': {
        '3e73749345802edc681eb20d1adbaf741bebab3df9ea7bcc7ff4ac453a50b0e9': (41795159693, '03aa7a123ad3d34ddcc07ce348e32357b43c7f89'),
        '4560175cf063336c5e192a4ffed31c90914e354b30c1d8c806b8dbee47c0ade7': (41779617448, 'db16788d7f7eecd65e87cc9283e5b0110beee48f'),
        'b98f7dcd4a9a9cff118c53c290cf68794e30b49c2b0e1ca06fd77b3c8bd5b1b9': (41769843340, 'eb7d24f2466498062d0b32054ab086fc3d243253'),
        'c3e9784fdaee742284dc4f7d90aaecbcb541cb50f699dabbb17e8c250f68815c': (41754595229, 'cec7f49da4edf5ca4dd760e3b593451624c1d063'),
    },
}



ADMISSION_CLOCKS['P07']['6abf375981b345fcdfebc5db1f68664a1f401783a7e13f6a3cf2e9c8bd6a2a22'] = ADMISSION_CLOCKS['P07']['9524b5ab97174248bd1171b00b6e5ac667546171f176a1d2b87ecd4f8cea23b4']


def authorized_spec(entry, arm):
    """Separate root continuation authority from immutable transport provenance."""
    a, t = entry['admission'], entry['transport']
    raw = (json.dumps(a, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    need(arm in ADMISSIONS and sha(raw) == entry['admission_sha256']
         and entry['admission_sha256'] in ADMISSION_CLOCKS[arm],
         'FINANCIAL_EXACT_ROOT_ADMISSION_BYTES')
    readonly_run, readonly_head = ADMISSION_CLOCKS[arm][entry['admission_sha256']]
    need(a['schema'] == 'research.root-financial-continuation-admission/1'
         and a['status'] == 'ADMITTED_EXACT_FINANCIAL_CONTINUATION_CHECKPOINT'
         and a['arm'] == t['arm'] == arm and a['financial_continuation_authorized'] is True
         and a['full_financial_validation_completed'] is a['performance_scoring_authorized'] is False
         and a['all_new_cash_shares_receivables_and_raw_marks_verified'] is True
         and a['all_new_funded_factors_and_financial_chains_verified'] is True
         and a['all_new_monthly_and_retry_state_verified'] is True
         and a['financial_source_epoch_unchanged'] is a['input_adoptions_fully_state_neutral'] is True
         and a['production_contacted'] is a['local_canonical_runtime_executed'] is False
         and a['readonly_run_id'] == readonly_run and a['readonly_head'] == readonly_head
         and t['archive_format'] in (FORMAT, FRESH_FORMAT)
         and t['financial_authority'] is t['financial_predecessor_admitted'] is False,
         'FINANCIAL_ONLY_SEPARATE_ROOT_CONTINUATION_AUTHORITY')
    if t['archive_format'] == FRESH_FORMAT:
        initial_reporting_seed(t)
        need(arm == 'P00' and a['initial_empty_origin_verified'] is True
             and a['historical_p00_state_or_returns_reused'] is False
             and a['initial_formation_records'] == 126 and a['new_daily_records'] == 169
             and a['parent_root_admission_sha256'] is None
             and a['fresh_empty_origin_proof_sha256'] == t['public_members']['fresh-origin-admission-P00.json']['sha256'],
             'FINANCIAL_ONLY_EXACT_NEW_FRESH_P00_ORIGIN_ADMISSION')
    for key in ('base', 'journals', 'repairs', 'selected_checkpoint', 'selected_file',
                'outer_sha256', 'inner_sha256', 'state_sha256', 'input_sha256', 'source_binding_sha256'):
        need(a[key] == t[key], 'FINANCIAL_EXACT_ADMITTED_OWN_' + key.upper())
    need(a['completed'] == t['measured_closes'] and a['source_cursor'] == t['selected_session']
         and a['financial_artifact_id'] == t['artifact_id'] and a['financial_run_id'] == t['run_id']
         and a['financial_head'] == t['head'] and a['financial_zip_sha256'] == t['zip_sha256']
         and a['financial_cipher_sha256'] == t['encrypted_output']['sha256'],
         'FINANCIAL_EXACT_CLOSED_TRANSPORT_AND_AXIS')
    return dict(deepcopy(t), root_admission=deepcopy(a), root_admission_sha256=entry['admission_sha256'])


def root_spec(arm, admission_sha256=None):
    bundle = json.loads((HERE / ROOTS).read_bytes())
    need(bundle['schema'] == 'research.root-admitted-financial-parents/1'
         and bundle['full_financial_validation_completed'] is False, 'FINANCIAL_ROOT_BUNDLE_SCOPE')
    need(arm in ADMISSIONS, 'FINANCIAL_EXACT_ADMITTED_ARM')
    selected = ADMISSIONS[arm] if admission_sha256 is None else admission_sha256
    need(selected in ADMISSION_CLOCKS[arm], 'FINANCIAL_EXACT_HISTORICAL_ROOT_SELECTION')
    entry = bundle['arms'][arm] if selected == ADMISSIONS[arm] else bundle['historical_roots'][selected]
    need(entry['admission_sha256'] == selected, 'FINANCIAL_EXACT_SELECTED_ROOT_HASH')
    return authorized_spec(entry, arm)


def completed_result(arm):
    """Read exact completed research scoring authority, never continuation authority."""
    entry = json.loads((HERE / ROOTS).read_bytes())['completed_financial_roots'][arm]
    return authorized_completion(entry, arm)


def authorized_completion(entry, arm):
    a, t = entry['admission'], entry['transport']
    raw = (json.dumps(a, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    need(arm in COMPLETED_ADMISSIONS and sha(raw) == entry['admission_sha256'] == COMPLETED_ADMISSIONS[arm],
         'FINANCIAL_EXACT_COMPLETED_RESEARCH_ADMISSION_BYTES')
    need(a['schema'] == 'research.root-completed-financial-result-admission/1'
         and a['status'] == 'ADMITTED_COMPLETE_FINANCIAL_RESEARCH_RESULT' and a['arm'] == t['arm'] == arm
         and a['full_financial_validation_completed'] is a['performance_scoring_authorized'] is True
         and a['financial_continuation_authorized'] is False and full_target(t)
         and a['completed'] == t['measured_closes'] == 2156
         and a['source_cursor'] == t['selected_session'] == '2026-07-31'
         and a['parent_root_admission_sha256'] == t['monthly_seed_root_admission_sha256'] == ADMISSIONS[arm]
         and (a['readonly_run_id'], a['readonly_head'], a['readonly_artifact_id']) ==
             COMPLETION_METADATA[arm][0]
         and all(a[k] is True for k in ('all_new_cash_shares_receivables_and_raw_marks_verified',
             'all_new_funded_factors_and_financial_chains_verified', 'all_new_monthly_and_retry_state_verified',
             'financial_source_epoch_unchanged', 'input_adoptions_fully_state_neutral', 'empty_uncommitted_tails_verified'))
         and a['production_contacted'] is a['local_canonical_runtime_executed'] is False
         and (a['new_daily_records'], a['independent_accounting_snapshots'], a['new_monthly_reports'], a['total_monthly_reports'])
             == COMPLETION_METADATA[arm][1], 'FINANCIAL_COMPLETE_RESEARCH_SCORING_ONLY_SCOPE')
    for key in ('base', 'journals', 'repairs', 'selected_checkpoint', 'selected_file', 'outer_sha256',
                'inner_sha256', 'state_sha256', 'input_sha256', 'source_binding_sha256'):
        need(a[key] == t[key], 'FINANCIAL_COMPLETED_EXACT_OWN_' + key.upper())
    need(a['financial_artifact_id'] == t['artifact_id'] and a['financial_run_id'] == t['run_id']
         and a['financial_head'] == t['head'] and a['financial_zip_sha256'] == t['zip_sha256']
         and a['financial_cipher_sha256'] == t['encrypted_output']['sha256'],
         'FINANCIAL_COMPLETED_EXACT_TRANSPORT_PROVENANCE')
    return deepcopy(a)


def validate_root_spec(spec):
    transport = {k: v for k, v in spec.items() if k not in ('root_admission', 'root_admission_sha256')}
    need(authorized_spec(dict(transport=transport, admission=spec['root_admission'],
         admission_sha256=spec['root_admission_sha256']), spec['arm']) == spec,
         'FINANCIAL_EXACT_ROOT_SPEC')


def reporting_seed(spec):
    """Select an independently admitted own seed, never arbitrary newer state."""
    if spec.get('initial_prefix_reporting') is not None:
        return initial_prefix_seed(spec)
    if spec.get('archive_format') == FRESH_FORMAT:
        return initial_reporting_seed(spec)
    if 'monthly_seed_root_admission_sha256' in spec:
        original = root_spec(spec['arm'], spec['monthly_seed_root_admission_sha256'])
        need(spec['monthly_seed_root_admission_sha256'] == original['root_admission_sha256'],
             'PARTIAL_EXACT_MONTHLY_ROOT_ADMISSION')
    else:
        original = json.loads((HERE / ORIGINALS).read_bytes())['arms'][spec['arm']]
    need(original['arm'] == spec['arm'] and original['base'] == spec['base']
         and original['measured_closes'] < spec['measured_closes']
         and original['selected_session'] < spec['selected_session'], 'PARTIAL_OWN_EARLIER_MONTHLY_SOURCE_SEED')
    return original


def initial_prefix_seed(spec):
    """Reporting only for exact existing own prefixes on their declared axes."""
    need(spec.get('arm') in INITIAL_PREFIX_TARGETS
         and digest(spec) == INITIAL_PREFIX_TARGETS[spec['arm']],
         'PARTIAL_EXACT_EXISTING_INITIAL_PREFIX_TARGET')
    seed = spec['initial_monthly_seed']
    need(spec['initial_prefix_reporting'] is True and spec['archive_format'] == FORMAT
         and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
         and (spec['measured_closes'], spec['selected_session']) == INITIAL_PREFIX_AXES[spec['arm']]
         and seed['arm'] == spec['arm'] and seed['measured_closes'] == 0
         and seed['selected_session'] == '2017-06-30'
         and all(seed['journals'][n]['bytes'] == 0 for n in ('daily', 'monthly')),
         'PARTIAL_ONLY_ORIGINAL_ZERO_MEASUREMENT_REPORTING_SEED')
    return dict(deepcopy(seed), base=deepcopy(spec['base']))


def initial_reporting_seed(spec):
    """This grants only reporting review of the one genuine fresh export."""
    if 'root_admission' in spec:
        validate_root_spec(spec)
        spec = {k: v for k, v in spec.items() if k not in ('root_admission', 'root_admission_sha256')}
    need(digest(spec) == FRESH_TARGET_SHA and spec['archive_format'] == FRESH_FORMAT
         and spec['arm'] == 'P00' and spec['measured_closes'] == 169
         and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False,
         'PARTIAL_EXACT_FRESH_INITIAL_REPORTING_TARGET')
    return dict(deepcopy(spec['initial_monthly_seed']), base=deepcopy(spec['base']))


def review_name(spec):
    need(spec['archive_format'] in (FORMAT, FRESH_FORMAT), 'PARTIAL_DECLARED_ARCHIVE_FORMAT')
    return 'core-review.json' if spec['archive_format'] == FRESH_FORMAT else 'stopped-review/core-review.json'


def retained_models(root, parent, spec):
    from system_campaign_financial_additional_sensor import selected_declaration
    if selected_declaration(root, parent, spec) is not None:
        from system_campaign_ordinary_augmentation_router import retained_models as additional
        return additional(root, parent, spec)
    schemas = [json.loads((Path(root) / 'book/repairs' / d['filename']).read_bytes())['schema']
               for d in parent['repairs']]
    declared = spec.get('retained_uncertainty_model')
    if declared is None:
        return all(s == 'terminal-repair/1' for s in schemas)
    from system_campaign_financial_branches import INPUT, validate_input
    from system_campaign_financial_uncertainty import retained_model_scope
    need((spec['arm'] == 'P07' or retained_model_scope(root, parent, spec)) and declared == INPUT and schemas.count(INPUT) == 1
         and all(s in ('terminal-repair/1', INPUT) for s in schemas), 'PARTIAL_ONLY_EXACT_SELECTED_RETAINED_MODEL')
    validate_input(Path(root), parent)
    return True


def activate_retained_projection(root, parent, projection):
    """Parse the original committed activation before resolving its branch owner."""
    from system_campaign_financial_projection import OwnProjection, branch_loader_owner
    if not isinstance(projection, OwnProjection):
        return None
    root = Path(root)
    found = [d for d in parent['repairs'] if d['sha256'] == projection.activation_sha]
    need(len(found) == 1, 'PARTIAL_ONE_EXACT_RETAINED_PROJECTION_ACTIVATION')
    entry = found[0]
    path = root / 'book/repairs' / entry['filename']
    need(entry['filename'] == entry['sha256'] + '.json'
         and sha(path.read_bytes()) == entry['sha256']
         and path.read_bytes() == projection.overlay_raw
         and parent['base'] == projection.cp['base']
         and parent['source_cursor'] >= projection.cp['source_cursor']
         and entry['resume_session'] == projection.cp['source_cursor']
         and entry['predecessor_checkpoint_sha256'] == projection.cp['run']['checkpoint_sha256'],
         'PARTIAL_RETAINED_PROJECTION_EXACT_BYTES_GENERATION_AND_ORIGINAL_CLOCK')
    backtest = projection.backtest
    need(getattr(backtest.load_repair, '__self__', None) is projection,
         'PARTIAL_RETAINED_PROJECTION_ACTUAL_INSTALLED_LOADER')
    loaded = backtest.load_repair(path, resume_session=entry['resume_session'],
        predecessor_checkpoint_sha256=entry['predecessor_checkpoint_sha256'])
    need(loaded.sha256 == entry['sha256'] and loaded._resume_session == entry['resume_session']
         and loaded.predecessor_checkpoint_sha256 == entry['predecessor_checkpoint_sha256'],
         'PARTIAL_RETAINED_PROJECTION_ACTUAL_LOADED_OBJECT_ORIGINAL_CLOCK')
    owner = branch_loader_owner(backtest.load_repair)
    need(owner is not None and owner is getattr(projection.original_load, '__self__', None),
         'PARTIAL_RETAINED_PROJECTION_ORIGINAL_ACTIVE_BRANCH_OWNER')
    return loaded


@contextmanager
def model_context(root, parent, spec):
    from system_campaign_financial_additional_sensor import selected_declaration
    if selected_declaration(root, parent, spec) is not None:
        from system_campaign_ordinary_augmentation_router import original_chain
        with original_chain(root, parent, spec):
            yield
        return
    with ExitStack() as stack:
        if spec.get('retained_uncertainty_model') is not None:
            from system_campaign_financial_branches import Codec, evidence
            stack.enter_context(Codec(evidence(Path(root))))
        if spec.get('arm') == 'P07':
            from system_campaign_financial_projection import retained_context
            projection = stack.enter_context(retained_context(root, parent))
            activate_retained_projection(root, parent, projection)
        yield


def retention_tree():
    """Retain every frozen retainer statement except two declared codec sites."""
    import system_campaign_parallel_discovery_run as original
    raw = Path(original.__file__).read_bytes()
    request = json.loads((HERE / 'system-campaign-parallel-discovery-request-001.json').read_bytes())
    need(sha(raw) == request['sources']['system_campaign_parallel_discovery_run.py'],
         'PARTIAL_UNCHANGED_FROZEN_INPUT_RETAINER')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'retained_inputs']

    class SelectedModel(ast.NodeTransformer):
        guard = codec = 0

        def visit_Expr(self, node):
            if (isinstance(node.value, ast.Call) and any(isinstance(a, ast.Constant)
                    and a.value == 'PARALLEL_NO_UNSELECTED_CONDITIONAL_INPUT_MODELS' for a in node.value.args)):
                self.guard += 1
                node.value.args[0] = ast.parse('retained_models(root, parent, selected_spec)', mode='eval').body
                return node
            if isinstance(node.value, ast.Yield):
                self.codec += 1
                return [ast.parse('stack.enter_context(model_context(root, parent, selected_spec))').body[0], node]
            return self.generic_visit(node)

    adapter = SelectedModel()
    fn = adapter.visit(fn)
    need(adapter.guard == adapter.codec == 1, 'PARTIAL_EXACT_TWO_RETAINED_MODEL_SITES')
    return ast.fix_missing_locations(fn)


@contextmanager
def financial_inputs(root, parent, output, spec):
    from system_campaign_ordinary_augmentation_router import preserve as preserve_additional
    preserve_additional(root, parent, output, spec)
    from system_campaign_financial_compound_dispatch import retained_context as compound_retained_context
    with compound_retained_context(root, parent, output):
        import system_campaign_parallel_discovery_run as original
        if spec.get('retained_uncertainty_model') is None:
            with original.retained_inputs(root, parent, output):
                from system_campaign_retained_cash_v2 import context as retained_cash_context
                with retained_cash_context(root, parent, output, spec):
                    yield
            return
        from system_campaign_financial_projection import preserve
        preserve(root, parent, output)
        fn = retention_tree()
        namespace = dict(vars(original), retained_models=retained_models, model_context=model_context, selected_spec=spec)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<source-bound-financial-input-retainer>', 'exec'), namespace)
        with namespace['retained_inputs'](root, parent, output):
            yield


def public_names(spec, archive):
    """This runs before GCM in the unchanged reader; public bytes are pinned."""
    if spec['archive_format'] == FRESH_FORMAT:
        return fresh_public_names(spec, archive)
    names = archive.namelist()
    public = spec['public_members']
    need(len(names) == len(set(names)) == 5 and len(public) == 4
         and set(public) == {spec['receipt_name'], 'full-core-staging.json',
             'ephemeral-runner-capacity.json', 'resume-export-qualification-' + spec['arm'] + '.json'}
         and set(names) == set(public) | {spec['encrypted_output']['name']},
         'PARTIAL_EXACT_FIVE_UNIQUE_ZIP_MEMBERS')
    for name, expected in public.items():
        need(archive.getinfo(name).file_size == expected['bytes'] < 2 * 1024**2,
             'PARTIAL_PUBLIC_MEMBER_BOUND')
        raw = archive.read(name)
        need(dict(bytes=len(raw), sha256=sha(raw)) == expected, 'PARTIAL_EXACT_PUBLIC_BYTES')
    receipt = json.loads(archive.read(spec['receipt_name']))
    status = ('COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT' if full_target(spec)
              else 'PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT')
    need(receipt['status'] == spec['receipt_status'] == status
         and receipt['performance_admitted'] is False
         and {k: receipt[k] for k in spec['prior_stops']} == spec['prior_stops'],
         'PARTIAL_ACTUAL_PRIOR_STATUS_AND_STOPS')
    marker = json.loads(archive.read('resume-export-qualification-' + spec['arm'] + '.json'))
    need(marker == dict(status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED',
         arm=spec['arm'], financial_sessions_advanced=0, credentials_saved=False),
         'PARTIAL_ACTUAL_EXPORT_PROBE')
    staging = json.loads(archive.read('full-core-staging.json'))
    need(staging['status'] == 'STAGING_PASSED' and staging['run_id'] == str(spec['run_id'])
         and staging['source_commit'] == spec['head'] and staging['protocol_sha256'] == PROTOCOL
         and staging['runtime_image'] == IMAGE and staging['execution_image'] == EXECUTION_IMAGE
         and staging['source_files_verified'] == 514 and staging['members_verified'] == 591
         and staging['authenticated_before_parsing'] is True and staging['offline_image_source_verified'] is True
         and staging['runtime_index_config_layer_chain_verified'] is True and staging['replay_started'] is False,
         'PARTIAL_ACTUAL_FROZEN_STAGING')
    return set(public) | {spec['encrypted_output']['name']}


def full_target(spec):
    """An explicit complete transport is reporting evidence, never a resume seed."""
    if 'readonly_full_financial_target' not in spec:
        return False
    need(spec['readonly_full_financial_target'] is True and spec['archive_format'] == FORMAT
         and spec['measured_closes'] == 2156 and spec['selected_session'] == '2026-07-31'
         and spec['receipt_status'] == 'COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'
         and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
         and all(spec['prior_stops'][role]['stopped'] is True
                 and type(spec['prior_stops'][role]['exit_code']) is int
                 and spec['prior_stops'][role]['exit_code'] == 0
                 and spec['prior_stops'][role]['oom_killed'] is False
                 for role in ('preflight', 'worker', 'reviewer')),
         'PARTIAL_ONLY_EXPLICIT_SUCCESSFUL_COMPLETE_READONLY_TARGET')
    return True


def fresh_public_names(spec, archive):
    initial_reporting_seed(spec)
    names, public = archive.namelist(), spec['public_members']
    need(len(names) == len(set(names)) == 6 and len(public) == 5
         and set(public) == {spec['receipt_name'], 'full-core-staging.json',
             'ephemeral-runner-capacity.json', 'fresh-origin-admission-P00.json',
             'fresh-origin-export-qualification-P00.json'}
         and set(names) == set(public) | {spec['encrypted_output']['name']},
         'PARTIAL_EXACT_SIX_UNIQUE_FRESH_MEMBERS')
    for name, expected in public.items():
        need(archive.getinfo(name).file_size == expected['bytes'] < 2 * 1024**2,
             'PARTIAL_PUBLIC_MEMBER_BOUND')
        raw = archive.read(name)
        need(dict(bytes=len(raw), sha256=sha(raw)) == expected, 'PARTIAL_EXACT_PUBLIC_BYTES')
    raw = (HERE / FRESH_REQUEST).read_bytes()
    need(sha(raw) == FRESH_REQUEST_SHA and dict(bytes=len(raw), sha256=sha(raw)) == spec['fresh_request_member'],
         'PARTIAL_DISTINCT_CLOSED_FRESH_REQUEST_BYTES')
    fresh = json.loads(raw)
    import system_campaign_candidate_job as candidate
    original = candidate.expected_request()
    need(fresh['arm'] == 'P00' and fresh['index'] == 0 and fresh['fresh_origin'] is True
         and fresh['parameters'] == original['initial_candidates'][0]['parameters']
         and fresh['candidate_id'] == original['initial_candidates'][0]['id']
         and fresh['original_candidate_request_sha256'] == spec['request_sha256']
         and fresh['inherited_financial_rows'] == 0
         and fresh['prior_checkpoint_imported'] is fresh['historical_result_reused'] is False,
         'PARTIAL_ONLY_CLOSED_EMPTY_P00_ORIGIN')
    proof = json.loads(archive.read('fresh-origin-admission-P00.json'))
    need(proof == spec['fresh_origin_admission'] and proof['request_sha256'] == sha(raw)
         and proof['previous_book_selected'] is proof['financial_runtime_executed'] is False
         and proof['old_p00_performance_is_not_completion_authority'] is True,
         'PARTIAL_REUSE_EXACT_CLOSED_FRESH_ORIGIN_PROOF')
    receipt = json.loads(archive.read(spec['receipt_name']))
    need(receipt['status'] == spec['receipt_status'] == 'PARTIAL_CANDIDATE_PREFIX_REVIEWED'
         and receipt['candidate_id'] == fresh['candidate_id'] and receipt['performance_admitted'] is False
         and {k: receipt[k] for k in spec['prior_stops']} == spec['prior_stops']
         and all(receipt[k]['stopped'] is True and type(receipt[k]['exit_code']) is int
                 and receipt[k]['oom_killed'] is False for k in ('worker', 'reviewer'))
         and receipt['reviewer']['exit_code'] == 0,
         'PARTIAL_ACTUAL_FRESH_STATUS_AND_STOPS')
    need(json.loads(archive.read('fresh-origin-export-qualification-P00.json')) == dict(
         status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED', arm='P00',
         financial_sessions_advanced=0, credentials_saved=False), 'PARTIAL_ACTUAL_FRESH_EXPORT_PROBE')
    staging = json.loads(archive.read('full-core-staging.json'))
    need(staging['status'] == 'STAGING_PASSED' and staging['run_id'] == str(spec['run_id'])
         and staging['source_commit'] == spec['head'] and staging['protocol_sha256'] == PROTOCOL
         and staging['runtime_image'] == IMAGE and staging['execution_image'] == EXECUTION_IMAGE
         and staging['source_files_verified'] == 514 and staging['members_verified'] == 591
         and staging['manifest_sha256'] == fresh['frozen_input_manifest_sha256']
         and all(staging[k] is True for k in ('authenticated_before_parsing', 'offline_image_source_verified',
                                             'runtime_index_config_layer_chain_verified'))
         and staging['replay_started'] is False, 'PARTIAL_ACTUAL_FROZEN_FRESH_STAGING')
    return set(names)


def admission_tree(review_file='stopped-review/core-review.json'):
    """Adapt exactly two format sites; retain every original authentication guard."""
    raw = Path(crypto.__file__).read_bytes()
    need(sha(raw) == CRYPTO_SHA, 'PARTIAL_UNCHANGED_ORIGINAL_CRYPTO_SOURCE')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'admit']

    class Format(ast.NodeTransformer):
        members = review = 0

        def visit_Set(self, node):
            if ast.unparse(node) == "{spec['receipt_name'], 'full-core-staging.json', asset['name']}":
                self.members += 1
                return ast.copy_location(ast.parse('public_names(spec, z)', mode='eval').body, node)
            return self.generic_visit(node)

        def visit_BinOp(self, node):
            if ast.unparse(node) == "dest / 'core-review.json'":
                self.review += 1
                return ast.copy_location(ast.BinOp(left=ast.Name(id='dest', ctx=ast.Load()),
                    op=ast.Div(), right=ast.Constant(review_file)), node)
            return self.generic_visit(node)

    adapter = Format()
    fn = adapter.visit(fn)
    need(adapter.members == adapter.review == 1, 'PARTIAL_EXACTLY_TWO_FORMAT_SITES')
    return ast.fix_missing_locations(fn)


def reviewed_archive_limit(spec):
    """Select an existing crypto size option for one source-qualified transport."""
    clock=(spec.get('arm'),spec.get('run_id'),spec.get('head'),spec.get('artifact_id'),spec.get('zip_sha256'))
    if clock!=('P07',42100223336,'e66f23919cdb17da52707c0c3e10abf9d531e3e2',13451345162,
               '6113900f2daf3320954dd042b51c78057c0e98abfea51270284b5705eac47c12'):
        return 512*1024**2
    need(type(spec['zip_bytes']) is int and spec['zip_bytes']==576040524
         and spec['manifest']==dict(member_count=545,raw_member_bytes=731251188)
         and all(type(v) is int for v in spec['manifest'].values())
         and spec['selected_checkpoint']=='book/checkpoint.json.gz'
         and spec['selected_file']==dict(bytes=1197812,sha256='76df216faf4060c1f96d8fc9833bfc1681303c0dcfe19e2322e326fada42d43a')
         and spec['outer_sha256']=='efc954aafff81ce10213b5a6ec62f765b7120734a076459e0b04d9b468ed6277'
         and type(spec['measured_closes']) is int and spec['measured_closes']==1238
         and spec['selected_session']=='2022-11-30',
         'PARTIAL_EXACT_QUALIFIED_ONE_GIB_ARCHIVE_COMMITMENTS')
    need(spec['archive_format']==FORMAT and spec['financial_authority'] is False
         and spec['financial_predecessor_admitted'] is False
         and spec['receipt_status']=='PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'
         and set(spec['prior_stops'])=={'preflight','worker','reviewer'}
         and all(spec['prior_stops'][role]['stopped'] is True
                 and type(spec['prior_stops'][role]['exit_code']) is int
                 and spec['prior_stops'][role]['exit_code']==code
                 and spec['prior_stops'][role]['oom_killed'] is False
                 for role,code in (('preflight',0),('worker',1),('reviewer',0))),
         'PARTIAL_QUALIFIED_ONE_GIB_POSITIVE_REVIEW_AND_STOP_SCOPE')
    return 1024**3


def admit(spec, root, key, inspector):
    from system_campaign_financial_requalified_parent import applies as requalified, admit as requalified_admit
    if requalified(spec):
        return requalified_admit(spec, root, key, inspector)
    from system_campaign_financial_review_repair import applies, admit as repair_admit
    if applies(spec):
        return repair_admit(spec, root, key, inspector)
    need(spec['archive_format'] in (FORMAT, FRESH_FORMAT) and spec['financial_authority'] is False
         and spec['financial_predecessor_admitted'] is False
         and spec['manifest']['raw_member_bytes'] < 1024**3,
         'PARTIAL_READONLY_UNADMITTED_TARGET_SCOPE')
    namespace = dict(vars(crypto), public_names=public_names)
    fn = admission_tree(review_name(spec))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<source-bound-financial-format-adapter>', 'exec'), namespace)
    destination = namespace['admit'](spec, root, key, max_zip_bytes=reviewed_archive_limit(spec))
    for name, expected in spec['inspections'].items():
        value = json.loads((destination / name).read_bytes())
        need(re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', expected['user']) is not None,
             'PARTIAL_POSITIVE_ORIGINAL_UID_GID')
        archived_inspection(spec, expected, value, inspector)
        state = value['State']
        need(state['Running'] is False and state['OOMKilled'] is False
             and type(state['ExitCode']) is int and state['ExitCode'] == expected['exit_code'],
             'PARTIAL_ACTUAL_ARCHIVED_POSITIVE_STOP')
    review = json.loads((destination / review_name(spec)).read_bytes())
    need(review['all_prefixes_verified'] is True and review['all_daily_factors_and_chains_verified'] is True
         and review['checkpoint_sha256'] == spec['outer_sha256']
         and review['counts'] == dict(formation=126, daily=spec['measured_closes']),
         'PARTIAL_ORIGINAL_FULL_PREFIX_REVIEW')
    if full_target(spec):
        need(review['complete'] is True and review['monthly_metrics'] == 103
             and all(v == dict(bytes=0, sha256=sha(b'')) for v in review['preserved_tails'].values())
             and set(review['preserved_tails']) == {'formation', 'daily', 'monthly', 'watch'},
             'PARTIAL_COMPLETE_ENDPOINT_AND_EMPTY_TAILS')
    raw = (destination / 'request.json').read_bytes()
    need(dict(bytes=len(raw), sha256=sha(raw)) == spec['original_request_member']
         and sha(raw) == spec['request_sha256'], 'PARTIAL_ORIGINAL_REQUEST_MEMBER')
    from ephemeral_runner_capacity import validate_prepared_receipt
    with zipfile.ZipFile(destination.parent / 'predecessor.zip') as archive:
        capacity = json.loads(archive.read('ephemeral-runner-capacity.json'))
    capacity_sources = (json.loads((HERE / FRESH_REQUEST).read_bytes()) if spec['archive_format'] == FRESH_FORMAT
                        else json.loads(raw))['sources']
    validate_prepared_receipt(capacity, head=spec['head'], run_id=str(spec['run_id']),
        source_sha256=capacity_sources['ephemeral_runner_capacity.py'])
    return destination


def archived_inspection(spec, expected, value, inspector):
    if spec['archive_format'] == FORMAT:
        return inspector(expected['name'].removeprefix('/'), expected['id'], value=value,
            run_id=str(spec['run_id']), user=expected['user'],
            correlation_prefix=expected['correlation_prefix_mounted'])
    initial_reporting_seed(spec)
    import system_campaign_candidate_job as candidate
    raw = Path(candidate.__file__).read_bytes()
    fresh = json.loads((HERE / FRESH_REQUEST).read_bytes())
    need(sha(raw) == fresh['sources']['system_campaign_candidate_job.py'], 'PARTIAL_ORIGINAL_CANDIDATE_INSPECTOR')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'inspect']
    assignment, = [n for n in fn.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'v' for t in n.targets)]
    assignment.value = ast.Name(id='supplied', ctx=ast.Load())
    uid, gid = map(int, expected['user'].split(':'))
    ns = dict(vars(candidate), supplied=value, os=SimpleNamespace(getuid=lambda: uid, getgid=lambda: gid))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<unchanged-candidate-inspector-archived-state>', 'exec'), ns)
    ns['inspect'](expected['name'].removeprefix('/'), expected['id'])
    phase = expected['phase']
    command = ['-B', '-u', '/driver/system_campaign_candidate.py', '--mode', phase]
    if phase == 'review':
        command += ['--evidence-root', '/evidence']
    need(phase in ('economic', 'review') and value['Config']['Entrypoint'] == ['python']
         and value['Config']['Cmd'] == command and value['Config']['User'] == expected['user'],
         'PARTIAL_EXACT_ORIGINAL_CANDIDATE_ENTRYPOINT')
    return value


def reproduce_reports(stats, parent, current, daily, reports, following):
    """Only recorded NAV/report values are ingested; this is not a financial run."""
    need(len(daily) == current['completed'] - parent['completed'] > 0
         and following > current['source_cursor'] == daily[-1]['session'], 'PARTIAL_REPORTING_SUFFIX_AXIS')
    dates = [r['session'] for r in daily] + [following]
    actual = []
    for index, row in enumerate(daily):
        report = stats.advance(row['session'], {k: Decimal(v) for k, v in row['comparison_navs'].items()},
            core_target=str(row['decision']['target_core_exposure']), month_end=dates[index + 1][:7] != row['session'][:7])
        if report:
            actual.append(report)
    stored = deepcopy(reports)
    for report in stored:
        report.pop('slot_retries')
    need(actual == stored and stats.to_dict() == current['stats'],
         'PARTIAL_ALL_NEW_REPORTS_AND_ENTIRE_STATS_EXACT')
    return dict(new_daily_records=len(daily), new_reports=len(reports),
                all_new_monthly_reports_exact=True, all_monthly_checkpoint_state_exact=True)


def reporting_stats(cls, parent, current, spec):
    if parent['stats'] is not None:
        return cls.from_dict(parent['stats'])
    (initial_prefix_seed if spec.get('initial_prefix_reporting') is not None else initial_reporting_seed)(spec)
    required = ('pooled', 'owned55_previous', 'compact_previous', 'spy')
    need(parent['completed'] == 0 and parent['stats'] is None
         and all(parent['journals'][n]['bytes'] == 0 for n in ('daily', 'monthly'))
         and current['base']['start'] == '2018-01-02' and current['base']['capital'] == '50000'
         and current['stats']['primary'] == 'pooled'
         and current['stats']['required_series'] == list(required)
         and set(current['stats']['series']) == set(required)
         and all(v['initial_nav'] == '50000' for v in current['stats']['series'].values()),
         'PARTIAL_ONLY_EXACT_ZERO_MEASUREMENT_REPORTING_BOOTSTRAP')
    return cls.fresh('2018-01-02', {n: '50000' for n in required},
                     primary='pooled', required_series=required)


def monthly_reproduction(evidence, out, spec, current):
    hosted()
    from research.pooled_vacancy_funding.monthly import MonthlyStats
    from research.pooled_input_support.bundle import axis
    need(sha256_file(HERE / ORIGINALS) == spec['original_parent_index_sha256'],
         'PARTIAL_EXACT_RETAINED_ORIGINAL_INDEX')
    original = reporting_seed(spec)
    path = (evidence / original['selected_checkpoint'] if spec['archive_format'] == FRESH_FORMAT
            or spec.get('initial_prefix_reporting') is True
            else evidence / 'book/predecessor-checkpoints' / (original['outer_sha256'] + '.json.gz'))
    raw = path.read_bytes()
    need(dict(bytes=len(raw), sha256=sha(raw)) == original['selected_file'],
         'PARTIAL_EXACT_ORIGINAL_MONTHLY_SEED_GZIP')
    parent = require_strict_checkpoint(json.loads(gzip.decompress(raw)))
    check_parent(parent, original)
    need(parent['base'] == current['base'], 'PARTIAL_SAME_MONTHLY_SOURCE_BASE')

    def rows(name):
        raw = (evidence / 'book' / (name + '.jsonl')).read_bytes()
        before, after = parent['journals'][name], current['journals'][name]
        need(after['bytes'] >= before['bytes'] and sha(raw[:before['bytes']]) == before['prefix_sha256']
             and sha(raw[:after['bytes']]) == after['prefix_sha256'], 'PARTIAL_REPORTING_ORIGINAL_AND_CURRENT_PREFIXES')
        return [json.loads(line) for line in raw[before['bytes']:after['bytes']].splitlines()]

    daily, reports = rows('daily'), rows('monthly')
    measured = [d for d in axis() if '2018-01-02' <= d <= '2026-07-31']
    need(len(measured) == 2156 and measured == sorted(set(measured))
         and measured[parent['completed']:current['completed']] == [r['session'] for r in daily],
         'PARTIAL_EXACT_FROZEN_NEW_REPORTING_AXIS')
    following = measured[current['completed']] if current['completed'] < 2156 else '2026-08-03'
    source = Path('/variant/research/pooled_vacancy_funding/monthly.py')
    need(sha256_file(source) == current['base']['sources']['research/pooled_vacancy_funding/monthly.py'],
         'PARTIAL_ACTUAL_MONTHLY_IMPLEMENTATION_SOURCE')
    with localcontext() as context:
        context.prec = 50
        proof = reproduce_reports(reporting_stats(MonthlyStats, parent, current, spec),
                                  parent, current, daily, reports, following)
    proof.update(schema='research.partial-exact-linux-monthly-reproduction/1', passed=True,
        arm=spec['arm'], parent_sha256=parent['sha256'], checkpoint_sha256=current['sha256'],
        completed=current['completed'], source_cursor=current['source_cursor'], next_session=following,
        monthly_source_sha256=sha256_file(source), complete_stored_reports_sha256=digest(reports),
        entire_monthly_journal_sha256=sha256_file(evidence / 'book/monthly.jsonl'),
        financial_transitions_reexecuted=0, financial_authority=False)
    save(out / 'monthly-reproduction.json', proof)
    return proof
