"""Selected future ordinary facts, with read-only actual cash/risk postconditions."""
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from fractions import Fraction
import inspect
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal
import zipfile

from pydantic import BaseModel, ConfigDict, Field

from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_facts import digest, sha

HERE = Path(__file__).parent
OVERLAY = 'future-financial-overlay.json'
HYDRATED = 'hydrated-future-financial-terminal-catalog.json'
REFERENCE = 'research:system-optimization-002/selected-future-ordinary-input/1'
PLANS = {
    'P04': ('system_campaign_following_completions_facts', 'FollowingFacts',
            'system-campaign-following-completions-terminal-facts.json', ('APHA', 'CATM', 'REGI', 'PLAN')),
    'P10': ('system_campaign_autumn2020_cash_facts', 'CashCompletionFacts',
            'system-campaign-autumn2020-cash-terminal-facts.json', ('MNTA', 'AIMT', 'IMMU', 'MYOK', 'VRTU')),
    'P07': ('system_campaign_medicines_facts', 'MedicinesFacts',
            'system-campaign-medicines-terminal-facts.json', ('MDCO',)),
}
CASH_PHASES = {
    ('P11', '2023-02-28'): ('system-campaign-october-cash-calendar-terminal-facts.json',
        ('EVOP', 'SGFY', 'CTIC', 'MGI', 'ISEE', 'UNVR', 'RETA', 'SYNH')),
    ('P11', '2022-01-31'): ('system-campaign-february-cash-calendar-terminal-facts.json', ('VCRA',)),
    ('P04', '2023-01-31'): ('system-campaign-october-cash-calendar-terminal-facts.json',
        ('LHCG', 'EVOP', 'SGFY', 'CTIC', 'MGI', 'ISEE', 'UNVR', 'ONEM', 'COUP', 'RETA', 'SYNH')),
    ('P04', '2022-04-29'): ('system-campaign-december-cash-calendar-terminal-facts.json', ('EPAY',)),
    ('P10', '2022-01-31'): ('system-campaign-february-cash-calendar-terminal-facts.json', ('VCRA',)),
}
CASH_PHASES['P07', '2021-11-30'] = (
    'system-campaign-december-cash-calendar-terminal-facts.json',
    ('COR2', 'DRNA', 'ARNA', 'EPAY', 'CCXI1', 'NEWR', 'IMGN', 'CTLT'))
COMPOSITION = 'research.selected-future-catalog-composition/1'
COMBINED_PHASES = {
    ('P07', '2019-12-31'): (
        PLANS['P07'],
        ('system_campaign_arqule_facts', 'ArQuleFacts', 'system-campaign-arqule-terminal-facts.json', ('ARQL',)),
    ),
}
COMBINED_PHASES['P05', '2019-12-31'] = COMBINED_PHASES['P07', '2019-12-31']
SINGLE_PHASES = {('P07', '2020-02-28'):
    ('system_campaign_sprint_facts', 'SprintFacts', 'system-campaign-sprint-terminal-facts.json', ('S2',))}
FOLLOWING_PHASES = {('P07', '2020-03-31'):
    ('system_campaign_spring2020_cash_facts', 'CashCompletionFacts', 'system-campaign-spring2020-cash-terminal-facts.json', ('CY', 'MLNX', 'WBC'))}
FUTURE_LITERAL_PHASES = {('P07', '2021-01-29'):
    ('system_campaign_following_completions_facts', 'FollowingFacts',
     'system-campaign-following-completions-terminal-facts.json', ('ACIA', 'APHA', 'CATM', 'AZPN1', 'REGI', 'PLAN'))}
FUTURE_LITERAL_PHASES['P07', '2021-03-31'] = (
    'system_campaign_2021_completions_facts', 'CompletionFacts',
    'system-campaign-2021-completions-terminal-facts.json', ('MIK', 'VAR', 'NAV', 'WORK', 'HOME', 'TRIL1'))
FUTURE_LITERAL_PHASES['P05', '2020-12-31'] = (
    'system_campaign_2021_completions_facts', 'CompletionFacts',
    'system-campaign-2021-completions-terminal-facts.json',
    ('WPX', 'BEAT1', 'MIK', 'VAR', 'NAV', 'WORK', 'HOME', 'TRIL1'))
COMBINED_PHASES['P07', '2020-03-31'] = (FOLLOWING_PHASES['P07', '2020-03-31'], PLANS['P10'])
COMBINED_PHASES['P06', '2020-03-31'] = (FOLLOWING_PHASES['P07', '2020-03-31'], PLANS['P10'])
SOURCE_WITNESS_SCHEMA = 'research.own-parent-frozen-source-witnesses/1'
SOURCE_WITNESS_PENDING_SCHEMA = 'research.own-parent-frozen-source-witnesses/2'
SOURCE_WITNESS_DISCOVERY_SCHEMA = 'research.own-parent-frozen-source-witnesses/3'
SOURCE_WITNESS_ROW_QUERY_SCHEMA = 'research.own-parent-frozen-source-witnesses/4'
SOURCE_WITNESS_DATE_QUERY_SCHEMA = 'research.own-parent-frozen-source-witnesses/5'
SOURCE_WITNESS_FILE = 'source-witnesses.json'
OWN_CASH_CATALOG = 'system-campaign-selected-own-cash-terminal-facts.json'
OWN_CASH_SHA = '9ef287a863e6fc5e6e0754ed8fe052b9fdc40a1353a68bf5e55e4398f03558b5'
RETAINED_OWN_CASH_PHASES = {('P11', '2022-07-29'): dict(
    source_arm='P10', source_cursor='2022-07-29', ticker='ACC',
    source_generation_sha256='7b58c64413b5f513ce76b9c7382f34cf8df612969e0865604ba283eb8a464be9',
    parent_root_admission_sha256='a2cd1c0d680f78f93d021de662f6dff7def0cb4add2ed15c28349acc8670f3d2',
    parent_outer_sha256='ee6cdd1bdc992883636495a5c20e1b93371af5e638fa8f553ef55198e9b73814',
    parent_positions=[])}
OWN_CASH_PHASES = {('P03', '2018-08-31'): 'NLST',
 ('P11', '2022-05-31'): 'TVTY',
 ('P03', '2018-04-30'): 'FMSA',
 ('P04', '2022-06-30'): 'SAFM',
 ('P10', '2022-07-29'): 'ACC',
 ('P10', '2024-04-30'): 'SWAV',
 ('P00', '2018-08-31'): 'ILG',
 ('P04', '2022-08-31'): 'CTXS',
 ('P04', '2022-09-30'): 'GBT',
 ('P00', '2025-06-30'): 'TGI',
 ('P07', '2020-06-30'): 'LM',
 ('P05', '2018-01-31'): 'AAAP1',
 ('P06', '2018-01-31'): 'AAAP1',
 ('P11', '2018-01-31'): 'AAAP1',
 ('P04', '2025-10-31'): 'LNWO',
 ('P11', '2018-08-31'): 'EDR1'}
OWN_CASH_PHASES['P05', '2020-01-31'] = 'WLH'
OWN_CASH_PHASES['P03', '2018-11-30'] = 'ARII'
OWN_CASH_PHASES['P05', '2020-06-30'] = 'LM'
OWN_CASH_PHASES['P11', '2023-06-30'] = 'AJRD'
OWN_CASH_PHASES['P03', '2018-12-31'] = 'SEND'
CLOSED_CASH_GENERATIONS = {'332a92d9dbfaea1b9154fbb2c2e0f397dbd5fa96686d148401d3607cce3a6a03': 18, 'c93bb3e00a7990b25fe146ced63407ce582e1da9511c1b94c8039e8e04b90f89': 17, '465c8a78287c5cb7864aa400e13290f07f278c31e2a34897018cf5403551070c': 16, '5c987533c0fdf7ac1a781044bd50f0a4232db2d9cc43d5a403c39a9bfad3b749': 14,
 '1998e26f6dc43f54ec63cff5171989b6b7952948af1b46a6d3c103e325ae004c': 15,
 'ddfb2f16b73dae3b1d4586e11ba3d8ec84365de260fcbc7e9cb9cf21b9481852': 13,
 '7b58c64413b5f513ce76b9c7382f34cf8df612969e0865604ba283eb8a464be9': 2,
 'd2b2ee65c2a029d6bc885a35dcf8138233a23b8654aaf1958a6a2677416605e3': 3,
 '629b3e64ab7cf6aae2cf54c733d65acc8c9cc3b2465d68b19a58b0918a09efe2': 4,
 '5a917388cfa61ed86d60792e263260fca876eaf3d8f3606ad95744d7a5ed7ed7': 5,
 'c3530a81ce5a9ae448f2e1ac59e06c3efbd224b28988fe414f3bd1b04fd47101': 6,
 '4467104fa7d591af78c7665895b453757c04431492c4a805fa6027ae24f27d84': 7,
 '1baf3f3938fa8fa6e31ddd1ca7c264f79f8eae8de8396c2828fdf831c2436915': 8,
 'c2b3d070ba31bd94c947c057f667cca2452ee3ff4875fcd458164b947e5147a2': 11,
 'a312304df09aa19feabce82cce92adc1798a49e104333fc4d7d5cb7ce94af77f': 12}
CLOSED_CASH_GENERATIONS['f7653bb52979ef4129741af32ae48bbd3463925dc26bd8f5f5aad60c1035e530'] = 20
CLOSED_CASH_GENERATIONS['f9f1ee6486767af7597a34be9425b22d6856bc26237255b1465055289494468e'] = 22
CASH_GENERATION_LENGTHS = {('P03', '2018-08-31'): 15,
 ('P11', '2022-05-31'): 16,
 ('P03', '2018-04-30'): 14,
 ('P04', '2022-06-30'): 2,
 ('P10', '2022-07-29'): 2,
 ('P10', '2024-04-30'): 3,
 ('P00', '2018-08-31'): 4,
 ('P04', '2022-08-31'): 5,
 ('P04', '2022-09-30'): 6,
 ('P00', '2025-06-30'): 7,
 ('P07', '2020-06-30'): 8,
 ('P05', '2018-01-31'): 11,
 ('P06', '2018-01-31'): 11,
 ('P11', '2018-01-31'): 11,
 ('P04', '2025-10-31'): 12,
 ('P11', '2018-08-31'): 13}
CASH_GENERATION_LENGTHS['P05', '2020-01-31'] = 17
CASH_GENERATION_LENGTHS['P03', '2018-11-30'] = 18
CASH_GENERATION_LENGTHS['P05', '2020-06-30'] = 19
CASH_GENERATION_LENGTHS['P11', '2023-06-30'] = 20
CASH_GENERATION_LENGTHS['P03', '2018-12-31'] = 21
CLOSED_CASH_GENERATIONS['c2b91afd1a521e14ce0f154b9c43317e6adac4f4a6fc6aca0c1ba42c4ee8889b'] = 21
OWN_CASH_PHASES['P06', '2020-02-28'] = 'WAAS'
OWN_CASH_PHASES['P05', '2020-11-30'] = 'BMCH'
CASH_GENERATION_LENGTHS['P06', '2020-02-28'] = 22
CASH_GENERATION_LENGTHS['P05', '2020-11-30'] = 23
NEXT_COMPLETION = 'FIRST_FROZEN_SESSION_AFTER_CONFIRMED_COMPLETION_DATE'
SOURCE_CLOSE = 'CONFIRMED_COMPLETION_CLOSE_UNOWNED_SOURCE_ONLY'
CLOSED_CASH_GENERATIONS['c5acabb2180a38d530f61d9200fcd3bd730395e6a90c34bd4e331d8dab269516'] = 23
OWN_CASH_PHASES['P03', '2019-05-31'] = 'KEYW'
CASH_GENERATION_LENGTHS['P03', '2019-05-31'] = 24
CLOSED_CASH_GENERATIONS['ad124c0b56755fe08d035d35d6a27665ccd5e2049bd7293cfae2ee6cb4188be7'] = 24
OWN_CASH_PHASES['P06', '2020-06-30'] = 'LM'
CASH_GENERATION_LENGTHS['P06', '2020-06-30'] = 25
CLOSED_CASH_GENERATIONS['712cec77c23fa188787daaf158e4f9d8fa1bbbc5c733537cfcaf9b5c1c17db28'] = 25
OWN_CASH_PHASES['P11', '2025-06-30'] = 'TGI'
CASH_GENERATION_LENGTHS['P11', '2025-06-30'] = 26
CLOSED_CASH_GENERATIONS['677c0bd781406b4fbfb9871ce14707250168526ef9f07162b4bde8c992423cc6'] = 26
OWN_CASH_PHASES['P03', '2019-09-30'] = 'CBLK'
CASH_GENERATION_LENGTHS['P03', '2019-09-30'] = 27
CLOSED_CASH_GENERATIONS['69cace876439b11fd0d9b48f8a6c8faa2ee149be9c6ffaf2e54dda034292feca'] = 27
OWN_CASH_PHASES['P06', '2021-03-31'] = 'IPHI'
CASH_GENERATION_LENGTHS['P06', '2021-03-31'] = 28
CLOSED_CASH_GENERATIONS['b199b6df1b4e34e1b98336795dc3eeb62caa9981f3f9a96b2b1edb1704aa6581'] = 28
OWN_CASH_PHASES['P11', '2026-02-27'] = 'EXAS'
CASH_GENERATION_LENGTHS['P11', '2026-02-27'] = 29
CLOSED_CASH_GENERATIONS['51674fc83cb9240168b27c2566edff62f44089cb4e00e57ce2e8f06b8a50277e'] = 29
OWN_CASH_PHASES['P05', '2021-10-29'] = 'UFS'
CASH_GENERATION_LENGTHS['P05', '2021-10-29'] = 30
RESEARCH_UNHELD_CASH = 'RESEARCH_COMPLETION_DATE_CLOSE_UNOWNED_SOURCE_ONLY'
CLOSED_CASH_GENERATIONS['7e497c722993513994326293e7703abb54161ed952ed0b99e3d8043a51475c9b'] = 31
OWN_CASH_PHASES['P11', '2026-04-30'] = 'TERN'
CASH_GENERATION_LENGTHS['P11', '2026-04-30'] = 32
RESEARCH_CASH = 'RESEARCH_COMPLETION_DATE_OPEN_AVAILABILITY'
RESEARCH_MIXED = 'RESEARCH_DAILY_MIXED_CONSIDERATION_OPEN_AVAILABILITY'
RESEARCH_TENDER = 'RESEARCH_ASSUMED_TENDER_PARTICIPATION'
RESEARCH_SOURCE_EXIT = 'UNHELD_SOURCE_EXIT_AT_LAST_RETAINED_RAW_CLOSE_NOT_STATUTORY_CASH'
PREOPEN_STOCK = 'CONFIRMED_PREOPEN_STOCK_ONLY_COMPLETION'
PRIOR_STOCK = 'FIRST_FROZEN_SESSION_AFTER_CONFIRMED_STOCK_ONLY_COMPLETION'
SOURCE_SCOPES = 'future-source-only-scopes.json'
ORIGINAL_ORDINARY_SOURCES = {
    arm: (('system_campaign_winter_facts', 'WinterCash',
          'system-campaign-corrected-winter-facts.json',
          '9784f96a4037fda8f4494d4d080b2a99e56bb4d4cd7640a52dd9cd9b99e23f4c'),
          ('system_campaign_followup_facts', 'FollowupFacts',
           'system-campaign-followup-terminal-facts.json',
           '046cac14b87a620ac922e6f10a96682943952f9ba7ce3cd2f99a3decffa13222'),
          ('system_campaign_late_facts', 'LateFacts',
           'system-campaign-late-terminal-facts.json',
           '0db4e7eb49ab973bbb6f7bb9579e2a33776b2f7ead3fe25f9cb40812cb3efca7'))
    for arm in ('P05', 'P06', 'P11')
}
ORIGINAL_ORDINARY_PHASES = {('P03', '2019-01-31'): (
    ('system_campaign_early2019_facts', 'Early2019Facts',
     'system-campaign-early2019-terminal-facts.json',
     '740b0e937067d3cf45a371e51cfd02c59821e9fdb5232714d449d302cda6b4ac'),)}
ORIGINAL_DELIVERY_SOURCES = {
    arm: (('system_campaign_midyear_facts', 'MidyearFacts',
           'system-campaign-midyear-terminal-facts.json',
           'f2467de7dd56d1b69bac24be9caeeedd6be946e1e898dce9a9afefe054437018'),
          ('system_campaign_late_facts', 'LateFacts',
           'system-campaign-late-terminal-facts.json',
           '0db4e7eb49ab973bbb6f7bb9579e2a33776b2f7ead3fe25f9cb40812cb3efca7'))
    for arm in ('P05', 'P06', 'P11')
}
ORIGINAL_ORDINARY_SOURCES['P03'] = (
    ('system_campaign_midyear_facts', 'MidyearFacts', 'system-campaign-midyear-terminal-facts.json',
     'f2467de7dd56d1b69bac24be9caeeedd6be946e1e898dce9a9afefe054437018'),
)
ORIGINAL_DELIVERY_SOURCES['P03'] = ORIGINAL_ORDINARY_SOURCES['P03']
ORIGINAL_DELIVERY_PHASES = {('P05', '2020-12-31'): (
    ('system_campaign_parsley_facts', 'ParsleyFacts', 'system-campaign-parsley-terminal-facts.json',
     '1983dd966359020fff66eccf6d6d3c22de12190c11f5a3019cafcbf80af0478d'),)}
ORIGINAL_DELIVERY_PHASES['P03', '2019-05-31'] = (
    ('system_campaign_distribution_facts', 'DistributionFacts', 'system-campaign-distribution-facts.json',
     'db0e6498224929c322c1a73a0e5b7942110e7a1c645db8f6b21bd329f22d41ae'),
    ('system_campaign_tableau_facts', 'TableauFacts', 'system-campaign-tableau-terminal-facts.json',
     '1833a5f0cc85193416b195d896b2e6dae68927b54db8a2ddb91666c5a3cef544'),
)
ORIGINAL_DELIVERY_SUBSETS = {
    ('P03', '2019-05-31', 'system-campaign-distribution-facts.json'): ('LLL1',),
    ('P03', '2019-05-31', 'system-campaign-tableau-terminal-facts.json'): ('DATA', 'TCF1'),
}
ORIGINAL_ORDINARY_PHASES['P03', '2019-05-31'] = (
    ('system_campaign_array_facts', 'ArrayFacts', 'system-campaign-array-terminal-facts.json',
     '927d997f93e4633ee3fbb8e1350b1720380684ebf9e4fff1437c301847ac023d'),
    ('system_campaign_tableau_facts', 'TableauFacts', 'system-campaign-tableau-terminal-facts.json',
     '1833a5f0cc85193416b195d896b2e6dae68927b54db8a2ddb91666c5a3cef544'),
)

SUPPLEMENTAL_PHASES = {
    ('P05', '2018-11-30'): (
        ('system_campaign_yearend_facts', 'YearendFacts', 'PATH',
         'system-campaign-yearend-terminal-facts.json',
         '967d6fd19080f08142f5d93620ab832e10481b4c828d2a062cc9b1ca7166c7cb',
         'b4318a6ea900586e72e663aac9da28a607f415bb4a881a1c9061dc97bde2aa6e',
         ('MZOR', 'TSRO', 'ZAYO')),
        ('system_campaign_followon_facts', 'FollowonFacts', 'PATH',
         'system-campaign-followon-terminal-facts.json',
         '7ed27c0e6d9a7b79192b026a2d02036a0e6360c8a7e49f1069435cf537477822',
         '05fe3cf59db15350abf037e12cb0dd55ab721a9c04444a5686854fede3498c15',
         ('XOXO', 'MB2', 'ESRX')),
    ),
    ('P07', '2021-03-31'): (
        ('system_campaign_cash_batch', 'CashBatch', 'JSON',
         'system-campaign-future-input-amendment-catalog.json',
         '8764d9c2a4c53578b7bfcbbfe86ee49b050c8934e755e0bab7eaf16f4c576066',
         '29da1d97e921ca8886d18365b16c944461090302df8da63f4f4d7cfeee1e972f',
         ('FPRX', 'GNMK', 'GLUU', 'WIFI', 'PFPT', 'STMP', 'NUAN', 'CERN')),
    ),
}


SUPPLEMENTAL_PHASES['P03', '2018-11-30'] = (
    ('system_campaign_late_facts', 'LateFacts', 'PATH',
     'system-campaign-late-terminal-facts.json',
     '0db4e7eb49ab973bbb6f7bb9579e2a33776b2f7ead3fe25f9cb40812cb3efca7',
     'ac77d968aee0ffc769bfba22e69ca16daa5bac6c723997fc947a0612596236ca',
     ('OCLR', 'APTI', 'VSM')),
    *SUPPLEMENTAL_PHASES['P05', '2018-11-30'],
)


SUPPLEMENTAL_PHASES['P05', '2020-06-30'] = (
    ('system_campaign_autumn2020_cash_facts', 'CashCompletionFacts', 'PATH',
     'system-campaign-autumn2020-cash-terminal-facts.json',
     'bf6a1836439ce44e499a2ec9818ce3e780d45f9c350090b844bce419c579b6b7',
     'dedd4a1a314a74301805c7e7ea6ef2fe4e4c86ed549bebe0ad9a217d6399d020',
     ('MNTA','AIMT','IMMU','MYOK','VRTU')),
)
SUPPLEMENTAL_PHASES['P03', '2019-05-31'] = (
    ('system_campaign_tableau_facts', 'TableauFacts', 'PATH',
     'system-campaign-tableau-terminal-facts.json',
     '1833a5f0cc85193416b195d896b2e6dae68927b54db8a2ddb91666c5a3cef544',
     'd133d1f2753e6a662824d419eeb6597153cc059a431a93789f2143ff792ca0b6',
     ('CTRL', 'UQM', 'BKS')),
)
SUPPLEMENTAL_PHASES['P11', '2023-06-30'] = (
    ('system_campaign_cash_calendar', 'CashCalendar', 'JSON',
     'system-campaign-h2-2023-cash-calendar-terminal-facts.json',
     '8b461ae3218c30c3aad95721379544261814404d72e908920e1c81e9c0775086',
     '183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f',
     ('DICE','ARNC','FRG','FORG','CFMS','QUOT','RADI')),
)


SUPPLEMENTAL_PHASES['P03', '2019-09-30'] = (
    ('system_campaign_medicines_facts', 'MedicinesFacts', 'PATH',
     'system-campaign-medicines-terminal-facts.json',
     '6331ed5c48e09492cc0c15db2dac69ae0b31ce761a00bd443af7015ced1179e2',
     '4d77a4ad59ed8a626502573decfd7b842812228aa9c6cdf1c1f05a064b1717d5',
     ('MDCO',)),
    ('system_campaign_arqule_facts', 'ArQuleFacts', 'PATH',
     'system-campaign-arqule-terminal-facts.json',
     'a785c139eeea04306948fd7a62cca4d6d9b0dd9211dba30123dad4892a150aa4',
     '2ce2a4b4dcf0cb7573c3a724b1aea7d95327ed58b3b0d01a008225bb069b176a',
     ('ARQL',)),
)

SUPPLEMENTAL_PHASES['P06', '2021-03-31'] = (('system_campaign_2021_completions_facts', 'CompletionFacts', 'PATH', 'system-campaign-2021-completions-terminal-facts.json', 'de3dadebcbe04aebe5af60dfad8d419db120ef4629f27e3313aeb5b08b5ce0bb', 'c56061f9a7341dbb84c6314aeafeda50ce32eeac9286f6a0c055f166f07e36a2', ('MIK', 'VAR', 'NAV', 'WORK', 'HOME', 'TRIL1')), ('system_campaign_following_completions_facts', 'FollowingFacts', 'PATH', 'system-campaign-following-completions-terminal-facts.json', 'bcedc899f0b34295c5e299ef6d0ce222bc666eec871997ceddd4f963fa5ba24d', '2a8aeb2eaf1f0eeafd5b902675c08a3a8fe7907039c15d9b00e774300dd6325e', ('CATM', 'AZPN1', 'REGI', 'PLAN')))


ORIGINAL_ORDINARY_AGGREGATE_PHASES = {('P03', '2019-09-30')}
ORIGINAL_ORDINARY_SUBSETS = {
    ('P03', '2019-09-30', 'system-campaign-spring2020-cash-terminal-facts.json'): ('CY', 'MLNX', 'WBC'),
    ('P03', '2019-09-30', 'system-campaign-autumn2020-cash-terminal-facts.json'): ('MNTA', 'AIMT', 'IMMU', 'MYOK'),
}
ORIGINAL_ORDINARY_PHASES['P03', '2019-09-30'] = (
    ('system_campaign_spring2020_cash_facts', 'CashCompletionFacts', 'system-campaign-spring2020-cash-terminal-facts.json', '923a4ad70188bf808299d4bf0ec232871330da9009ad8c9aeb9f354a5f89c122'),
    ('system_campaign_autumn2020_cash_facts', 'CashCompletionFacts', 'system-campaign-autumn2020-cash-terminal-facts.json', 'bf6a1836439ce44e499a2ec9818ce3e780d45f9c350090b844bce419c579b6b7'),
)
ORIGINAL_DELIVERY_PHASES['P03', '2019-09-30'] = (
    ('system_campaign_sprint_facts', 'SprintFacts', 'system-campaign-sprint-terminal-facts.json', 'd30f52b302557445f8ed85e6314b7deb16e04f77009c5491c9de6287515116fe'),
)
ORIGINAL_DELIVERY_SUBSETS['P03', '2019-09-30', 'system-campaign-sprint-terminal-facts.json'] = ('S2',)
SINGLE_PHASES['P03', '2019-09-30'] = ('system_campaign_sprint_facts', 'SprintFacts', 'system-campaign-sprint-terminal-facts.json', ('S2',))
ROOT_BOUND_ALIAS_SOURCE_PHASES = {('P03', '2019-09-30'): (
    'bd698ea48738875baa59796f671ccf7439885976a5b439bf4d9bd4cddeb9164f',
    'a685ba1c6d4d0c6401f974cb681f02c08bb477e9498f468a6224dffa0d0184f0', 439)}

SUPPLEMENTAL_PHASES['P05', '2021-10-29'] = (('system_campaign_cash_calendar', 'CashCalendar', 'JSON', 'system-campaign-december-cash-calendar-terminal-facts.json', 'f7f5111041a7b22a6a9d0e2b627dc2b9e077fc0198ae0c3804061c2dcad3f6a6', '183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f', ('COR2', 'DRNA', 'ARNA', 'EPAY', 'CCXI1', 'NEWR', 'IMGN', 'CTLT')),)
SUPPLEMENTAL_SAME_DAY_PHASES = frozenset({('P05', '2021-10-29')})


class ResearchCashAssumption(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.daily-economic-cash-assumption/1'] = Field(alias='schema')
    published_cash_per_share: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    recognition_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    opening_availability_assumed: Literal[True]
    actual_settlement_claimed: Literal[False]
    settlement_fees: Literal['IGNORED_FOR_RESEARCH']


class ResearchNormalizedUSDCashAssumption(BaseModel):
    """Research FX normalization facts; neither holder payment nor PIT evidence."""
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.daily-normalized-usd-cash-assumption/1'] = Field(alias='schema')
    raw_cash_per_share: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    raw_cash_currency: Literal['CAD']
    target_cash_currency: Literal['USD']
    exchange_rate: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    exchange_rate_direction: Literal['CAD_PER_USD']
    exchange_rate_as_of_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    exchange_rate_source: Annotated[str, Field(min_length=1)]
    exchange_rate_source_record_sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    normalization_rule: Literal['RAW_CAD_DIVIDED_BY_CAD_PER_USD']
    decimal_precision: Literal[50]
    normalized_usd_decimal: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    canonical_usd_float_decimal: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    canonical_usd_float_hex: Annotated[str, Field(min_length=1)]
    primary_extraction_sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    recognition_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    opening_availability_assumed: Literal[True]
    actual_usd_payment_claimed: Literal[False]
    actual_settlement_claimed: Literal[False]
    fx_publication_before_open_proven: Literal[False]
    historical_causality_status: Literal['UNVERIFIED']
    settlement_fees: Literal['IGNORED_FOR_RESEARCH']


class ResearchUnheldCashAssumption(BaseModel):
    """Explicit closing-source assumption with no held-completion authority."""
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.daily-unheld-source-cash-assumption/1'] = Field(alias='schema')
    published_cash_per_share: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    recognition_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    closing_availability_assumed: Literal[True]
    completion_confirmed_by_close: Literal[False]
    actual_settlement_claimed: Literal[False]
    portfolio_completion_authorized: Literal[False]


class ResearchMixedAssumption(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.daily-mixed-consideration-assumption/1'] = Field(alias='schema')
    published_cash_per_share: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    published_cash_is_approximate: Literal[True]
    published_exchange_ratio: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    recognition_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    opening_availability_assumed: Literal[True]
    fractional_cash_proxy: Literal['FROZEN_DELIVERED_RAW_OPEN_NOT_ACTUAL_SETTLEMENT_RATE']
    actual_settlement_claimed: Literal[False]
    settlement_fees: Literal['IGNORED_FOR_RESEARCH']


class ResearchExactCashMixedAssumption(ResearchMixedAssumption):
    """Version2 preserves all daily assumptions and declares exact published cash."""
    schema_id: Literal['research.daily-mixed-consideration-assumption/2'] = Field(alias='schema')
    published_cash_is_approximate: Literal[False]


class ResearchAfterCloseMixedAssumption(ResearchExactCashMixedAssumption):
    """Version3 separates a confirmed post-close legal event from daily recognition."""
    schema_id: Literal['research.daily-mixed-consideration-assumption/3'] = Field(alias='schema')
    legal_effective_local: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$')]
    legal_effective_timezone: Literal['America/New_York']
    completed_after_close_confirmed: Literal[True]


class ResearchTenderAssumption(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.assumed-tender-cash-recognition/1'] = Field(alias='schema')
    published_cash_per_source_unit: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    source_unit: Literal['LISTED_DEPOSITARY_SHARE']
    offer_deadline_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    recognition_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    tender_participation_assumed: Literal[True]
    opening_availability_assumed: Literal[True]
    actual_settlement_claimed: Literal[False]
    settlement_fees: Literal['IGNORED_FOR_RESEARCH']


class ResearchSourceExitAssumption(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.unheld-source-exit-assumption/1'] = Field(alias='schema')
    treatment: Literal['UNHELD_SOURCE_EXIT_AT_LAST_RETAINED_RAW_CLOSE_NOT_STATUTORY_CASH']
    retained_quote_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    retained_raw_close: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    retained_quote_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    recognition_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    scope: Literal['NEVER_HELD_NO_INTENT_RESERVATION_OR_CLAIM']
    held_settlement_supported: Literal[False]
    legal_identity_admitted: Literal[False]
    execution_price_claimed: Literal[False]
    actual_settlement_claimed: Literal[False]


class SourceOnlyScope(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.unowned-closing-source-scope/1'] = Field(alias='schema')
    arm: str
    parent_outer_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    parent_root_admission_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    hydrated_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    overlay_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    terminal_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    security_id: str
    source_valuation_phase: Literal['CLOSE']
    portfolio_completion_authorized: Literal[False]
    require_unowned_and_unordered: Literal[True]


class NativePreimageQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.unconsumed-cash-native-preimage-query/1'] = Field(alias='schema')
    native_kind: Literal['CASH_MERGER']
    maximum_terms: Literal[1]
    financial_use_authorized: Literal[False]


class NativeDateQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.bounded-native-terminal-date-query/1', 'research.bounded-native-terminal-date-query/2'] = Field(alias='schema')
    security_id: Annotated[str, Field(min_length=1)]
    session_from: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    session_to: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    maximum_records: Literal[16]
    financial_use_authorized: Literal[False]
    include_outside_window: Literal[True] | None = None


class ObservationIdentityQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.frozen-observation-identity-query/1'] = Field(alias='schema')
    session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    ticker: Annotated[str, Field(min_length=1)]
    match_mode: Literal['EXACT', 'PREFIX'] = 'EXACT'
    maximum_rows: Literal[1]
    require_unheld_at_parent: Literal[True]
    financial_use_authorized: Literal[False]


class NeverHeldSourceExitScope(SourceOnlyScope):
    schema_id: Literal['research.never-held-source-exit-scope/1'] = Field(alias='schema')
    source_ticker: Annotated[str, Field(min_length=1)]
    require_never_held: Literal[True]


RESEARCH_UNHELD_COMPOSITE = 'ORIGINAL_UNHELD_COMPOSITE_NATIVE_DAY'
ORIGINAL_UNHELD_COMPOSITE_MODELS = {
    'research.p01-unheld-composite-cash-input/1': dict(
        input_file='p01_iac_namespace_continue_cash_input.json',
        input_sha256='4978eebd26d840a0d1678ba96fdae302e844f08f932d6eaa0b2ed675470b869c',
        compiler_file='p01_iac_namespace_continue.py',
        compiler_sha256='1dd6857cb374532bd33faeaadd53bdd4ae600e68c16a5534408fa498d8cb8cf5',
        constructor='UnheldCashInput', scope_function='mdp_unheld_scope', scope_symbol='MDP',
        identity_field='source_security_id', ticker_field='source_ticker',
        distribution_ratio_field='new_meredith_distribution_ratio',
        cash_component_fields=('gray_cash_per_old_share','dotdash_cash_per_distributed_share'),
        aggregate_field='aggregate_cash_per_old_share',
        ordered_legs=('DISTRIBUTE_NEW_MEREDITH_ONE_FOR_ONE','GRAY_CASH_16_99','DOTDASH_CASH_42_18')),
}


class ResearchOriginalUnheldCompositeAssumption(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.original-unheld-composite-native-day-assumption/1'] = Field(alias='schema')
    original_input_schema: str
    original_input_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    recognition_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    aggregate_cash_per_original_share: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    ordered_legs: list[str] = Field(min_length=1)
    require_never_held: Literal[True]
    held_multileg_supported: Literal[False]
    preopen_availability_claimed: Literal[False]
    actual_settlement_claimed: Literal[False]
    strict_archival_PIT_claimed: Literal[False]
    portfolio_completion_authorized: Literal[False]


class OriginalUnheldCompositeSourceScope(NeverHeldSourceExitScope):
    schema_id: Literal['research.original-unheld-composite-source-scope/1'] = Field(alias='schema')
    original_input_schema: str
    original_input_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    original_compiler_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


def original_unheld_composite_model(reference):
    """Read original legal/schema bytes; never load its originating book."""
    import ast
    registration = ORIGINAL_UNHELD_COMPOSITE_MODELS.get(reference['schema'])
    need(registration is not None, 'COMPOSITE_SOURCE_ONLY_REGISTERED_ORIGINAL_SCHEMA')
    expected = {k: registration[k] for k in ('input_file','input_sha256','compiler_file','compiler_sha256')}
    need(reference == dict(schema=reference['schema'], **expected), 'COMPOSITE_SOURCE_EXACT_ORIGINAL_FILE_BINDING')
    original_raw = (HERE / expected['input_file']).read_bytes()
    source = (HERE / expected['compiler_file']).read_bytes()
    need(sha(original_raw) == expected['input_sha256'] and sha(source) == expected['compiler_sha256'],
         'COMPOSITE_SOURCE_UNCHANGED_ORIGINAL_LEGAL_AND_COMPILER_BYTES')
    tree = ast.parse(source)
    symbol, = [n for n in tree.body if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == registration['scope_symbol'] for t in n.targets)]
    identity = ast.literal_eval(symbol.value)
    scope, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == registration['scope_function']]
    namespace = dict(need=need,**{registration['scope_symbol']:identity})
    exec(compile(ast.Module(body=[scope],type_ignores=[]),'<unchanged-original-pure-composite-scope>','exec'),namespace)
    document = json.loads(original_raw)
    need(document['schema'] == reference['schema'] and document[registration['identity_field']] == identity
         and document['held_multileg_supported'] is False,
         'COMPOSITE_SOURCE_ORIGINAL_SCHEMA_NO_HELD_AUTHORITY')
    return document,registration,namespace[registration['scope_function']]


def research_original_unheld_composite_term(term):
    from decimal import Decimal
    model = ResearchOriginalUnheldCompositeAssumption.model_validate(term['research_assumption'])
    original, registration, _ = original_unheld_composite_model(term['retained_original_composite_input'])
    ratio = Fraction(original[registration['distribution_ratio_field']])
    first,second = (Decimal(original[name]) for name in registration['cash_component_fields'])
    total = first + second * Decimal(ratio.numerator) / Decimal(ratio.denominator)
    need(ratio == 1 and total == Decimal(original[registration['aggregate_field']])
         == Decimal(model.aggregate_cash_per_original_share)
         and model.ordered_legs == original['ordered_legs'] == list(registration['ordered_legs']),
         'COMPOSITE_SOURCE_ALL_ORDERED_LEGS_AND_EXACT_DECIMAL_SUM')
    a,w = term['added'],term['identity_witness']
    need(term['recognition_rule'] == RESEARCH_UNHELD_COMPOSITE
         and model.original_input_schema == original['schema']
         and model.original_input_sha256 == registration['input_sha256']
         and term['parent_cursor'] == w['session'] < term['native_session'] == a['session']
             == original['earliest_affected_session'] == model.recognition_session
         and original['clock_scope'] == 'EXISTING_NATIVE_CALENDAR_DAY_UNHELD_ONLY_NO_PREOPEN_CLAIM'
         and original['scope'] == 'NEVER_HELD_NO_INTENT_RESERVATION_OR_CLAIM_UNHELD_TERMINAL_MARKER_ONLY'
         and term['native_term_sha256'] == original['native_term_sha256']
         and term['security_id'] == w['security_id'] == a['security_id'] == original[registration['identity_field']]
         and term['ticker'] == w['ticker'] == original[registration['ticker_field']],
         'COMPOSITE_SOURCE_EXACT_NATIVE_DAY_CURRENT_PARENT_IDENTITY_AND_ORIGINAL_CLOCK')
    need(a['kind'] == 'CASH_MERGER' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and Fraction(str(a['cash_per_share'])) == Fraction(total)
         and a['entitlement_aggregation'] == 'HOLDER'
         and all(a[k] is None for k in ('delivered_security_id','delivered_ticker','delivered_issuer_id',
                                       'exchange_ratio','cash_in_lieu_price_per_delivered_share'))
         and term['primary_source'] == original['primary_urls'][0]
         and term['timing_source'] in original['primary_urls']
         and a['reference'] == term['primary_source'] + ' | ' + term['description'],
         'COMPOSITE_SOURCE_ONLY_DECLARED_TERMINAL_MARKER_NO_HELD_LEG_ALLOCATION')
    need(term['source_valuation_phase'] == 'CLOSE' and term['parent_positions'] == []
         and term['preopen_completion_confirmed'] is term['mandatory_common_share_completion_confirmed'] is False
         and term['portfolio_completion_authorized'] is False and term['require_unowned_and_unordered'] is True
         and term['require_never_held'] is True and term['source_parent_selected'] is True,
         'COMPOSITE_SOURCE_EXPLICIT_SELECTED_UNHELD_ONLY_AUTHORITY')


def require_original_composite_scope(wealth,pending,ledger,scope):
    registration = ORIGINAL_UNHELD_COMPOSITE_MODELS.get(scope['original_input_schema'])
    need(registration is not None and scope['original_input_sha256'] == registration['input_sha256']
         and scope['original_compiler_sha256'] == registration['compiler_sha256'],
         'COMPOSITE_SCOPE_EXACT_ORIGINAL_SCHEMA_AND_SOURCES')
    reference = dict(schema=scope['original_input_schema'],**{k:registration[k] for k in
        ('input_file','input_sha256','compiler_file','compiler_sha256')})
    original,registered,guard = original_unheld_composite_model(reference)
    need(scope['security_id'] == original[registered['identity_field']]
         and scope['source_ticker'] == original[registered['ticker_field']],
         'COMPOSITE_SCOPE_EXACT_ORIGINAL_SOURCE_IDENTITY')
    pending_data = risk_diagnostic_value(pending)
    need(isinstance(pending_data,list) and all(isinstance(p,dict) and 'security_id' in p for p in pending_data),
         'COMPOSITE_SCOPE_SUPPORTED_COMPLETE_PENDING_RECORDS')
    guard(dict(wealth_core=wealth,pending=pending_data,ledger=ledger))
    need(not mentions_source([wealth['episodes'],pending_data,ledger['receivables']],
                             (scope['security_id'],scope['source_ticker']))
         and not any(s.get('reserved_ticker') == scope['source_ticker'] for s in wealth['slots'].values()),
         'COMPOSITE_SCOPE_NO_RELATED_CHILD_INTENT_RESERVATION_OR_DUE_BILL')


def original_composite_source_names():
    return sorted({registration[k] for registration in ORIGINAL_UNHELD_COMPOSITE_MODELS.values()
                   for k in ('input_file','compiler_file')})


OWN_CASH_SOURCE_CLOCKS = {('P03', '2018-08-31'): (41919370510, '3aa0c311346305f0699dd3562ee047106129efdc', 13366886633),
 ('P11', '2022-05-31'): (41919370510, '3aa0c311346305f0699dd3562ee047106129efdc', 13367285466),
 ('P03', '2018-04-30'): (41889428177, 'eb12a1517e9f3e73c7e4976f9bc7dfcc44367855', 13353540587),
 ('P07', '2020-06-30'): (41827156321, '9f4dbf9ae615cbdfcee7b10ee3c2458855c90c4b', 13320032317),
 ('P00', '2025-06-30'): (41837453683, 'ecf08be298726e86ed48d97f468b834d3fcb51a6', 13327262198),
 ('P04', '2022-09-30'): (41830900595, '6022c86853d71a575df8e562a0d1ada63f787dd2', 13321284554),
 ('P04', '2022-08-31'): (41798315426, 'c750169a3cadb1d18fc58cdb6e5ec3cc807c6dd7', 13307310013),
 ('P00', '2018-08-31'): (41807854617, '4bd9083c233779cbfbb00503a6bfee9bf7d2ddcd', 13311490065),
 ('P04', '2022-06-30'): (41783795694, 'cddd0dfb84433998b52c46b5e53e836a84fc5d58', 13299799904),
 ('P10', '2022-07-29'): (41783795694, 'cddd0dfb84433998b52c46b5e53e836a84fc5d58', 13299684770),
 ('P10', '2024-04-30'): (41799737694, '3ea65d6eefefc66d593858dc0ee6a4b476769c2a', 13307052219),
 ('P05', '2018-01-31'): (41856244317, 'b68cab1f7989e35af90630f6fbfc82e11c0c18ea', 13338596091),
 ('P06', '2018-01-31'): (41856244317, 'b68cab1f7989e35af90630f6fbfc82e11c0c18ea', 13337926516),
 ('P11', '2018-01-31'): (41856244317, 'b68cab1f7989e35af90630f6fbfc82e11c0c18ea', 13337507034),
 ('P04', '2025-10-31'): (41858834037, '790729ae679f165e6c3fb458a5c1537e3f07f05e', 13339516521),
 ('P11', '2018-08-31'): (41874947218, '23ff8feb61239406896bafe24a80bfc9cb95be89', 13345399053)}
OWN_CASH_SOURCE_CLOCKS['P05', '2020-01-31'] = (41923205664, '3e1c36e288bcf3ebf553f9e560583e8771b485ab', 13367833467)
OWN_CASH_SOURCE_CLOCKS['P03', '2018-11-30'] = (41934413763, 'e808ed5be1b537fc51a726ecf156620e43a630d9', 13373513049)
OWN_CASH_SOURCE_CLOCKS['P05', '2020-06-30'] = (41939321606, '0e8dcd539f7e473f206285e44c8db523c41e7d73', 13375404569 )
OWN_CASH_SOURCE_CLOCKS['P11', '2023-06-30'] = (41939321606, '0e8dcd539f7e473f206285e44c8db523c41e7d73', 13376016520 )
OWN_CASH_SOURCE_CLOCKS['P03', '2018-12-31'] = (41944211225, 'e81158bfa1feadfd0c97d6c4bf7999cc263a0c1d', 13378121330)
OWN_CASH_SOURCE_CLOCKS['P06', '2020-02-28'] = (41950496055, '4447cb10993eb7a7069a389615d25500dc180a95', 13380408021)
OWN_CASH_SOURCE_CLOCKS['P05', '2020-11-30'] = (41950496055, '4447cb10993eb7a7069a389615d25500dc180a95', 13380652339)
OWN_CASH_SOURCE_CLOCKS['P03', '2019-05-31'] = (41961189857, 'a766451be5a7fdcdad6f1cc755244f7ab5bbd8be', 13384628988)
OWN_CASH_SOURCE_CLOCKS['P06', '2020-06-30'] = (41966300662, '9f73b5fa7ab5102b079313b6715f030e70419c7a', 13388235253)
OWN_CASH_SOURCE_CLOCKS['P11', '2025-06-30'] = (41971859824, 'f304f01185feadb9ab9ecd2509d9f9a57b3f2ee6', 13390656184)
OWN_CASH_SOURCE_CLOCKS['P03', '2019-09-30'] = (41974204844, '51a1d68b1a615af2e80937f11e22a60510802185', 13391196722)
OWN_CASH_SOURCE_CLOCKS['P06', '2021-03-31'] = (41978263810, 'a0a06b71157b91557bf30951ac4dc7a2aba243ca', 13392737266)
OWN_CASH_SOURCE_CLOCKS['P11', '2026-02-27'] = (41992111094, 'e0272a24fc706b2f35c5310f89718cc418b49c37', 13398956926)
OWN_CASH_SOURCE_CLOCKS['P05', '2021-10-29'] = (41992111094, 'e0272a24fc706b2f35c5310f89718cc418b49c37', 13397614792)
OWN_CASH_SOURCE_CLOCKS['P11', '2026-04-30'] = (42020159295, '6d0abbb92a2647a93112cecad78b8c1397c2c467', 13411242209)
HISTORICAL_WITNESS_SCOPES = {
    'P04': dict(parent_outer_sha256='0e6028db71e0a12efd603580870f57495e5c66d1d46a0aaf264567e6aacf68fe',
        parent_cursor='2022-06-30', terms=[dict(ticker='SAFM', security_id='962454383671746307',
            session='2022-07-20', native_session='2022-07-21',
            native_term_sha256='d00cf559bcc50db02d1e30e69194f3f92949e1085b4bd23b53c4f134aba86d09',
            parent_positions=[dict(slot_id=6, ticker='SAFM', quantity=29, entry_date='2022-06-30')])]),
    'P10': dict(parent_outer_sha256='e1c1c823374d10e0cbf62752b0465e39c23165ec80a61e3f357bea13217462e4',
        parent_cursor='2022-07-29', terms=[dict(ticker='ACC', security_id='209530306982231273',
            session='2022-08-08', native_session='2022-08-09',
            native_term_sha256='dedc2034f8b43302ab25e6be16e3c4896563412b8510b3cb4083281b6cbf21a7',
            parent_positions=[])]),
}
NEXT_WITNESS_SCOPES = {
    'P00': dict(parent_outer_sha256='ad12b8a58f00560f1393cccdc0d9718b59d172265fc89f4bc36cb1ec7a4b37d2',
        parent_cursor='2018-08-31', terms=[dict(ticker='ILG', security_id='278081346388915134',
            session='2018-08-30', native_session='2018-08-31',
            native_term_sha256='9aa688a1c3a76f03ed5f2ca463b75a19d20b10937333e51946ab3d74cdce1703',
            parent_positions=[dict(slot_id=1, ticker='ILG', quantity=90, entry_date='2017-07-05')],
            pending_at_parent=dict(pending_sessions=0, stale_at_event=0, unresolved=False,
                native_term_sha256='9aa688a1c3a76f03ed5f2ca463b75a19d20b10937333e51946ab3d74cdce1703'))],
        additional_rows=[dict(ticker='VAC', security_id='851672149700415133', session='2018-09-04',
            source_observation_sha256='e76a958ab2504c0372cbe44096c1d3e4d4b156723574705b93df34c3afebf595',
            parent_positions=[])]),
    'P04': dict(parent_outer_sha256='5ff96b14f5e463494d22816ee6a61464411498324cd8298ec48461e12a5f90ac',
        parent_cursor='2022-08-31', terms=[dict(ticker='CTXS', security_id='554480052825212855',
            session='2022-09-28', native_session='2022-09-29',
            native_term_sha256='6c306190c326bc01b52d3fb9fda5f2cd2cdf09fdc447cb5a41064136c6c4329a',
            parent_positions=[])]),
    'P10': dict(parent_outer_sha256='6ffb77026ee113108e175f22c6aa24c2d68963b24b48100340b9ce9888d58377',
        parent_cursor='2024-04-30', terms=[dict(ticker='SWAV', security_id='158012003593585084',
            session='2024-05-29', native_session='2024-05-30',
            native_term_sha256='011cbd286ef8f6e57519452164b18187177190814dfe5742ce4ac52d70f02a0c',
            parent_positions=[])]),
}
NEXT_WITNESS_SCOPES['P07'] = {'parent_outer_sha256': 'b4dfd007ce0e9ea454b8a174f7796b3be416620173d85715b24abdbfdb56d9a3',
 'parent_cursor': '2020-06-30',
 'terms': [{'ticker': 'LM',
            'security_id': '986298677409235360',
            'session': '2020-07-29',
            'native_session': '2020-07-30',
            'native_term_sha256': '6b60c2374934a08916f197cd917df1a40074fe15818797d6d02b4c942d07917d',
            'parent_positions': [{'slot_id': 20,
                                  'ticker': 'LM',
                                  'quantity': 49,
                                  'entry_date': '2020-06-24'}]}]}
DISCOVERY_WITNESS_SCOPES = {'P04': {'parent_outer_sha256': '65216f19c6aac8b0c31db34fa40fa4cc63c5875406b0ed2f1aae457181554433',
         'parent_cursor': '2022-09-30',
         'native_preimage_query': {'schema': 'research.unconsumed-cash-native-preimage-query/1',
                                   'native_kind': 'CASH_MERGER',
                                   'maximum_terms': 1,
                                   'financial_use_authorized': False},
         'terms': [{'ticker': 'GBT',
                    'security_id': '827416728546053456',
                    'session': '2022-10-03',
                    'native_session': '2022-10-04',
                    'native_term_sha256': None,
                    'parent_positions': []}]}}
RESOLVED_WITNESS_SCOPES = {'P04': {'parent_cursor': '2022-09-30',
         'parent_outer_sha256': '65216f19c6aac8b0c31db34fa40fa4cc63c5875406b0ed2f1aae457181554433',
         'terms': [{'native_session': '2022-10-04',
                    'native_term_sha256': '24ecdb67869b11470699c0bf1a02ca59f46d671bd9008d196f4a80cd05c46500',
                    'parent_positions': [],
                    'security_id': '827416728546053456',
                    'session': '2022-10-03',
                    'ticker': 'GBT'}]}}
EXTRA_WITNESS_SCOPES = {('P00', '2025-06-30'): {'parent_outer_sha256': 'fef5c1fa91e000030d09fe758ec2abd01bf48dbd2b2a3f2c197c4cfa0e32c93c',
                         'parent_cursor': '2025-06-30',
                         'terms': [{'ticker': 'TGI',
                                    'security_id': '498918945550351909',
                                    'session': '2025-07-23',
                                    'native_session': '2025-07-24',
                                    'native_term_sha256': 'd64927eb0e80aa8e0a5e596cb60a510b45896548ea33f082442ae8a7a9a40580',
                                    'parent_positions': [{'slot_id': 2,
                                                          'ticker': 'TGI',
                                                          'quantity': 234,
                                                          'entry_date': '2025-04-04'}]}]}}
INITIAL_WITNESS_SCOPES = {'P05': {'parent_outer_sha256': '201001331f78634a46ce80509992c04c927ae6304dda28a3f248f3a4393c718b',
         'parent_cursor': '2018-01-31',
         'native_preimage_query': {'schema': 'research.unconsumed-cash-native-preimage-query/1',
                                   'native_kind': 'CASH_MERGER',
                                   'maximum_terms': 1,
                                   'financial_use_authorized': False},
         'terms': [{'ticker': 'AAAP1',
                    'security_id': '554122275008038119',
                    'session': '2018-01-31',
                    'native_session': '2018-02-09',
                    'native_term_sha256': None,
                    'parent_positions': [{'slot_id': 7,
                                          'ticker': 'AAAP1',
                                          'quantity': 25,
                                          'entry_date': '2018-01-08'}]}]},
 'P06': {'parent_outer_sha256': '55d61959194c0572a9a686a1ace6202255296ec1cae81127a170a7785a5bcb2a',
         'parent_cursor': '2018-01-31',
         'native_preimage_query': {'schema': 'research.unconsumed-cash-native-preimage-query/1',
                                   'native_kind': 'CASH_MERGER',
                                   'maximum_terms': 1,
                                   'financial_use_authorized': False},
         'terms': [{'ticker': 'AAAP1',
                    'security_id': '554122275008038119',
                    'session': '2018-01-31',
                    'native_session': '2018-02-09',
                    'native_term_sha256': None,
                    'parent_positions': [{'slot_id': 29,
                                          'ticker': 'AAAP1',
                                          'quantity': 17,
                                          'entry_date': '2017-12-20'}]}]},
 'P11': {'parent_outer_sha256': '527b7d4fcb92d4136195cc0eacf0459b73c368edfb0cdf3e9121f15ed8335e57',
         'parent_cursor': '2018-01-31',
         'native_preimage_query': {'schema': 'research.unconsumed-cash-native-preimage-query/1',
                                   'native_kind': 'CASH_MERGER',
                                   'maximum_terms': 1,
                                   'financial_use_authorized': False},
         'terms': [{'ticker': 'AAAP1',
                    'security_id': '554122275008038119',
                    'session': '2018-01-31',
                    'native_session': '2018-02-09',
                    'native_term_sha256': None,
                    'parent_positions': [{'slot_id': 11,
                                          'ticker': 'AAAP1',
                                          'quantity': 35,
                                          'entry_date': '2017-11-30'}]}]}}
EXTRA_WITNESS_SCOPES['P04', '2025-10-31'] = {'parent_outer_sha256': 'f5562177949d371147920b4cbd05bd149559c2840bd2c742ff826ea245b938a8', 'parent_cursor': '2025-10-31', 'terms': [{'ticker': 'LNWO', 'security_id': '467726443352731838', 'session': '2025-11-13', 'native_session': '2025-11-14', 'native_term_sha256': '6cc2c176c4e2289531450e4bbfc11a0434114506766daed1310363a9ad6aff8d', 'parent_positions': []}]}
RESOLVED_TENDER_WITNESS_SCOPES = {'P05': {'parent_cursor': '2018-01-31',
         'parent_outer_sha256': '201001331f78634a46ce80509992c04c927ae6304dda28a3f248f3a4393c718b',
         'terms': [{'native_session': '2018-02-09',
                    'native_term_sha256': '4dadd533c4360a8f766033f95d0bea355dea375ff223d39cfd3c893ebb1ee0b9',
                    'parent_positions': [{'entry_date': '2018-01-08',
                                          'quantity': 25,
                                          'slot_id': 7,
                                          'ticker': 'AAAP1'}],
                    'security_id': '554122275008038119',
                    'session': '2018-01-31',
                    'ticker': 'AAAP1'}]},
 'P06': {'parent_cursor': '2018-01-31',
         'parent_outer_sha256': '55d61959194c0572a9a686a1ace6202255296ec1cae81127a170a7785a5bcb2a',
         'terms': [{'native_session': '2018-02-09',
                    'native_term_sha256': '4dadd533c4360a8f766033f95d0bea355dea375ff223d39cfd3c893ebb1ee0b9',
                    'parent_positions': [{'entry_date': '2017-12-20',
                                          'quantity': 17,
                                          'slot_id': 29,
                                          'ticker': 'AAAP1'}],
                    'security_id': '554122275008038119',
                    'session': '2018-01-31',
                    'ticker': 'AAAP1'}]},
 'P11': {'parent_cursor': '2018-01-31',
         'parent_outer_sha256': '527b7d4fcb92d4136195cc0eacf0459b73c368edfb0cdf3e9121f15ed8335e57',
         'terms': [{'native_session': '2018-02-09',
                    'native_term_sha256': '4dadd533c4360a8f766033f95d0bea355dea375ff223d39cfd3c893ebb1ee0b9',
                    'parent_positions': [{'entry_date': '2017-11-30',
                                          'quantity': 35,
                                          'slot_id': 11,
                                          'ticker': 'AAAP1'}],
                    'security_id': '554122275008038119',
                    'session': '2018-01-31',
                    'ticker': 'AAAP1'}]}}
EXTRA_WITNESS_SCOPES['P11', '2018-08-31'] = {'parent_outer_sha256': '6674bb20eeac387f06ff53eba3a58046a63e1183b75e01e6c642c99e5c853b1a', 'parent_cursor': '2018-08-31', 'terms': [{'ticker': 'EDR1', 'security_id': '371238123781729047', 'session': '2018-09-18', 'native_session': '2018-09-19', 'native_term_sha256': '8e02d5bedff161467045415a77cffeb603a79fee9156dc51926ccba5123a715f', 'parent_positions': [{'slot_id': 4, 'ticker': 'EDR1', 'quantity': 1, 'entry_date': '2018-08-31'}]}]}
EXTRA_WITNESS_SCOPES['P03', '2018-04-30'] = dict(
    parent_outer_sha256='8b7358f5848b23ac440a9d5da094f17bee39acd46e8ad69526159e23af509f6b',
    parent_cursor='2018-04-30',
    terms=[dict(ticker='FMSA', security_id='278580348046109004', session='2018-05-30',
                native_session='2018-05-31', native_term_sha256=None, parent_positions=[])],
    native_preimage_query=dict(schema='research.unconsumed-cash-native-preimage-query/1',
                               native_kind='CASH_MERGER', maximum_terms=1, financial_use_authorized=False),
    additional_row_queries=[dict(schema='research.frozen-observation-identity-query/1',
                                 session='2018-06-01', ticker='CVIA', maximum_rows=1,
                                 require_unheld_at_parent=True, financial_use_authorized=False)])
EXTRA_WITNESS_SCOPES['P03', '2018-04-30-resolved'] = {'additional_rows': [{'parent_positions': [],
                      'security_id': '357217500185735770',
                      'session': '2018-06-01',
                      'source_observation_sha256': '8acc30ed1e01a33320a54ca45f8f5d0c112bf3889900129b8d17e08199563053',
                      'ticker': 'CVIAQ'}],
 'parent_cursor': '2018-04-30',
 'parent_outer_sha256': '8b7358f5848b23ac440a9d5da094f17bee39acd46e8ad69526159e23af509f6b',
 'terms': [{'native_session': '2018-05-31',
            'native_term_sha256': 'ea6383d0b229748e2248335707c24b66f30e1479f4374da3aa450f0fbc40b877',
            'parent_positions': [],
            'security_id': '278580348046109004',
            'session': '2018-05-30',
            'ticker': 'FMSA'}]}
ROW_QUERY_WITNESS_SCOPES = {'P03_PREFIX': deepcopy(EXTRA_WITNESS_SCOPES['P03', '2018-04-30'])}
ROW_QUERY_WITNESS_SCOPES['P03_PREFIX']['additional_row_queries'][0]['match_mode'] = 'PREFIX'
EXTRA_WITNESS_SCOPES['P11', '2022-05-31'] = dict(
    parent_outer_sha256='8e43f75b8686d18f688b6cb35b6292634e525e8b9b979351d3765923e4a0af34',
    parent_cursor='2022-05-31', native_preimage_query=dict(
        schema='research.unconsumed-cash-native-preimage-query/1', native_kind='CASH_MERGER',
        maximum_terms=1, financial_use_authorized=False),
    terms=[dict(ticker='TVTY', security_id='506048722516044547', session='2022-06-27',
                native_session='2022-06-28', native_term_sha256=None, parent_positions=[])])
NATIVE_DATE_WITNESS_SCOPES = {
    'P03': dict(parent_outer_sha256='46c576de5f3d5f9ecaabe460bf82ac5d5a184b42f2f4297583324f65dd5f2b54',
        parent_cursor='2018-08-31', terms=[dict(ticker='NLST', security_id='92160119416751819',
            session='2018-09-25', parent_positions=[])],
        native_date_query=dict(schema='research.bounded-native-terminal-date-query/1',
            security_id='92160119416751819', session_from='2018-09-26', session_to='2018-10-15',
            maximum_records=16, financial_use_authorized=False)),
    'P11': dict(parent_outer_sha256='8e43f75b8686d18f688b6cb35b6292634e525e8b9b979351d3765923e4a0af34',
        parent_cursor='2022-05-31', terms=[dict(ticker='TVTY', security_id='506048722516044547',
            session='2022-06-27', parent_positions=[])],
        native_date_query=dict(schema='research.bounded-native-terminal-date-query/1',
            security_id='506048722516044547', session_from='2022-06-28', session_to='2022-07-15',
            maximum_records=16, financial_use_authorized=False)),
}
NATIVE_INVENTORY_WITNESS_SCOPES = deepcopy(NATIVE_DATE_WITNESS_SCOPES)
for _scope in NATIVE_INVENTORY_WITNESS_SCOPES.values():
    _scope['native_date_query'].update(schema='research.bounded-native-terminal-date-query/2', include_outside_window=True)
RESOLVED_NATIVE_WITNESS_SCOPES = {
    'P03': dict(parent_outer_sha256='46c576de5f3d5f9ecaabe460bf82ac5d5a184b42f2f4297583324f65dd5f2b54',
        parent_cursor='2018-08-31', terms=[dict(ticker='NLST', security_id='92160119416751819',
            session='2018-09-25', native_session='2018-09-26', parent_positions=[],
            native_term_sha256='b3c9c9332ac9fa5380eadd30abfda1ff4ecb0d0bf671d7e4d1c1cf8bb2c040b3')]),
    'P11': dict(parent_outer_sha256='8e43f75b8686d18f688b6cb35b6292634e525e8b9b979351d3765923e4a0af34',
        parent_cursor='2022-05-31', terms=[dict(ticker='TVTY', security_id='506048722516044547',
            session='2022-06-24', native_session='2022-06-27', parent_positions=[],
            native_term_sha256='aca7bf92b9c5faea11cf82b77b7e081e728242a3775f9ba2f435da3015236e95')]),
}
EXTRA_WITNESS_SCOPES['P05', '2020-01-31'] = dict(
    parent_outer_sha256='8c3f8d3c53b380317fd624e7a55714960cf82ba44f1aaca204f58fbdaed28b38',
    parent_cursor='2020-01-31', terms=[dict(ticker='WLH', security_id='355892456681242666',
        session='2020-02-04', native_session='2020-02-05', parent_positions=[],
        native_term_sha256='431c662cb0a1bc988bc0db33c4f08e0a1037112ab6ac900c0930381af2f38181')],
    additional_row_queries=[dict(schema='research.frozen-observation-identity-query/1',
        session='2020-02-06', ticker='TMHC', maximum_rows=1,
        require_unheld_at_parent=True, financial_use_authorized=False)])
EXTRA_WITNESS_SCOPES['P05_RESOLVED', '2020-01-31'] = {'additional_rows': [{'parent_positions': [], 'security_id': '13062188894457483', 'session': '2020-02-06', 'source_observation_sha256': 'a08bf595ba2f598f4c96fe0d0459185920cdbffc52f189216045f3f77f7720a3', 'ticker': 'TMHC'}], 'parent_cursor': '2020-01-31', 'parent_outer_sha256': '8c3f8d3c53b380317fd624e7a55714960cf82ba44f1aaca204f58fbdaed28b38', 'terms': [{'native_session': '2020-02-05', 'native_term_sha256': '431c662cb0a1bc988bc0db33c4f08e0a1037112ab6ac900c0930381af2f38181', 'parent_positions': [], 'security_id': '355892456681242666', 'session': '2020-02-04', 'ticker': 'WLH'}]}
EXTRA_WITNESS_SCOPES['P03', '2018-11-30'] = dict(
    parent_outer_sha256='9330b6d44b8dac35d528d18aed2687c5a4609c0cedd2c0872f2b4229f88844d1',
    parent_cursor='2018-11-30',terms=[dict(ticker='ARII',security_id='435766160247494711',
        session='2018-12-03',native_session='2018-12-04',
        native_term_sha256='4447441e01411420775c471f8c54d01fe6f00d54adaff997517b0d360cad8222',parent_positions=[])])
EXTRA_WITNESS_SCOPES['P05', '2020-06-30'] = dict(
    parent_outer_sha256='2666a9c29c778f499db15c687303d1dd663edc6cb3461d3ba877c615c03a4446',
    parent_cursor='2020-06-30',terms=[dict(ticker='LM',security_id='986298677409235360',
        session='2020-07-29',native_session='2020-07-30',
        native_term_sha256='6b60c2374934a08916f197cd917df1a40074fe15818797d6d02b4c942d07917d',
        parent_positions=[dict(slot_id=17,ticker='LM',quantity=41,entry_date='2020-04-03')])])
EXTRA_WITNESS_SCOPES['P11', '2023-06-30'] = dict(
    parent_outer_sha256='28f4b89c314c2d9b3fe3256412d83f335bf394708497b638fba9e95cb1cd3895',
    parent_cursor='2023-06-30',terms=[dict(ticker='AJRD',security_id='721679296374852573',
        session='2023-07-26',native_session='2023-07-27',
        native_term_sha256='c18c68ef2a138d80a1bf1325d3ece4707e45c2bb6d51ea96a9a3c6dbb402237d',
        parent_positions=[dict(slot_id=15,ticker='AJRD',quantity=75,entry_date='2023-02-13')])])
EXTRA_WITNESS_SCOPES['P03', '2018-12-31'] = dict(
    parent_outer_sha256='32b2fb50d0686f057814a7d1950b5bf5a48bd7a46ad7c686e2dcda6cdca1ebf7',
    parent_cursor='2018-12-31',terms=[dict(ticker='SEND',security_id='33561376965494239',
        session='2019-01-30',native_session='2019-01-31',
        native_term_sha256='53de6f69b2b4f8071a785b84cf9fa697da8c8b098db2227b8e0b48b7e9c23919',parent_positions=[])],
    additional_rows=[dict(ticker='TWLO',security_id='361746987237610562',session='2019-02-01',
        source_observation_sha256='9d1d9eeb1363f4226fa7789a982a35ec3bb738f92d65a398b1208aca68df1107',parent_positions=[])])
EXTRA_WITNESS_SCOPES[('P05', '2020-11-30')] = {'additional_rows': [{'parent_positions': [], 'security_id': '314959357206229827', 'session': '2021-01-04', 'source_observation_sha256': 'a1f7b152918eff73069646585c491b5dc89fc381a79e3808cf59cffaad6fcf54', 'ticker': 'BLDR'}], 'parent_cursor': '2020-11-30', 'parent_outer_sha256': '8043fc8fb8915fbd14bb69834f905d0bf217fc06027f0283f816f064235f443c', 'terms': [{'native_session': '2020-12-31', 'native_term_sha256': '9a81db8dd2d4cce361f65bea04e15e7c9b311d8c035b84cb310fcd8e547e2c27', 'parent_positions': [], 'security_id': '344954105397997801', 'session': '2020-12-30', 'ticker': 'BMCH'}]}
EXTRA_WITNESS_SCOPES[('P06', '2020-02-28')] = {'parent_cursor': '2020-02-28', 'parent_outer_sha256': '129e006cdcb66fe02dbe443560b7fbcc09c48acae521a781915efbce3ad1b194', 'terms': [{'native_session': '2020-03-27', 'native_term_sha256': '9a5c400fd2d72a73e3a4765f8e76b2cca33a5d10d8aefe9357a6b0b323b7dc83', 'parent_positions': [], 'security_id': '879124841538592826', 'session': '2020-03-26', 'ticker': 'WAAS'}]}
EXTRA_WITNESS_SCOPES[('P03', '2019-05-31')] = {'parent_cursor': '2019-05-31', 'parent_outer_sha256': '4fc061018ff0ea13600136b4ca24351e82bc20aed894a32c417a9f696a3339da', 'terms': [{'native_session': '2019-06-11', 'native_term_sha256': '505e48955faf2f4b469b28a92d3aa1c9027fe340f231f2de0ecf34942d2c8eb6', 'parent_positions': [], 'security_id': '1113120724624398950', 'session': '2019-06-10', 'ticker': 'KEYW'}]}
EXTRA_WITNESS_SCOPES[('P03', '2019-05-31-seven-ordinary')] = {'additional_rows': [{'parent_positions': [], 'security_id': '821698168806940222', 'session': '2019-07-01', 'source_observation_sha256': 'f4ae045ec2ef53ceba3ca9e1c6d581f9bb73f8dfa758b9381b83884addf3be79', 'ticker': 'LHX'}, {'parent_positions': [], 'security_id': '344177561147922007', 'session': '2019-08-01', 'source_observation_sha256': 'a181e7804abf0e7bf89e15659da8a91facd0c0c38515c70fd00c7f1e84c02dc0', 'ticker': 'CRM'}, {'parent_positions': [], 'security_id': '707661213264749628', 'session': '2019-08-01', 'source_observation_sha256': 'b915d775f6a2f7f1db61a13bdc8c36ff43f2af4de44ff98473259947f884c79d', 'ticker': 'TCF'}], 'parent_cursor': '2019-05-31', 'parent_outer_sha256': '4fc061018ff0ea13600136b4ca24351e82bc20aed894a32c417a9f696a3339da', 'terms': [{'native_session': '2019-06-28', 'native_term_sha256': '5d5d2d1fa84cd9783e53ed4308d182d04cd259136439c271abd0219fbcb20a50', 'parent_positions': [], 'security_id': '149209101404250271', 'session': '2019-06-27', 'ticker': 'LLL1'}, {'native_session': '2019-07-30', 'native_term_sha256': 'a41cf151c67df6b11edc3229d57f7e209a0ceb9d214f0cd6a0a2cf50698c39aa', 'parent_positions': [], 'security_id': '331866698645518730', 'session': '2019-07-29', 'ticker': 'ARRY1'}, {'native_session': '2019-07-31', 'native_term_sha256': '1cbaa93baf604a9c04c0c15ce0d82c14bc8ee0c8e0f94ee1fd2bd2b767af2243', 'parent_positions': [], 'security_id': '1043452212170571060', 'session': '2019-07-30', 'ticker': 'DATA'}, {'native_session': '2019-07-31', 'native_term_sha256': 'a643cdb5e4484ea5cd816b365bc7b3278854fa0e3d9920c3c3d72bce169578c3', 'parent_positions': [], 'security_id': '216684274153477700', 'session': '2019-07-30', 'ticker': 'TCF1'}, {'native_session': '2019-07-31', 'native_term_sha256': '420af78438f9dd3a4f88e776c83ab59350468fa92fdd7e09ca1d68813e08c0ac', 'parent_positions': [], 'security_id': '261788311002817744', 'session': '2019-07-30', 'ticker': 'CTRL'}, {'native_session': '2019-07-31', 'native_term_sha256': '4511b20717491d24a41ead44087815477a69bf4ce95f50dee21be5a0c6c42be8', 'parent_positions': [], 'security_id': '3393863893051950', 'session': '2019-07-30', 'ticker': 'UQM'}, {'native_session': '2019-08-06', 'native_term_sha256': '01b5eec64d7faee41d44f16ac01d7324652b8e8ad20fbe4f9de5093e721c9c4a', 'parent_positions': [], 'security_id': '268110096969655215', 'session': '2019-08-05', 'ticker': 'BKS'}]}
EXTRA_WITNESS_SCOPES[('P03', '2019-09-30-CBLK-MDCO-ARQL')] = {'parent_cursor': '2019-09-30', 'parent_outer_sha256': 'a685ba1c6d4d0c6401f974cb681f02c08bb477e9498f468a6224dffa0d0184f0', 'terms': [{'native_session': '2019-10-07', 'native_term_sha256': 'bc11617318adfe6fa2f2b9d4d5fa2fdf1b302adc31bfe89ef0191d08dc25ab9b', 'parent_positions': [], 'security_id': '325066623134917949', 'session': '2019-10-04', 'ticker': 'CBLK'}, {'native_session': '2020-01-03', 'native_term_sha256': 'ca502fd6aa774d0e1c671f4d1996c82335eedd337d69e97c72fe78806f6ee4ff', 'parent_positions': [], 'security_id': '1000604417782241778', 'session': '2020-01-02', 'ticker': 'MDCO'}, {'native_session': '2020-01-15', 'native_term_sha256': 'f3ed4f220db858a202c05a3efc4b1e16a55ee6be33ff580a23fb2a28129a8e1c', 'parent_positions': [], 'security_id': '37487278358102709', 'session': '2020-01-14', 'ticker': 'ARQL'}]}
_distribution_scope_raw = (HERE / 'system-campaign-compound-source-witness-scopes.json').read_bytes()
need(sha(_distribution_scope_raw) == '558d3b70ec1ed24ad349ebc1d126f05b40fcb47acb44d690b982c4b382f21925',
     'SOURCE_DISTRIBUTION_EXACT_REGISTERED_SCOPE_CATALOG')
DISTRIBUTION_WITNESS_SCOPES = json.loads(_distribution_scope_raw)['scopes']
EXTRA_WITNESS_SCOPES['P06', '2020-06-30'] = {'parent_outer_sha256': '67f3063f3fd68a79dd83189fb1c29173dda651fe399f235272d019f486c2fbb1', 'parent_cursor': '2020-06-30', 'terms': [{'ticker': 'LM', 'security_id': '986298677409235360', 'session': '2020-07-29', 'native_session': '2020-07-30', 'native_term_sha256': '6b60c2374934a08916f197cd917df1a40074fe15818797d6d02b4c942d07917d', 'parent_positions': [{'slot_id': 21, 'ticker': 'LM', 'quantity': 35, 'entry_date': '2020-04-02'}]}]}
EXTRA_WITNESS_SCOPES['P05', '2021-03-31'] = {'parent_outer_sha256': '57fc54933459d897d290094c7cb3b9c1c5d1195ff2dd1eea182284941302070a', 'parent_cursor': '2021-03-31', 'terms': [{'ticker': 'APHA', 'security_id': '1056418588994492299', 'session': '2021-04-29', 'native_session': '2021-04-30', 'native_term_sha256': '31b315bf0ae426ae1216fb3fa44dc6d4d084313ce05786b4c7b2082a62b5f6bb', 'parent_positions': []}, {'ticker': 'CATM', 'security_id': '1127660475946542495', 'session': '2021-06-17', 'native_session': '2021-06-18', 'native_term_sha256': '070bed00fbafec28dd4c16c22728f6655e10bb1c1f67468bc06265bb33acb8cc', 'parent_positions': []}, {'ticker': 'AZPN1', 'security_id': '223345417151181882', 'session': '2022-05-13', 'native_session': '2022-05-16', 'native_term_sha256': '79fc7e1f6db87e47b08a3dcbd746b92021c7d9d7627a9bf1473605be4e00608a', 'parent_positions': []}, {'ticker': 'REGI', 'security_id': '1012599037173653936', 'session': '2022-06-09', 'native_session': '2022-06-10', 'native_term_sha256': 'db8331a6239b9aadba37604efb31c8e0cec398a975859cd376bc8a7c53ffb619', 'parent_positions': []}, {'ticker': 'PLAN', 'security_id': '621163045039428157', 'session': '2022-06-17', 'native_session': '2022-06-21', 'native_term_sha256': 'dd03d1787c5e048af217a9f9313ea4347123dd290c0ee01feac24811b68c89e6', 'parent_positions': []}], 'additional_rows': [{'ticker': 'TLRY', 'security_id': '653423826172679659', 'session': '2021-05-03', 'source_observation_sha256': '73ba6d30c2699f8c1ca3c416aa072f1853fff0dd274a0f3d1fb405e080894984', 'parent_positions': []}, {'ticker': 'AZPN', 'security_id': '556944515102158299', 'session': '2022-05-17', 'source_observation_sha256': 'd8a2d9bb914c9888e9f0b9ad238ddb597830ff2e12a0277c9776e6895b95ad95', 'parent_positions': []}]}
EXTRA_WITNESS_SCOPES['P11', '2025-06-30'] = {'parent_cursor': '2025-06-30', 'parent_outer_sha256': '1544d979c23b8827783bbccf6dbf5b4184f1df0fcaded5f630fcd18109737c7c', 'terms': [{'native_session': '2025-07-24', 'native_term_sha256': 'd64927eb0e80aa8e0a5e596cb60a510b45896548ea33f082442ae8a7a9a40580', 'parent_positions': [{'entry_date': '2025-04-04', 'quantity': 206, 'slot_id': 3, 'ticker': 'TGI'}], 'security_id': '498918945550351909', 'session': '2025-07-23', 'ticker': 'TGI'}]}
EXTRA_WITNESS_SCOPES['P06', '2021-03-31'] = {'parent_outer_sha256': '41eb70aa3f3feab4190426a9b17e0ea3f20499607ccfa1e4e86d39c309355246', 'parent_cursor': '2021-03-31', 'terms': [{'ticker': 'IPHI', 'security_id': '417303318744640788', 'session': '2021-04-19', 'native_session': '2021-04-20', 'native_term_sha256': '784f0b044d83705dd144f20dda7dc87392ce7567336185b84d49811aabf2f518', 'parent_positions': [{'slot_id': 7, 'ticker': 'IPHI', 'quantity': 23, 'entry_date': '2020-03-30'}]}, {'ticker': 'MIK', 'security_id': '350829412574453923', 'session': '2021-04-13', 'native_session': '2021-04-14', 'native_term_sha256': '92b5b048e834f32ec0b4b8679cbace152ec986b064e5d0637c80a937ea472202', 'parent_positions': []}, {'ticker': 'VAR', 'security_id': '258412215698403601', 'session': '2021-04-13', 'native_session': '2021-04-14', 'native_term_sha256': 'a184b667de19c35ba2c9a3ba3e1b80e0e132ef9c20d6bae283ef5d5644fde7d8', 'parent_positions': []}, {'ticker': 'NAV', 'security_id': '515332170991709358', 'session': '2021-06-29', 'native_session': '2021-06-30', 'native_term_sha256': '87224dc2937f8eba47e669e77e4f4ad676c56da6102f9975987482009709b621', 'parent_positions': []}, {'ticker': 'WORK', 'security_id': '753795210944150814', 'session': '2021-07-19', 'native_session': '2021-07-20', 'native_term_sha256': 'c14243b48f1f69a67752c093015abd9f415c235fe78c0802383c961b3600891b', 'parent_positions': []}, {'ticker': 'HOME', 'security_id': '914962085458002202', 'session': '2021-07-21', 'native_session': '2021-07-22', 'native_term_sha256': '7d3c8178c314fbdc8ae67722803989e46fa94e91c9843a2fe15602bd2823ac97', 'parent_positions': []}, {'ticker': 'TRIL1', 'security_id': '1119755750402433659', 'session': '2021-11-15', 'native_session': '2021-11-16', 'native_term_sha256': '5057f8ad3fa88626ef5f2898847655a461bc8cea4c2d09270e199716b365dd43', 'parent_positions': []}, {'ticker': 'APHA', 'security_id': '1056418588994492299', 'session': '2021-04-29', 'native_session': '2021-04-30', 'native_term_sha256': '31b315bf0ae426ae1216fb3fa44dc6d4d084313ce05786b4c7b2082a62b5f6bb', 'parent_positions': []}, {'ticker': 'CATM', 'security_id': '1127660475946542495', 'session': '2021-06-17', 'native_session': '2021-06-18', 'native_term_sha256': '070bed00fbafec28dd4c16c22728f6655e10bb1c1f67468bc06265bb33acb8cc', 'parent_positions': []}, {'ticker': 'AZPN1', 'security_id': '223345417151181882', 'session': '2022-05-13', 'native_session': '2022-05-16', 'native_term_sha256': '79fc7e1f6db87e47b08a3dcbd746b92021c7d9d7627a9bf1473605be4e00608a', 'parent_positions': []}, {'ticker': 'REGI', 'security_id': '1012599037173653936', 'session': '2022-06-09', 'native_session': '2022-06-10', 'native_term_sha256': 'db8331a6239b9aadba37604efb31c8e0cec398a975859cd376bc8a7c53ffb619', 'parent_positions': []}, {'ticker': 'PLAN', 'security_id': '621163045039428157', 'session': '2022-06-17', 'native_session': '2022-06-21', 'native_term_sha256': 'dd03d1787c5e048af217a9f9313ea4347123dd290c0ee01feac24811b68c89e6', 'parent_positions': []}], 'additional_rows': [{'ticker': 'MRVL', 'security_id': '522595530457156829', 'session': '2021-04-21', 'source_observation_sha256': 'f99c5f4ff4a4e92c5e232c27415a753b3de1815f9c6082a73a022b0289e61a2e', 'parent_positions': []}, {'ticker': 'CRM', 'security_id': '344177561147922007', 'session': '2021-07-21', 'source_observation_sha256': '70753ee913170ae7225f51d3954c0700ade85cb67dc8fceeecf968407ff802eb', 'parent_positions': []}, {'ticker': 'TLRY', 'security_id': '653423826172679659', 'session': '2021-05-03', 'source_observation_sha256': '73ba6d30c2699f8c1ca3c416aa072f1853fff0dd274a0f3d1fb405e080894984', 'parent_positions': []}, {'ticker': 'AZPN', 'security_id': '556944515102158299', 'session': '2022-05-17', 'source_observation_sha256': 'd8a2d9bb914c9888e9f0b9ad238ddb597830ff2e12a0277c9776e6895b95ad95', 'parent_positions': []}]}
EXTRA_WITNESS_SCOPES[('P05', '2021-10-29')] = {'additional_rows': [], 'parent_cursor': '2021-10-29', 'parent_outer_sha256': 'f3d33cdafa7e3d8ab1df03c7be59d3f56c69fbdf1b0e063a467dd5a22fcdb848', 'terms': [{'native_session': '2021-11-29', 'native_term_sha256': '93470bf15871ab34659f8452d9d4bfa96242d8eee58bff2d5918d9f28c824447', 'parent_positions': [], 'security_id': '1123376669724901530', 'session': '2021-11-26', 'ticker': 'UFS'}, {'native_session': '2021-12-27', 'native_term_sha256': 'd45db785ce4ce0fdad553a53b34f1426666de01e076b9e2e841b6b199b8049dd', 'parent_positions': [], 'security_id': '1112840042710916617', 'session': '2021-12-23', 'ticker': 'COR2'}, {'native_session': '2021-12-27', 'native_term_sha256': '8d9afe459a7f4253f3c1f489449c0b835ca6de6fae45120ab733ce5a304ae554', 'parent_positions': [], 'security_id': '241515261501228040', 'session': '2021-12-23', 'ticker': 'DRNA'}, {'native_session': '2022-03-11', 'native_term_sha256': 'afccf7b8698e0c04849091bc7f7f3a7758595cf52fa775a37f22e040cad3b6bb', 'parent_positions': [], 'security_id': '1028361513614760286', 'session': '2022-03-10', 'ticker': 'ARNA'}, {'native_session': '2022-05-13', 'native_term_sha256': '5eb674cff87d9baba04ab103475f0bccc7fef9ba1dcfb03d476ae6a7c20a80f4', 'parent_positions': [], 'security_id': '302828589827843603', 'session': '2022-05-12', 'ticker': 'EPAY'}, {'native_session': '2022-10-19', 'native_term_sha256': 'f1c92007dac927423e7703ac280ca4de869a7b275b323e127b7b6e0c5f9c6dca', 'parent_positions': [], 'security_id': '659896685009177378', 'session': '2022-10-18', 'ticker': 'CCXI1'}, {'native_session': '2023-11-07', 'native_term_sha256': '23d0dfe7e1d209f84a68c666878673381b1748f10a891edcd9a00ad55f66b6c0', 'parent_positions': [], 'security_id': '333926898180811276', 'session': '2023-11-06', 'ticker': 'NEWR'}, {'native_session': '2024-02-09', 'native_term_sha256': 'c09607c58f8ec9489f838f63ff6527059c755d2cdf9438f5925f8d8a496951b5', 'parent_positions': [], 'security_id': '170441452346015322', 'session': '2024-02-08', 'ticker': 'IMGN'}, {'native_session': '2024-12-17', 'native_term_sha256': '3271de7e17ba66ccba86e074949c81af628173cc56a19774ced304bedd7669ba', 'parent_positions': [], 'security_id': '926139522403724450', 'session': '2024-12-16', 'ticker': 'CTLT'}]}
EXTRA_WITNESS_SCOPES[('P11', '2026-02-27')] = {'additional_rows': [], 'parent_cursor': '2026-02-27', 'parent_outer_sha256': '29fe6110159e24934ea521d15d72ff6c4d08d2b3e4c7bf904ebd1fb5b377ceb4', 'terms': [{'native_session': '2026-03-20', 'native_term_sha256': '689adccb69cd2f499298678e43c60d83e73de51f1af1ba8f4de739aabc85ccbd', 'parent_positions': [{'entry_date': '2026-02-10', 'quantity': 79, 'slot_id': 13, 'ticker': 'EXAS'}], 'security_id': '637262944715750985', 'session': '2026-03-19', 'ticker': 'EXAS'}]}
EXTRA_WITNESS_SCOPES[('P03', '2019-09-30-ALDR-and-2020-originals')] = {'additional_rows': [{'parent_positions': [], 'security_id': '13062188894457483', 'session': '2020-02-06', 'source_observation_sha256': 'a08bf595ba2f598f4c96fe0d0459185920cdbffc52f189216045f3f77f7720a3', 'ticker': 'TMHC'}, {'parent_positions': [], 'security_id': '314959357206229827', 'session': '2021-01-04', 'source_observation_sha256': 'a1f7b152918eff73069646585c491b5dc89fc381a79e3808cf59cffaad6fcf54', 'ticker': 'BLDR'}, {'parent_positions': [], 'security_id': '36692955301160544', 'session': '2020-04-01', 'source_observation_sha256': '50b9829cb66fd616b7cab6f886bed61f3afd8facdf887d129fb171ea07423bf1', 'ticker': 'TMUS'}], 'parent_cursor': '2019-09-30', 'parent_outer_sha256': 'a685ba1c6d4d0c6401f974cb681f02c08bb477e9498f468a6224dffa0d0184f0', 'terms': [{'native_session': '2019-10-21', 'native_term_sha256': 'd42b9821ced47a846ecdc78c47e7513cdc81bc8cb1629090cae78f8f97c668d6', 'parent_positions': [], 'security_id': '941065113449292610', 'session': '2019-10-18', 'ticker': 'ALDR'}, {'native_session': '2020-02-05', 'native_term_sha256': '431c662cb0a1bc988bc0db33c4f08e0a1037112ab6ac900c0930381af2f38181', 'parent_positions': [], 'security_id': '355892456681242666', 'session': '2020-02-04', 'ticker': 'WLH'}, {'native_session': '2020-03-27', 'native_term_sha256': '9a5c400fd2d72a73e3a4765f8e76b2cca33a5d10d8aefe9357a6b0b323b7dc83', 'parent_positions': [], 'security_id': '879124841538592826', 'session': '2020-03-26', 'ticker': 'WAAS'}, {'native_session': '2020-03-31', 'native_term_sha256': '19de7e96860750033acdad9dbf88ae9471f95a6abfc65047f398cbe932e889a5', 'parent_positions': [], 'security_id': '957008674074369745', 'session': '2020-03-30', 'ticker': 'S2'}, {'native_session': '2020-04-16', 'native_term_sha256': '4745eb950f7793984bd07b0bec1d77f7d7281e0e7b1406ff1927f66aade35afb', 'parent_positions': [], 'security_id': '66103160004367746', 'session': '2020-04-15', 'ticker': 'CY'}, {'native_session': '2020-04-24', 'native_term_sha256': 'cacb190ef70a64f296e675e382cbd7d5ea3a4ffe54b908992827b7ab7ff324ea', 'parent_positions': [], 'security_id': '597162481941536532', 'session': '2020-04-23', 'ticker': 'MLNX'}, {'native_session': '2020-05-28', 'native_term_sha256': 'f7141a474101c3787b9ebf4ff76bc4f1aa3f43337e43f501743805f0d0d9eeda', 'parent_positions': [], 'security_id': '384188467071429790', 'session': '2020-05-27', 'ticker': 'WBC'}, {'native_session': '2020-07-30', 'native_term_sha256': '6b60c2374934a08916f197cd917df1a40074fe15818797d6d02b4c942d07917d', 'parent_positions': [], 'security_id': '986298677409235360', 'session': '2020-07-29', 'ticker': 'LM'}, {'native_session': '2020-09-30', 'native_term_sha256': '33f886da0ae216c99de493cb3db5a849d18f11a6b3a7b600fde5644aab7afc5a', 'parent_positions': [], 'security_id': '510659411298086546', 'session': '2020-09-29', 'ticker': 'MNTA'}, {'native_session': '2020-10-12', 'native_term_sha256': '3fb89333ef204d5bded06009c3e2f1ef7c9b550818d8b1ff21abb85ffd9d19a7', 'parent_positions': [], 'security_id': '557908413825257346', 'session': '2020-10-09', 'ticker': 'AIMT'}, {'native_session': '2020-10-22', 'native_term_sha256': '16dc36e02a1191dc3674bda1667d57e761df0582e29df74263daf3122260f4ac', 'parent_positions': [], 'security_id': '158295011127936997', 'session': '2020-10-21', 'ticker': 'IMMU'}, {'native_session': '2020-11-16', 'native_term_sha256': 'e63adffc3e0218fdf41fbca1981d3c6f51797aedf0352d7d57c99b527c93eb9c', 'parent_positions': [], 'security_id': '6711969151821433', 'session': '2020-11-13', 'ticker': 'MYOK'}, {'native_session': '2020-12-31', 'native_term_sha256': '9a81db8dd2d4cce361f65bea04e15e7c9b311d8c035b84cb310fcd8e547e2c27', 'parent_positions': [], 'security_id': '344954105397997801', 'session': '2020-12-30', 'ticker': 'BMCH'}]}
EXTRA_WITNESS_SCOPES[('P07', '2022-02-28')] = {'additional_rows': [{'parent_positions': [], 'security_id': '732226698577723721', 'session': '2022-03-04', 'source_observation_sha256': '36e364a2773bd5a9754ae3c9eb4eac9f5c963890532add4f96978b9626158ef3', 'ticker': 'ZGNX'}, {'parent_positions': [], 'security_id': '652370478798714876', 'session': '2022-10-18', 'source_observation_sha256': '1c697983440ac118e35f9ae4027795d36f27a75243307b036647d6e1a2358ec9', 'ticker': 'AVLR'}, {'parent_positions': [], 'security_id': '321650252292096156', 'session': '2022-10-13', 'source_observation_sha256': 'f229d49f15efef81e7dbe9b9f5c08f95087a024c69a486f2b43eec40ca20f172', 'ticker': 'FMTX'}, {'parent_positions': [], 'security_id': '23427772744584579', 'session': '2022-10-17', 'source_observation_sha256': 'c84a4fc7c86d6723d8e35b5feb7a4258985340d49504a4dec3b6a2f695fd28a4', 'ticker': 'PING'}, {'parent_positions': [], 'security_id': '683977592320274232', 'session': '2022-10-18', 'source_observation_sha256': 'a640bbaaa29de8ed34a014f0ce1ff2404a50828c16bb08871cfbe5367797975b', 'ticker': 'Y'}, {'parent_positions': [], 'security_id': '870865871230451373', 'session': '2022-11-21', 'source_observation_sha256': '96b74840274797ebadf6cfcf793825dad254223828c16c8247ccae63821015f0', 'ticker': 'ZEN'}], 'parent_cursor': '2022-02-28', 'parent_outer_sha256': 'd4845ce85600d202fe99e3a67bc7241c14c93279edd51992fea0db0b5a19b058', 'terms': [{'native_session': '2022-03-04', 'native_term_sha256': '34fa057e5cca33a2885a6b2025c0ebde09f03a6f8ab2371fa5136b67c7b1fcb7', 'parent_positions': [], 'security_id': '732226698577723721', 'session': '2022-03-03', 'ticker': 'ZGNX'}, {'native_session': '2022-05-18', 'native_term_sha256': '1ea2abbb8cd4e10bae112ca8aaa7cd87822db91afbcaaa52ad6da417b8c4d0d6', 'parent_positions': [], 'security_id': '988236261397113691', 'session': '2022-05-17', 'ticker': 'MIME'}, {'native_session': '2022-11-03', 'native_term_sha256': '4284b79a3b3954191aa59af15c07a06e626cb2340fc4834100ec506631670ef1', 'parent_positions': [], 'security_id': '738630690199421979', 'session': '2022-11-02', 'ticker': 'CYBE'}, {'native_session': '2022-10-18', 'native_term_sha256': '10943a680bf8b4a98575225ee89ecabce5e8ed3bf066ed318e8ef5db55d5bc5f', 'parent_positions': [], 'security_id': '652370478798714876', 'session': '2022-10-17', 'ticker': 'AVLR'}, {'native_session': '2022-10-13', 'native_term_sha256': '520764575d781727341e687841e205e9404aff6726da7de2bc8e58a9864d18d4', 'parent_positions': [], 'security_id': '321650252292096156', 'session': '2022-10-12', 'ticker': 'FMTX'}, {'native_session': '2022-10-17', 'native_term_sha256': 'b1481b42046cb67003a896150c6f7f9b28910b29f1b5a53ec35ef219bd4a78f0', 'parent_positions': [], 'security_id': '23427772744584579', 'session': '2022-10-14', 'ticker': 'PING'}, {'native_session': '2022-10-18', 'native_term_sha256': 'a32a8b2e023dedf84185a5b7d3847b546bc29f0ff99b0186c05019dd91d9ab90', 'parent_positions': [], 'security_id': '683977592320274232', 'session': '2022-10-17', 'ticker': 'Y'}, {'native_session': '2022-11-21', 'native_term_sha256': '4eb6cbadfb1fd10a87741ed05f2e3d7025700280835e49f4f838d071b0600dd2', 'parent_positions': [], 'security_id': '870865871230451373', 'session': '2022-11-18', 'ticker': 'ZEN'}]}
EXTRA_WITNESS_SCOPES['P06', '2022-04-29'] = {'parent_outer_sha256': '7edc9c1ea24c4c353ae50644ff7423f1f7f23f18f0cf2135050c0e360220ecde', 'parent_cursor': '2022-04-29', 'terms': [{'ticker': 'XENT', 'security_id': '948589239641460025', 'session': '2022-05-11', 'native_session': '2022-05-12', 'native_term_sha256': '7ec878d790620777a8e43b53ee60903959627938b58e36397560051d5eacb03f', 'parent_positions': []}, {'ticker': 'EPAY', 'security_id': '302828589827843603', 'session': '2022-05-12', 'native_session': '2022-05-13', 'native_term_sha256': '5eb674cff87d9baba04ab103475f0bccc7fef9ba1dcfb03d476ae6a7c20a80f4', 'parent_positions': []}, {'ticker': 'MIME', 'security_id': '988236261397113691', 'session': '2022-05-17', 'native_session': '2022-05-18', 'native_term_sha256': '1ea2abbb8cd4e10bae112ca8aaa7cd87822db91afbcaaa52ad6da417b8c4d0d6', 'parent_positions': [{'slot_id': 26, 'ticker': 'MIME', 'quantity': 38, 'entry_date': '2022-04-01'}]}, {'ticker': 'FMTX', 'security_id': '321650252292096156', 'session': '2022-10-12', 'native_session': '2022-10-13', 'native_term_sha256': '520764575d781727341e687841e205e9404aff6726da7de2bc8e58a9864d18d4', 'parent_positions': []}, {'ticker': 'PING', 'security_id': '23427772744584579', 'session': '2022-10-14', 'native_session': '2022-10-17', 'native_term_sha256': 'b1481b42046cb67003a896150c6f7f9b28910b29f1b5a53ec35ef219bd4a78f0', 'parent_positions': []}, {'ticker': 'AVLR', 'security_id': '652370478798714876', 'session': '2022-10-17', 'native_session': '2022-10-18', 'native_term_sha256': '10943a680bf8b4a98575225ee89ecabce5e8ed3bf066ed318e8ef5db55d5bc5f', 'parent_positions': []}, {'ticker': 'Y', 'security_id': '683977592320274232', 'session': '2022-10-17', 'native_session': '2022-10-18', 'native_term_sha256': 'a32a8b2e023dedf84185a5b7d3847b546bc29f0ff99b0186c05019dd91d9ab90', 'parent_positions': []}, {'ticker': 'CCXI1', 'security_id': '659896685009177378', 'session': '2022-10-18', 'native_session': '2022-10-19', 'native_term_sha256': 'f1c92007dac927423e7703ac280ca4de869a7b275b323e127b7b6e0c5f9c6dca', 'parent_positions': []}, {'ticker': 'CYBE', 'security_id': '738630690199421979', 'session': '2022-11-02', 'native_session': '2022-11-03', 'native_term_sha256': '4284b79a3b3954191aa59af15c07a06e626cb2340fc4834100ec506631670ef1', 'parent_positions': []}, {'ticker': 'ZEN', 'security_id': '870865871230451373', 'session': '2022-11-18', 'native_session': '2022-11-21', 'native_term_sha256': '4eb6cbadfb1fd10a87741ed05f2e3d7025700280835e49f4f838d071b0600dd2', 'parent_positions': []}], 'additional_rows': [{'ticker': 'FMTX', 'security_id': '321650252292096156', 'session': '2022-10-13', 'source_observation_sha256': 'f229d49f15efef81e7dbe9b9f5c08f95087a024c69a486f2b43eec40ca20f172', 'parent_positions': []}, {'ticker': 'PING', 'security_id': '23427772744584579', 'session': '2022-10-17', 'source_observation_sha256': 'c84a4fc7c86d6723d8e35b5feb7a4258985340d49504a4dec3b6a2f695fd28a4', 'parent_positions': []}, {'ticker': 'AVLR', 'security_id': '652370478798714876', 'session': '2022-10-18', 'source_observation_sha256': '1c697983440ac118e35f9ae4027795d36f27a75243307b036647d6e1a2358ec9', 'parent_positions': []}, {'ticker': 'Y', 'security_id': '683977592320274232', 'session': '2022-10-18', 'source_observation_sha256': 'a640bbaaa29de8ed34a014f0ce1ff2404a50828c16bb08871cfbe5367797975b', 'parent_positions': []}, {'ticker': 'ZEN', 'security_id': '870865871230451373', 'session': '2022-11-21', 'source_observation_sha256': '96b74840274797ebadf6cfcf793825dad254223828c16c8247ccae63821015f0', 'parent_positions': []}]}
EXTRA_WITNESS_SCOPES[('P11', '2026-04-30')] = {'additional_rows': [{'parent_positions': [{'entry_date': '2026-04-29', 'quantity': 157, 'slot_id': 19, 'ticker': 'TERN'}], 'security_id': '961294553911856115', 'session': '2026-05-04', 'source_observation_sha256': '23bdb30afab068f1c152f1843abf6ba4f453789a37a43d9df9645abfe6a1f3f1', 'ticker': 'TERN'}], 'parent_cursor': '2026-04-30', 'parent_outer_sha256': '6455483fb3a6c6e765ba75cc00c5468d1d95a3866f59643c19fffef530ac52a4', 'terms': [{'native_session': '2026-05-04', 'native_term_sha256': 'ee9a9ee8b82e907c6b0024834ae9e9ac4aef4341358e57556926fa955e0139d0', 'parent_positions': [{'entry_date': '2026-04-29', 'quantity': 157, 'slot_id': 19, 'ticker': 'TERN'}], 'security_id': '961294553911856115', 'session': '2026-05-01', 'ticker': 'TERN'}]}
EXTRA_WITNESS_SCOPES[('P05', '2021-11-30')] = {'additional_rows': [], 'parent_cursor': '2021-11-30', 'parent_outer_sha256': 'c720960dc19f452d8a67e72a13e8caefd4374fbf3a7610fc4d2e21f865c940e6', 'terms': [{'native_session': '2021-12-01', 'native_term_sha256': 'c0415c1aa5fc0a0205ade497e308f194d403687c8db4c77cd413da22a21748b8', 'parent_positions': [], 'security_id': '1072510367992802359', 'session': '2021-11-30', 'ticker': 'MDP'}]}
EXTRA_WITNESS_SCOPES[('P06', '2022-11-30')] = {'additional_rows': [], 'parent_cursor': '2022-11-30', 'parent_outer_sha256': '615f8daa736504d3ee8f9c17515e6fc4d014fd4f5a2fa4bd5e1af640249c942f', 'terms': [{'native_session': '2022-12-15', 'native_term_sha256': '88fc01228c4183c26a1eb963e38d251081453f2bc8acf89d30315309b7376a6a', 'parent_positions': [{'entry_date': '2022-11-07', 'quantity': 82, 'slot_id': 0, 'ticker': 'TRQ'}], 'security_id': '655209666181687436', 'session': '2022-12-14', 'ticker': 'TRQ'}]}
EXTRA_WITNESS_SCOPES[('P03', '2019-10-31')] = {'additional_rows': [], 'parent_cursor': '2019-10-31', 'parent_outer_sha256': 'e229d73086f5c907ebff065be97c9a8eb090520a6dc3a55e6a1649c1e3efd3fd', 'terms': [{'native_session': '2019-11-12', 'native_term_sha256': 'f2b36754d579bab94b67cc9628f9e32cd927189466c99c428b7c1ca977dfd41f', 'parent_positions': [], 'security_id': '471435039050105714', 'session': '2019-11-11', 'ticker': 'DOVA'}]}
EXTRA_WITNESS_SCOPES[('P05', '2021-11-30-seven-next-cash-natives')] = {'additional_rows': [], 'parent_cursor': '2021-11-30', 'parent_outer_sha256': 'c720960dc19f452d8a67e72a13e8caefd4374fbf3a7610fc4d2e21f865c940e6', 'terms': [{'ticker': 'CXP', 'security_id': '505590033806659541', 'session': '2021-12-06', 'native_session': '2021-12-07', 'native_term_sha256': '7ae3331e4bbb3f576ebfcaa0dcc8b2f8aa2f01bbb3db77d42f4b3bdaf5a319ba', 'parent_positions': []}, {'ticker': 'HRC', 'security_id': '413759046550141969', 'session': '2021-12-09', 'native_session': '2021-12-10', 'native_term_sha256': '0cf0409fa93cc7a8c9c81009dcd246591846fbf9237f4ed06bcac1377d937969', 'parent_positions': []}, {'ticker': 'MGLN', 'security_id': '644546217848577516', 'session': '2021-12-31', 'native_session': '2022-01-03', 'native_term_sha256': 'b26916c7396760a17752c7bd49f128bf9b14d5accb27cd5fec65a8e03a184c68', 'parent_positions': []}, {'ticker': 'PAE', 'security_id': '79288825945223775', 'session': '2022-02-11', 'native_session': '2022-02-14', 'native_term_sha256': '2b4f3b0dab1319948132dd10c96fbb2e9c0a554fcfaf37591c7a3a8bec11bf88', 'parent_positions': []}, {'ticker': 'RRD', 'security_id': '1103823526630607847', 'session': '2022-02-23', 'native_session': '2022-02-24', 'native_term_sha256': '54cb5fc3645c0609c5865e94630440723d96c3b4db6534cfedf5527db5d1eb8b', 'parent_positions': []}, {'ticker': 'MCFE', 'security_id': '150296277399646272', 'session': '2022-02-25', 'native_session': '2022-02-28', 'native_term_sha256': 'ac6da5b2c6724d36192f176d569ae1bcccb4e12e3f3544a1f274d176adb384c7', 'parent_positions': []}, {'ticker': 'NUAN', 'security_id': '631181427311568999', 'session': '2022-03-02', 'native_session': '2022-03-03', 'native_term_sha256': '5bc9ad32f70f91a5247f6ae8c5895c2fe4debd00886a0a849b221f14845f18cc', 'parent_positions': []}]}
EXTRA_WITNESS_SCOPES[('P06', '2022-11-30-remaining-original-cash-natives')] = {'parent_outer_sha256': '615f8daa736504d3ee8f9c17515e6fc4d014fd4f5a2fa4bd5e1af640249c942f', 'parent_cursor': '2022-11-30', 'terms': [{'ticker': 'ABMD', 'security_id': '1050970006012443443', 'session': '2022-12-20', 'native_session': '2022-12-21', 'native_term_sha256': '815f61b085dee89b89956834f250763522bff5402fdcc3d36ebb36c85d0796e4', 'parent_positions': []}, {'ticker': 'SJI', 'security_id': '255755003526074655', 'session': '2023-01-30', 'native_session': '2023-01-31', 'native_term_sha256': '3cdb7e9ae9227a2ff6d47e2e40240b74e8d10854ec1eb4591c5c2a039f2a72fb', 'parent_positions': []}, {'ticker': 'LHCG', 'security_id': '348961068556052300', 'session': '2023-02-17', 'native_session': '2023-02-21', 'native_term_sha256': 'b13c3cdc8ce1b9651108d79ca572c1a7f10aefa5a204c35fb1c8fbd28b3e3e37', 'parent_positions': []}, {'ticker': 'ONEM', 'security_id': '677864286983813096', 'session': '2023-02-21', 'native_session': '2023-02-22', 'native_term_sha256': '7930c9741ebd86ef403aa2c1f8a64e36a627c9db3bc4e3993fae29a438ca6d1d', 'parent_positions': []}, {'ticker': 'COUP', 'security_id': '840778708963135084', 'session': '2023-02-24', 'native_session': '2023-02-27', 'native_term_sha256': '23dcc826824e13c0137d03ff260ecac5fc4a79b0f945363946c9511ae6e567c7', 'parent_positions': []}, {'ticker': 'EVOP', 'security_id': '754975132000056845', 'session': '2023-03-22', 'native_session': '2023-03-23', 'native_term_sha256': '4ae01e26dfd27924a8973b40c79e755ff31adfba0be52e9ee9779fd8ca9679b3', 'parent_positions': []}, {'ticker': 'SGFY', 'security_id': '151225572607695758', 'session': '2023-03-27', 'native_session': '2023-03-28', 'native_term_sha256': 'b62f3cd219734387c09081d63dac7858e2b28ffd6f41ae29b39a9ebe0dcaa940', 'parent_positions': []}, {'ticker': 'CEMI', 'security_id': '1089594935488302817', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': 'c3fe2a1af242ed612fe1d9d7a4042bcde7a840011b1c2843c9227285f625101c', 'parent_positions': []}, {'ticker': 'CSII', 'security_id': '50040477475186027', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': '04260434a5ee3eccb4a082ab5f969d49790e8a76738cb3534260811cbd14cf58', 'parent_positions': []}, {'ticker': 'PRVB', 'security_id': '858933953652218125', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': '0425d032b38ebf0099beec0a7556f66368d3cba1a7ee82a455d28d3908331d39', 'parent_positions': []}, {'ticker': 'OSH', 'security_id': '917666101373510238', 'session': '2023-04-28', 'native_session': '2023-05-01', 'native_term_sha256': '3bfd185a3434b5e62dde7aa56683f1f9c82f61150541f8ae0871d0f2b16db450', 'parent_positions': []}, {'ticker': 'MAXR', 'security_id': '192029376284057522', 'session': '2023-05-01', 'native_session': '2023-05-02', 'native_term_sha256': '8165277eedd833036d96db039d1432df89514fc53800e6d5cd8f05c977efcd8b', 'parent_positions': []}, {'ticker': 'SUMO', 'security_id': '233469495168272142', 'session': '2023-05-10', 'native_session': '2023-05-11', 'native_term_sha256': 'cd4f6ea36d9e3a6475dcd9a6f34f93feefd20699f4df36992a4a6c1f9aad2a23', 'parent_positions': []}, {'ticker': 'TA', 'security_id': '273582270998538925', 'session': '2023-05-11', 'native_session': '2023-05-12', 'native_term_sha256': '77d6eedc0731bf0b61f05abbe341d3a6d0ededaff2b99f5f18efe6d7047bcff2', 'parent_positions': []}, {'ticker': 'MNTV', 'security_id': '62458272022348266', 'session': '2023-05-30', 'native_session': '2023-05-31', 'native_term_sha256': 'dc62d52a52598231f5a244624e60bca0f72789db27ccc30ddf212c568ec3f870', 'parent_positions': []}, {'ticker': 'MGI', 'security_id': '631714153765036714', 'session': '2023-05-30', 'native_session': '2023-05-31', 'native_term_sha256': '5d5e99a5c938874325db2c8ca83c2c8aaee2901eb86599b21a250fd6a4880b6c', 'parent_positions': []}, {'ticker': 'HSKA', 'security_id': '1132165486668118439', 'session': '2023-06-09', 'native_session': '2023-06-12', 'native_term_sha256': 'be6349194d300cb9195944599ddba0d2c80c0f3afbb7e22295d12033c20a5fe0', 'parent_positions': []}, {'ticker': 'RUTH', 'security_id': '129751434275280834', 'session': '2023-06-12', 'native_session': '2023-06-13', 'native_term_sha256': '882d416fd8b3dd611ec9d7c0c83b6b08d4499cffdd2a0e93d656fa5371e7c016', 'parent_positions': []}, {'ticker': 'CVT', 'security_id': '373813670584114036', 'session': '2023-06-13', 'native_session': '2023-06-14', 'native_term_sha256': 'edbc4944cd6c2348a4fc175801a4869a5b0f2bebd324701dad850720876eb002', 'parent_positions': []}, {'ticker': 'RXDX', 'security_id': '1140650572960055100', 'session': '2023-06-14', 'native_session': '2023-06-15', 'native_term_sha256': '47b894ab6a5b05ba753783dbe031d6ec14c47abd32a2db18bd0c529c5039c91c', 'parent_positions': []}, {'ticker': 'CTIC', 'security_id': '394927144545790620', 'session': '2023-06-22', 'native_session': '2023-06-23', 'native_term_sha256': '4a9acb1a7af4fccfbb8ba40f0c072130e4fb8215ee46caef40740fe3a5ba97e7', 'parent_positions': []}, {'ticker': 'XM', 'security_id': '348606319062466815', 'session': '2023-06-26', 'native_session': '2023-06-27', 'native_term_sha256': '131487cf7ccf68c542c39afe70909c80e6c445fc8bf83367c973f5f8b107eded', 'parent_positions': []}, {'ticker': 'ISEE', 'security_id': '477302961403569227', 'session': '2023-07-07', 'native_session': '2023-07-10', 'native_term_sha256': '670cd42f7b0bd828e76d5ac0f5b8e9f7e311271278275ce261efd8fe0e368c79', 'parent_positions': []}, {'ticker': 'LSI', 'security_id': '753641750484343508', 'session': '2023-07-18', 'native_session': '2023-07-19', 'native_term_sha256': 'ccb498dd580b7f803166463271de8bfb95d1c9f362efaa4f50c0398ed7fdf677', 'parent_positions': []}, {'ticker': 'AJRD', 'security_id': '721679296374852573', 'session': '2023-07-26', 'native_session': '2023-07-27', 'native_term_sha256': 'c18c68ef2a138d80a1bf1325d3ece4707e45c2bb6d51ea96a9a3c6dbb402237d', 'parent_positions': []}, {'ticker': 'UNVR', 'security_id': '220188358195861572', 'session': '2023-07-28', 'native_session': '2023-07-31', 'native_term_sha256': 'a268aa3d4745bff6faab92aac962c554b3d771849acb55a4b32479cddf72f047', 'parent_positions': []}, {'ticker': 'DICE', 'security_id': '349504371207456722', 'session': '2023-08-07', 'native_session': '2023-08-08', 'native_term_sha256': '38a801a52f9077b135500f4810995ad7ef957a5b4b7a5482d76478bef2104868', 'parent_positions': []}, {'ticker': 'KDNY', 'security_id': '47247117758471252', 'session': '2023-08-09', 'native_session': '2023-08-10', 'native_term_sha256': '8779121eb314297caa8a05ab20d8b3c5c990fe0849d21026d37e50dee95d4060', 'parent_positions': []}, {'ticker': 'ARNC', 'security_id': '814822139570731593', 'session': '2023-08-16', 'native_session': '2023-08-17', 'native_term_sha256': 'daf6fb3e9cf5d61d39b506306a9fc2694ea08dcde843fb6cbbc2e718adb01084', 'parent_positions': []}, {'ticker': 'FRG', 'security_id': '906280636792711059', 'session': '2023-08-17', 'native_session': '2023-08-18', 'native_term_sha256': 'f3c80eb81e56926df1d9d53c81ab4b84b82386d7cefed6814b61ae3b8cc11187', 'parent_positions': []}, {'ticker': 'FORG', 'security_id': '927598213803887960', 'session': '2023-08-21', 'native_session': '2023-08-22', 'native_term_sha256': '154b48f99dbae1e994a7633ecd833f93f76c00e28e3cdc1976fcee45b050fb04', 'parent_positions': []}, {'ticker': 'CFMS', 'security_id': '356455035813755306', 'session': '2023-08-31', 'native_session': '2023-09-01', 'native_term_sha256': 'aa3825d28c44a4b64c55a3b02a4cbbfef597ab48404d2a1e32f9486a2f9a2ec7', 'parent_positions': []}, {'ticker': 'QUOT', 'security_id': '823579734840521990', 'session': '2023-08-31', 'native_session': '2023-09-01', 'native_term_sha256': 'c5476a5065675eb10be41e3feeb1ea7e108e86f85408d066dcd31f6e17342d80', 'parent_positions': []}, {'ticker': 'WWE', 'security_id': '426024777347801008', 'session': '2023-09-08', 'native_session': '2023-09-11', 'native_term_sha256': 'aa99115df1cfdc59e142e6572adb258decc4adedefcb9815e5cce7dcb030c035', 'parent_positions': []}, {'ticker': 'RADI', 'security_id': '477309164594500719', 'session': '2023-09-19', 'native_session': '2023-09-20', 'native_term_sha256': 'ace7f8e508c49e9862bebc47f5b85a37894e6437a7d42d5abdafd777efa13307', 'parent_positions': []}, {'ticker': 'RETA', 'security_id': '877716075426179792', 'session': '2023-09-22', 'native_session': '2023-09-25', 'native_term_sha256': 'bb0719c54b4ff45a5dc107d9fcfa8f7cd5669dd6ade1d1a361805f2b8135983b', 'parent_positions': []}, {'ticker': 'SYNH', 'security_id': '842403186726794681', 'session': '2023-09-26', 'native_session': '2023-09-27', 'native_term_sha256': 'f39a11f470b2c55aa34ba2fee92b70e9c4d1f68eec97c8bf3873af5d61a98feb', 'parent_positions': []}, {'ticker': 'KLR', 'security_id': '130923305193858293', 'session': '2023-10-03', 'native_session': '2023-10-04', 'native_term_sha256': '9b6dcf1a6f93e6a563f4a0bc2312f856bfb08c2d9fc75a6e0b38916dcd78826a', 'parent_positions': []}, {'ticker': 'HZNP', 'security_id': '383424504385495727', 'session': '2023-10-04', 'native_session': '2023-10-05', 'native_term_sha256': '975c5509c7016e4d4c9f414727ed6a3c40838484cf6da343b472385003b13114', 'parent_positions': []}, {'ticker': 'NATI', 'security_id': '889446746390919934', 'session': '2023-10-09', 'native_session': '2023-10-10', 'native_term_sha256': '8ee5dd6fe1c436bc7a30d96e7ec20e929cdf8c242369af91464bacee3eb2f704', 'parent_positions': []}, {'ticker': 'ATVI', 'security_id': '390513115168803332', 'session': '2023-10-11', 'native_session': '2023-10-12', 'native_term_sha256': 'b8322b6513499f4f499c114e9c9fadd724844fdeedbbefcc760b3e195c5f0b96', 'parent_positions': []}, {'ticker': 'THRN', 'security_id': '835478709412082111', 'session': '2023-10-12', 'native_session': '2023-10-13', 'native_term_sha256': '97b2cb4ce89bb219ecd3e7d67da606e0ac9fdd81d7f4be882ff9047e01e151e7', 'parent_positions': []}, {'ticker': 'HCCI', 'security_id': '717278895849758441', 'session': '2023-10-13', 'native_session': '2023-10-16', 'native_term_sha256': 'f9db95537eff65526bf2f14a0db55bc4b56ec4af6e15b06ae5b6e1b6c0c558c3', 'parent_positions': []}, {'ticker': 'EMAN', 'security_id': '702386900757567766', 'session': '2023-10-16', 'native_session': '2023-10-17', 'native_term_sha256': 'c9df437dd7980f250f9cffff09a21f55d02e0ed5a0267c704036b93411b82f6e', 'parent_positions': []}, {'ticker': 'SCPL', 'security_id': '499254345947670980', 'session': '2023-10-19', 'native_session': '2023-10-20', 'native_term_sha256': '3c90ae13a077222a34f759258b1b26282802a7a92e55993f8ed004716528d299', 'parent_positions': []}, {'ticker': 'PFSW', 'security_id': '343955049285071424', 'session': '2023-10-20', 'native_session': '2023-10-23', 'native_term_sha256': '2281e27d40ce01b2d2de4ba1f5b0599697e3b56c18f519b7d93c2ee2c9eb098f', 'parent_positions': []}, {'ticker': 'FRGI', 'security_id': '1134582194511063389', 'session': '2023-10-26', 'native_session': '2023-10-27', 'native_term_sha256': '923dcea368530e78d8eb6e78459aac40310efe047b812e5ef99d6b9e2e7f31a7', 'parent_positions': []}, {'ticker': 'TRHC', 'security_id': '565033869086694544', 'session': '2023-11-01', 'native_session': '2023-11-02', 'native_term_sha256': '1108ea9d0a40f5e0430bb4bec43b63684134c43d21741868c78e5c7e1d00f835', 'parent_positions': []}, {'ticker': 'AVID', 'security_id': '203591011054715248', 'session': '2023-11-03', 'native_session': '2023-11-06', 'native_term_sha256': '042e3c4ef6a4dde2ce9f6856f7e724c153d5ebe2845fe50d28bf0ae99dfcb0c7', 'parent_positions': []}, {'ticker': 'TWNK', 'security_id': '533554648046407798', 'session': '2023-11-03', 'native_session': '2023-11-06', 'native_term_sha256': '5997cc84706bab5bd04a5c6d9fb6e4fb030ece8d8c5792d8235e36c74d071018', 'parent_positions': []}, {'ticker': 'ICPT', 'security_id': '24026445320701582', 'session': '2023-11-06', 'native_session': '2023-11-07', 'native_term_sha256': '785b1e7a91a20d2184844a21a4c088d32d15ef68991d1771e070f438748eeba1', 'parent_positions': []}, {'ticker': 'NEWR', 'security_id': '333926898180811276', 'session': '2023-11-06', 'native_session': '2023-11-07', 'native_term_sha256': '23d0dfe7e1d209f84a68c666878673381b1748f10a891edcd9a00ad55f66b6c0', 'parent_positions': []}, {'ticker': 'NXGN', 'security_id': '666950814132995667', 'session': '2023-11-07', 'native_session': '2023-11-08', 'native_term_sha256': 'ed9cb4e73661df4a643697ed97054a00608f69de0d9285412a9572841a7c446f', 'parent_positions': []}, {'ticker': 'APRN', 'security_id': '50945802619249724', 'session': '2023-11-09', 'native_session': '2023-11-10', 'native_term_sha256': 'a2d09a62db63201dd04a8c12ef4787e60a1c6076c599cd7d3a2ac6985871b707', 'parent_positions': []}, {'ticker': 'CCF', 'security_id': '296189780333092312', 'session': '2023-11-13', 'native_session': '2023-11-14', 'native_term_sha256': '33540560e81521cdf9e039726ce9e883376fbc76ad2450c12c873c820ba872e5', 'parent_positions': []}, {'ticker': 'ARGO', 'security_id': '742455654792357520', 'session': '2023-11-14', 'native_session': '2023-11-15', 'native_term_sha256': '7e48b25b34915b0efa300614288abeb8d1d7216af5826ea0239f37fe8eaafb20', 'parent_positions': []}, {'ticker': 'SCU', 'security_id': '430094077611721082', 'session': '2023-11-15', 'native_session': '2023-11-16', 'native_term_sha256': '82351662c1b14efd3d8dbd1da67afb8bdd40a87e430a6888186036e119f864d3', 'parent_positions': []}, {'ticker': 'AVTA', 'security_id': '208186199728699255', 'session': '2023-11-24', 'native_session': '2023-11-27', 'native_term_sha256': 'd918e87a2fecd07beb73b36b004f1fd702905fbbed9d2d0a2b881fc313c8c660', 'parent_positions': []}, {'ticker': 'HT', 'security_id': '507062967556352769', 'session': '2023-11-24', 'native_session': '2023-11-27', 'native_term_sha256': '238d86ca42a2db880685f2a7c8293ea58b41862bcff8e438c42fd7b4b35ba482', 'parent_positions': []}, {'ticker': 'VRTV', 'security_id': '383149493474077830', 'session': '2023-11-28', 'native_session': '2023-11-29', 'native_term_sha256': '69ea34393e67ec4cdd0af7f85f5620871305daf50315fd66da35efb50734b847', 'parent_positions': []}, {'ticker': 'GHL', 'security_id': '922568749150320567', 'session': '2023-11-29', 'native_session': '2023-11-30', 'native_term_sha256': '99ea1082f03eba7fcf76b43b7c3c36559c38d4a8d2374d4e557f8c2db3f9819b', 'parent_positions': []}, {'ticker': 'BSQR', 'security_id': '62222139879558786', 'session': '2023-12-06', 'native_session': '2023-12-07', 'native_term_sha256': 'b3838bb28dceabc1c76ac26ac27b90f5db5ac843dbef547b7253c4fa5687ca08', 'parent_positions': []}, {'ticker': 'CTG', 'security_id': '300142723740074716', 'session': '2023-12-11', 'native_session': '2023-12-12', 'native_term_sha256': '4292e34ae26b19e99252bb4c628b69df54db0e23b8b6de5bda8e43f4c3e8bff5', 'parent_positions': []}, {'ticker': 'SGEN', 'security_id': '64011142132727200', 'session': '2023-12-12', 'native_session': '2023-12-13', 'native_term_sha256': '8cf9ddef5b17730a2a94f8cd1a269254addb17d66a5f9b03aa11d9c0b5913f24', 'parent_positions': []}, {'ticker': 'PCTI', 'security_id': '1141467240476407851', 'session': '2023-12-14', 'native_session': '2023-12-15', 'native_term_sha256': '8db22cc6a930d1cd5fc7b4da11e0ef32e57ccad1db59e297acbee83878f1429f', 'parent_positions': []}, {'ticker': 'MDWT', 'security_id': '1032365920179969095', 'session': '2023-12-19', 'native_session': '2023-12-20', 'native_term_sha256': '504add145eb0a287d9566d16d84545a21da7c5678e2880e9be12f35ccfb87e9a', 'parent_positions': []}, {'ticker': 'PATI', 'security_id': '809685213630446666', 'session': '2023-12-20', 'native_session': '2023-12-21', 'native_term_sha256': '6d7e1fca086a7b78aa9c2d7e03a1dc2962624b11581e4e576c50fcbd48fb274e', 'parent_positions': []}, {'ticker': 'LVOX', 'security_id': '321856714299697497', 'session': '2023-12-21', 'native_session': '2023-12-22', 'native_term_sha256': '9252c8e3835e4cac30dc95fcce05def1c1d4f73312b749f8830040fd562a94be', 'parent_positions': []}, {'ticker': 'PNT', 'security_id': '148089382008743586', 'session': '2023-12-22', 'native_session': '2023-12-26', 'native_term_sha256': '2bef242fbc33ad035d6a7d00c35d9d060383d0d6545dd1acb682e4b5527229ce', 'parent_positions': []}, {'ticker': 'CHS', 'security_id': '889536937307159083', 'session': '2024-01-03', 'native_session': '2024-01-04', 'native_term_sha256': '1229c375c50234e641330553576ed882cdcadaf456414e3458f7cbffcf830c5f', 'parent_positions': []}, {'ticker': 'BVH', 'security_id': '156282255624886742', 'session': '2024-01-12', 'native_session': '2024-01-16', 'native_term_sha256': 'a60952df8ed1087a87e58cd1a5a96dc2db90909a91ef321a0ad9ac3a34b51470', 'parent_positions': []}, {'ticker': 'ESMT', 'security_id': '569372934016384054', 'session': '2024-01-24', 'native_session': '2024-01-25', 'native_term_sha256': 'b26f3e70f27e9e8104335899a2485ac05555c1678f5c7cf29f93eb82b9a152c0', 'parent_positions': []}, {'ticker': 'IMGN', 'security_id': '170441452346015322', 'session': '2024-02-08', 'native_session': '2024-02-09', 'native_term_sha256': 'c09607c58f8ec9489f838f63ff6527059c755d2cdf9438f5925f8d8a496951b5', 'parent_positions': []}, {'ticker': 'SPLK', 'security_id': '562947493199996351', 'session': '2024-03-14', 'native_session': '2024-03-15', 'native_term_sha256': '2bfcf1c193d2d87430648498ec0aeb6466c2b924280960aa77bc4120cd85c451', 'parent_positions': []}, {'ticker': 'CBAY', 'security_id': '1020879448423638006', 'session': '2024-03-20', 'native_session': '2024-03-21', 'native_term_sha256': 'd61a1c3436d5ed8b2f5d3535c534ee6dd8aefefa2d95362e2ece751c44198be7', 'parent_positions': []}, {'ticker': 'KAMN', 'security_id': '1131981377127137469', 'session': '2024-04-17', 'native_session': '2024-04-18', 'native_term_sha256': 'f4ad1a4b048535b57c95230ab704f0b20396d89345b75fae190e10d878522bef', 'parent_positions': []}, {'ticker': 'MDC', 'security_id': '990238054080584816', 'session': '2024-04-17', 'native_session': '2024-04-18', 'native_term_sha256': '008b11876071a34917bef3d7cdfe2bfa3385813c1d53165a1a36ae1121677eee', 'parent_positions': []}, {'ticker': 'PXD', 'security_id': '276044719892003870', 'session': '2024-05-01', 'native_session': '2024-05-02', 'native_term_sha256': '75634fb117503001b3c9e09b14f381c25aa4de0dbb9f6cf05db57eee57adde3f', 'parent_positions': []}, {'ticker': 'ALPN', 'security_id': '1079367959124332531', 'session': '2024-05-16', 'native_session': '2024-05-17', 'native_term_sha256': '501ef01c210d47e1194cf165eca0b17cc2e014f52a7b01ea6aef622b1f95a300', 'parent_positions': []}, {'ticker': 'SWAV', 'security_id': '158012003593585084', 'session': '2024-05-29', 'native_session': '2024-05-30', 'native_term_sha256': '011cbd286ef8f6e57519452164b18187177190814dfe5742ce4ac52d70f02a0c', 'parent_positions': []}, {'ticker': 'DCPH', 'security_id': '710952026927009495', 'session': '2024-06-07', 'native_session': '2024-06-10', 'native_term_sha256': '0176813ad5782f9bf8ac9d288c890209119c6e1030675018523f6ba660ed979c', 'parent_positions': []}, {'ticker': 'EVBG', 'security_id': '741035362761868119', 'session': '2024-06-28', 'native_session': '2024-07-01', 'native_term_sha256': '3945592c297ca7206c046072586f3ae7dc328922b05b96e1db7e6f6530b783c9', 'parent_positions': []}, {'ticker': 'ASTR', 'security_id': '1011284967859810069', 'session': '2024-07-16', 'native_session': '2024-07-17', 'native_term_sha256': '4d014735e70d00fde30af61fc710a750d3c724c888a517d220e4fdc864dd8982', 'parent_positions': []}, {'ticker': 'MORF', 'security_id': '977112340201324412', 'session': '2024-08-15', 'native_session': '2024-08-16', 'native_term_sha256': '86f0b41fbd1d1e2489011ed3649696b50ad7cebd4375cc1725a382724ed60235', 'parent_positions': []}, {'ticker': 'PRFT', 'security_id': '183768544366008802', 'session': '2024-09-30', 'native_session': '2024-10-01', 'native_term_sha256': '3e51dd694101fef4a99b3f1fbfb9764802b072776546b77886be7036c6a47602', 'parent_positions': []}, {'ticker': 'LBPH', 'security_id': '355279027800974395', 'session': '2024-11-27', 'native_session': '2024-11-29', 'native_term_sha256': 'e65b583e8e8358e98294987b3fcaa172ce122bb744aa1fc51a875ee73a48d669', 'parent_positions': []}, {'ticker': 'CTLT', 'security_id': '926139522403724450', 'session': '2024-12-16', 'native_session': '2024-12-17', 'native_term_sha256': '3271de7e17ba66ccba86e074949c81af628173cc56a19774ced304bedd7669ba', 'parent_positions': []}, {'ticker': 'CDMO', 'security_id': '641708992638960500', 'session': '2025-02-03', 'native_session': '2025-02-04', 'native_term_sha256': '7b2b81fd18a7ea21785d94eb2d6b0a2a6094d071cdf39e29adc90f9c676955fd', 'parent_positions': []}, {'ticker': 'RVNC', 'security_id': '561615213934063912', 'session': '2025-02-04', 'native_session': '2025-02-05', 'native_term_sha256': '9cc4f56192bc679401bac4693ef257ac1b8cf604d3fc3b3e3ba2e078ff3115de', 'parent_positions': []}, {'ticker': 'SUM', 'security_id': '364431306575234844', 'session': '2025-02-06', 'native_session': '2025-02-07', 'native_term_sha256': '5255ddbfa9b5ea696b66534c6b3164df88d207f1b11376bfb1b3fba9c8676e97', 'parent_positions': []}, {'ticker': 'ZUO', 'security_id': '699288853008671138', 'session': '2025-02-12', 'native_session': '2025-02-13', 'native_term_sha256': '21579cffcc2f2314a8b6c950019e8f9712892ab0cfd48e790acbf605fd0f2842', 'parent_positions': []}, {'ticker': 'NARI', 'security_id': '543768354908702200', 'session': '2025-02-14', 'native_session': '2025-02-18', 'native_term_sha256': '762b3b541e1666ae72f6f3acf2715ada57262f3663b9262e94f04e01bbcdf584', 'parent_positions': []}, {'ticker': 'OMIC', 'security_id': '252574123696847206', 'session': '2025-02-19', 'native_session': '2025-02-20', 'native_term_sha256': 'd34f99ecf7288747480d57847fe6e0e037a62958a82bbe1b2705e09dd2c81932', 'parent_positions': []}, {'ticker': 'HCP', 'security_id': '610550191134128154', 'session': '2025-02-25', 'native_session': '2025-02-26', 'native_term_sha256': '1ff4c354fc5ce990d341e498439ddae9a0ee850bb942067d25cfb75b04b91d95', 'parent_positions': []}, {'ticker': 'MTTR', 'security_id': '268723442486744870', 'session': '2025-02-26', 'native_session': '2025-02-27', 'native_term_sha256': '421d2c626abc23c56c22ffc5ecf7f94f5b42620dd5af1255c4464c232b2b3fbb', 'parent_positions': []}, {'ticker': 'INFN', 'security_id': '472454776648049441', 'session': '2025-02-26', 'native_session': '2025-02-27', 'native_term_sha256': 'fa976bbcc5bd0458c6eb3e8018c80f42d0b7133b2d11a9e32ac3ea5ff12c15f1', 'parent_positions': []}, {'ticker': 'EMKR', 'security_id': '106733641894872523', 'session': '2025-02-27', 'native_session': '2025-02-28', 'native_term_sha256': '4065446c280d39ce8be2e4d835e35462eebccddb90cd77e3cf98ddc4aaa501d0', 'parent_positions': []}, {'ticker': 'ALTM', 'security_id': '683269517186158393', 'session': '2025-03-04', 'native_session': '2025-03-05', 'native_term_sha256': '96ab26959f6e9d842ba4410a4903bca9907a1ca5465bc95bc156b32121acb0f3', 'parent_positions': []}, {'ticker': 'AZPN', 'security_id': '556944515102158299', 'session': '2025-03-10', 'native_session': '2025-03-11', 'native_term_sha256': '173f226d9a15bf7e782de041d3679c4480aca4b96952f910c4add848fa94bfa6', 'parent_positions': []}, {'ticker': 'DFS', 'security_id': '884366050981445610', 'session': '2025-05-15', 'native_session': '2025-05-16', 'native_term_sha256': '638b0d51e7a7601a41b651932bec0d789a2da27e17159048300b29f7f2d33fdb', 'parent_positions': []}, {'ticker': 'JNPR', 'security_id': '949392331435765708', 'session': '2025-06-30', 'native_session': '2025-07-01', 'native_term_sha256': 'eea71df25ce86ef99f87d8505cf6920884cc8a66b3aeb2d7557e74f6d295aa4c', 'parent_positions': []}, {'ticker': 'BPMC', 'security_id': '142211284179578270', 'session': '2025-07-16', 'native_session': '2025-07-17', 'native_term_sha256': '77b3dd31d5a77ecbdcaf505630a891933e79b09e614dcfdff19ec56a025e7e5b', 'parent_positions': []}, {'ticker': 'TGI', 'security_id': '498918945550351909', 'session': '2025-07-23', 'native_session': '2025-07-24', 'native_term_sha256': 'd64927eb0e80aa8e0a5e596cb60a510b45896548ea33f082442ae8a7a9a40580', 'parent_positions': []}, {'ticker': 'AMED', 'security_id': '207977697074649672', 'session': '2025-08-13', 'native_session': '2025-08-14', 'native_term_sha256': '22df39e836fa2f92088ae209ad2a09c085d18d7828432cf1b7b262576064be4e', 'parent_positions': []}, {'ticker': 'ETNB', 'security_id': '146334772721825722', 'session': '2025-10-29', 'native_session': '2025-10-30', 'native_term_sha256': 'bf5577c47d4d69ceaf8bf547c840580a079b495852b4d089f661bc1e5a4b7c89', 'parent_positions': []}, {'ticker': 'LNWO', 'security_id': '467726443352731838', 'session': '2025-11-13', 'native_session': '2025-11-14', 'native_term_sha256': '6cc2c176c4e2289531450e4bbfc11a0434114506766daed1310363a9ad6aff8d', 'parent_positions': []}, {'ticker': 'CDTX', 'security_id': '1113557341267806383', 'session': '2026-01-05', 'native_session': '2026-01-06', 'native_term_sha256': '944993f17a9eb2dcf26081fed8e05fba416f9a136b69a8e9255f5a2150f1374e', 'parent_positions': []}, {'ticker': 'SHCO', 'security_id': '162004720301108303', 'session': '2026-01-27', 'native_session': '2026-01-28', 'native_term_sha256': '1925b21534a70b9b25ab331350bf9cf46d37f397925c733c7f96a8e0c22d27c5', 'parent_positions': []}, {'ticker': 'RAPT', 'security_id': '117211213247402731', 'session': '2026-03-02', 'native_session': '2026-03-03', 'native_term_sha256': '77a4ab952aca53203df5a4972a51aac2d8d55669f32ac56c863fa64b896dbed0', 'parent_positions': []}, {'ticker': 'EXAS', 'security_id': '637262944715750985', 'session': '2026-03-19', 'native_session': '2026-03-20', 'native_term_sha256': '689adccb69cd2f499298678e43c60d83e73de51f1af1ba8f4de739aabc85ccbd', 'parent_positions': []}, {'ticker': 'TERN', 'security_id': '961294553911856115', 'session': '2026-05-01', 'native_session': '2026-05-04', 'native_term_sha256': 'ee9a9ee8b82e907c6b0024834ae9e9ac4aef4341358e57556926fa955e0139d0', 'parent_positions': []}, {'ticker': 'SLNO', 'security_id': '736275735073520563', 'session': '2026-05-15', 'native_session': '2026-05-18', 'native_term_sha256': '2394da8743a299b2acf321096a51c90ac0e499222a56832d58a50b28bcba849a', 'parent_positions': []}, {'ticker': 'AMWD', 'security_id': '332224216763941431', 'session': '2026-05-27', 'native_session': '2026-05-28', 'native_term_sha256': '51e18a8ab3c72cae703c490a0a432edc46bae19bbf5146f8228127d2ab9b21eb', 'parent_positions': []}, {'ticker': 'TMHC', 'security_id': '13062188894457483', 'session': '2026-07-22', 'native_session': '2026-07-23', 'native_term_sha256': '11fd2c4548f637a6ce8f3083ca50cb2f616f4f4e4c185ff46f745b5b51a4a2c8', 'parent_positions': []}, {'ticker': 'ORLA', 'security_id': '622077003929363486', 'session': '2026-07-30', 'native_session': '2026-07-31', 'native_term_sha256': '38af459b36abb7bbd88339f114ac17c3755db5be8836982edd3077f36e8b65da', 'parent_positions': []}], 'additional_rows': []}
EXTRA_WITNESS_SCOPES[('P05', '2022-03-31-remaining-original-cash-natives')] = {'parent_outer_sha256': 'feef2cdb81f4a469b69f381f9e5fc398c2bdbe24c709d05ab49157e3df971ff4', 'parent_cursor': '2022-03-31', 'terms': [{'ticker': 'HMHC', 'security_id': '875684930968851666', 'session': '2022-04-05', 'native_session': '2022-04-06', 'native_term_sha256': '2e28ff8f4c521842ff9344f35ff1fcd7b14059897930661bd53dc75e92c64abf', 'parent_positions': [{'slot_id': 14, 'ticker': 'HMHC', 'quantity': 103, 'entry_date': '2022-03-22'}]}, {'ticker': 'GNOG', 'security_id': '492385206273420565', 'session': '2022-05-03', 'native_session': '2022-05-04', 'native_term_sha256': '04c3597fed20e3dde7fa44db154cad48a097d1737f419fafd1b70074a95cfe33', 'parent_positions': []}, {'ticker': 'XENT', 'security_id': '948589239641460025', 'session': '2022-05-11', 'native_session': '2022-05-12', 'native_term_sha256': '7ec878d790620777a8e43b53ee60903959627938b58e36397560051d5eacb03f', 'parent_positions': []}, {'ticker': 'MIME', 'security_id': '988236261397113691', 'session': '2022-05-17', 'native_session': '2022-05-18', 'native_term_sha256': '1ea2abbb8cd4e10bae112ca8aaa7cd87822db91afbcaaa52ad6da417b8c4d0d6', 'parent_positions': [{'slot_id': 13, 'ticker': 'MIME', 'quantity': 27, 'entry_date': '2022-03-25'}]}, {'ticker': 'ANAT', 'security_id': '43437726633884038', 'session': '2022-05-23', 'native_session': '2022-05-24', 'native_term_sha256': 'aa8af4c300137446a2cadbeed4361abab75e51e5fc5df0aeb86720fa501629f2', 'parent_positions': [{'slot_id': 19, 'ticker': 'ANAT', 'quantity': 11, 'entry_date': '2022-02-02'}]}, {'ticker': 'MSP', 'security_id': '892733995247202485', 'session': '2022-06-21', 'native_session': '2022-06-22', 'native_term_sha256': '5018fbc936ffda49edf56862746b3be103144fd0b7b400c46e7e6ac4dfca71f7', 'parent_positions': []}, {'ticker': 'TVTY', 'security_id': '506048722516044547', 'session': '2022-06-24', 'native_session': '2022-06-27', 'native_term_sha256': 'aca7bf92b9c5faea11cf82b77b7e081e728242a3775f9ba2f435da3015236e95', 'parent_positions': []}, {'ticker': 'CCMP', 'security_id': '361307705630329294', 'session': '2022-07-01', 'native_session': '2022-07-05', 'native_term_sha256': 'e6b906f60567135af8a2d339bb3cfbb866d6a3236b446f4a7e402d6456ad915d', 'parent_positions': []}, {'ticker': 'SAFM', 'security_id': '962454383671746307', 'session': '2022-07-20', 'native_session': '2022-07-21', 'native_term_sha256': 'd00cf559bcc50db02d1e30e69194f3f92949e1085b4bd23b53c4f134aba86d09', 'parent_positions': []}, {'ticker': 'ACC', 'security_id': '209530306982231273', 'session': '2022-08-08', 'native_session': '2022-08-09', 'native_term_sha256': 'dedc2034f8b43302ab25e6be16e3c4896563412b8510b3cb4083281b6cbf21a7', 'parent_positions': []}, {'ticker': 'CTXS', 'security_id': '554480052825212855', 'session': '2022-09-28', 'native_session': '2022-09-29', 'native_term_sha256': '6c306190c326bc01b52d3fb9fda5f2cd2cdf09fdc447cb5a41064136c6c4329a', 'parent_positions': []}, {'ticker': 'DRE', 'security_id': '518054177581800417', 'session': '2022-09-29', 'native_session': '2022-09-30', 'native_term_sha256': '713092be4dbb3c3f9ba9d72f027191a8e5394a69087bbd98b7351d19c7d94c3c', 'parent_positions': []}, {'ticker': 'GBT', 'security_id': '827416728546053456', 'session': '2022-10-03', 'native_session': '2022-10-04', 'native_term_sha256': '24ecdb67869b11470699c0bf1a02ca59f46d671bd9008d196f4a80cd05c46500', 'parent_positions': []}, {'ticker': 'FMTX', 'security_id': '321650252292096156', 'session': '2022-10-12', 'native_session': '2022-10-13', 'native_term_sha256': '520764575d781727341e687841e205e9404aff6726da7de2bc8e58a9864d18d4', 'parent_positions': []}, {'ticker': 'PING', 'security_id': '23427772744584579', 'session': '2022-10-14', 'native_session': '2022-10-17', 'native_term_sha256': 'b1481b42046cb67003a896150c6f7f9b28910b29f1b5a53ec35ef219bd4a78f0', 'parent_positions': []}, {'ticker': 'AVLR', 'security_id': '652370478798714876', 'session': '2022-10-17', 'native_session': '2022-10-18', 'native_term_sha256': '10943a680bf8b4a98575225ee89ecabce5e8ed3bf066ed318e8ef5db55d5bc5f', 'parent_positions': []}, {'ticker': 'Y', 'security_id': '683977592320274232', 'session': '2022-10-17', 'native_session': '2022-10-18', 'native_term_sha256': 'a32a8b2e023dedf84185a5b7d3847b546bc29f0ff99b0186c05019dd91d9ab90', 'parent_positions': []}, {'ticker': 'CYBE', 'security_id': '738630690199421979', 'session': '2022-11-02', 'native_session': '2022-11-03', 'native_term_sha256': '4284b79a3b3954191aa59af15c07a06e626cb2340fc4834100ec506631670ef1', 'parent_positions': []}, {'ticker': 'ZEN', 'security_id': '870865871230451373', 'session': '2022-11-18', 'native_session': '2022-11-21', 'native_term_sha256': '4eb6cbadfb1fd10a87741ed05f2e3d7025700280835e49f4f838d071b0600dd2', 'parent_positions': []}, {'ticker': 'ABMD', 'security_id': '1050970006012443443', 'session': '2022-12-20', 'native_session': '2022-12-21', 'native_term_sha256': '815f61b085dee89b89956834f250763522bff5402fdcc3d36ebb36c85d0796e4', 'parent_positions': []}, {'ticker': 'SJI', 'security_id': '255755003526074655', 'session': '2023-01-30', 'native_session': '2023-01-31', 'native_term_sha256': '3cdb7e9ae9227a2ff6d47e2e40240b74e8d10854ec1eb4591c5c2a039f2a72fb', 'parent_positions': []}, {'ticker': 'LHCG', 'security_id': '348961068556052300', 'session': '2023-02-17', 'native_session': '2023-02-21', 'native_term_sha256': 'b13c3cdc8ce1b9651108d79ca572c1a7f10aefa5a204c35fb1c8fbd28b3e3e37', 'parent_positions': []}, {'ticker': 'ONEM', 'security_id': '677864286983813096', 'session': '2023-02-21', 'native_session': '2023-02-22', 'native_term_sha256': '7930c9741ebd86ef403aa2c1f8a64e36a627c9db3bc4e3993fae29a438ca6d1d', 'parent_positions': []}, {'ticker': 'COUP', 'security_id': '840778708963135084', 'session': '2023-02-24', 'native_session': '2023-02-27', 'native_term_sha256': '23dcc826824e13c0137d03ff260ecac5fc4a79b0f945363946c9511ae6e567c7', 'parent_positions': []}, {'ticker': 'EVOP', 'security_id': '754975132000056845', 'session': '2023-03-22', 'native_session': '2023-03-23', 'native_term_sha256': '4ae01e26dfd27924a8973b40c79e755ff31adfba0be52e9ee9779fd8ca9679b3', 'parent_positions': []}, {'ticker': 'SGFY', 'security_id': '151225572607695758', 'session': '2023-03-27', 'native_session': '2023-03-28', 'native_term_sha256': 'b62f3cd219734387c09081d63dac7858e2b28ffd6f41ae29b39a9ebe0dcaa940', 'parent_positions': []}, {'ticker': 'CEMI', 'security_id': '1089594935488302817', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': 'c3fe2a1af242ed612fe1d9d7a4042bcde7a840011b1c2843c9227285f625101c', 'parent_positions': []}, {'ticker': 'CSII', 'security_id': '50040477475186027', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': '04260434a5ee3eccb4a082ab5f969d49790e8a76738cb3534260811cbd14cf58', 'parent_positions': []}, {'ticker': 'PRVB', 'security_id': '858933953652218125', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': '0425d032b38ebf0099beec0a7556f66368d3cba1a7ee82a455d28d3908331d39', 'parent_positions': []}, {'ticker': 'OSH', 'security_id': '917666101373510238', 'session': '2023-04-28', 'native_session': '2023-05-01', 'native_term_sha256': '3bfd185a3434b5e62dde7aa56683f1f9c82f61150541f8ae0871d0f2b16db450', 'parent_positions': []}, {'ticker': 'MAXR', 'security_id': '192029376284057522', 'session': '2023-05-01', 'native_session': '2023-05-02', 'native_term_sha256': '8165277eedd833036d96db039d1432df89514fc53800e6d5cd8f05c977efcd8b', 'parent_positions': []}, {'ticker': 'SUMO', 'security_id': '233469495168272142', 'session': '2023-05-10', 'native_session': '2023-05-11', 'native_term_sha256': 'cd4f6ea36d9e3a6475dcd9a6f34f93feefd20699f4df36992a4a6c1f9aad2a23', 'parent_positions': []}, {'ticker': 'TA', 'security_id': '273582270998538925', 'session': '2023-05-11', 'native_session': '2023-05-12', 'native_term_sha256': '77d6eedc0731bf0b61f05abbe341d3a6d0ededaff2b99f5f18efe6d7047bcff2', 'parent_positions': []}, {'ticker': 'MNTV', 'security_id': '62458272022348266', 'session': '2023-05-30', 'native_session': '2023-05-31', 'native_term_sha256': 'dc62d52a52598231f5a244624e60bca0f72789db27ccc30ddf212c568ec3f870', 'parent_positions': []}, {'ticker': 'MGI', 'security_id': '631714153765036714', 'session': '2023-05-30', 'native_session': '2023-05-31', 'native_term_sha256': '5d5e99a5c938874325db2c8ca83c2c8aaee2901eb86599b21a250fd6a4880b6c', 'parent_positions': []}, {'ticker': 'HSKA', 'security_id': '1132165486668118439', 'session': '2023-06-09', 'native_session': '2023-06-12', 'native_term_sha256': 'be6349194d300cb9195944599ddba0d2c80c0f3afbb7e22295d12033c20a5fe0', 'parent_positions': []}, {'ticker': 'RUTH', 'security_id': '129751434275280834', 'session': '2023-06-12', 'native_session': '2023-06-13', 'native_term_sha256': '882d416fd8b3dd611ec9d7c0c83b6b08d4499cffdd2a0e93d656fa5371e7c016', 'parent_positions': []}, {'ticker': 'CVT', 'security_id': '373813670584114036', 'session': '2023-06-13', 'native_session': '2023-06-14', 'native_term_sha256': 'edbc4944cd6c2348a4fc175801a4869a5b0f2bebd324701dad850720876eb002', 'parent_positions': []}, {'ticker': 'RXDX', 'security_id': '1140650572960055100', 'session': '2023-06-14', 'native_session': '2023-06-15', 'native_term_sha256': '47b894ab6a5b05ba753783dbe031d6ec14c47abd32a2db18bd0c529c5039c91c', 'parent_positions': []}, {'ticker': 'CTIC', 'security_id': '394927144545790620', 'session': '2023-06-22', 'native_session': '2023-06-23', 'native_term_sha256': '4a9acb1a7af4fccfbb8ba40f0c072130e4fb8215ee46caef40740fe3a5ba97e7', 'parent_positions': []}, {'ticker': 'XM', 'security_id': '348606319062466815', 'session': '2023-06-26', 'native_session': '2023-06-27', 'native_term_sha256': '131487cf7ccf68c542c39afe70909c80e6c445fc8bf83367c973f5f8b107eded', 'parent_positions': []}, {'ticker': 'ISEE', 'security_id': '477302961403569227', 'session': '2023-07-07', 'native_session': '2023-07-10', 'native_term_sha256': '670cd42f7b0bd828e76d5ac0f5b8e9f7e311271278275ce261efd8fe0e368c79', 'parent_positions': []}, {'ticker': 'LSI', 'security_id': '753641750484343508', 'session': '2023-07-18', 'native_session': '2023-07-19', 'native_term_sha256': 'ccb498dd580b7f803166463271de8bfb95d1c9f362efaa4f50c0398ed7fdf677', 'parent_positions': [{'slot_id': 5, 'ticker': 'LSI', 'quantity': 16, 'entry_date': '2022-03-24'}]}, {'ticker': 'AJRD', 'security_id': '721679296374852573', 'session': '2023-07-26', 'native_session': '2023-07-27', 'native_term_sha256': 'c18c68ef2a138d80a1bf1325d3ece4707e45c2bb6d51ea96a9a3c6dbb402237d', 'parent_positions': []}, {'ticker': 'UNVR', 'security_id': '220188358195861572', 'session': '2023-07-28', 'native_session': '2023-07-31', 'native_term_sha256': 'a268aa3d4745bff6faab92aac962c554b3d771849acb55a4b32479cddf72f047', 'parent_positions': []}, {'ticker': 'DICE', 'security_id': '349504371207456722', 'session': '2023-08-07', 'native_session': '2023-08-08', 'native_term_sha256': '38a801a52f9077b135500f4810995ad7ef957a5b4b7a5482d76478bef2104868', 'parent_positions': []}, {'ticker': 'KDNY', 'security_id': '47247117758471252', 'session': '2023-08-09', 'native_session': '2023-08-10', 'native_term_sha256': '8779121eb314297caa8a05ab20d8b3c5c990fe0849d21026d37e50dee95d4060', 'parent_positions': []}, {'ticker': 'ARNC', 'security_id': '814822139570731593', 'session': '2023-08-16', 'native_session': '2023-08-17', 'native_term_sha256': 'daf6fb3e9cf5d61d39b506306a9fc2694ea08dcde843fb6cbbc2e718adb01084', 'parent_positions': []}, {'ticker': 'FRG', 'security_id': '906280636792711059', 'session': '2023-08-17', 'native_session': '2023-08-18', 'native_term_sha256': 'f3c80eb81e56926df1d9d53c81ab4b84b82386d7cefed6814b61ae3b8cc11187', 'parent_positions': []}, {'ticker': 'FORG', 'security_id': '927598213803887960', 'session': '2023-08-21', 'native_session': '2023-08-22', 'native_term_sha256': '154b48f99dbae1e994a7633ecd833f93f76c00e28e3cdc1976fcee45b050fb04', 'parent_positions': []}, {'ticker': 'CFMS', 'security_id': '356455035813755306', 'session': '2023-08-31', 'native_session': '2023-09-01', 'native_term_sha256': 'aa3825d28c44a4b64c55a3b02a4cbbfef597ab48404d2a1e32f9486a2f9a2ec7', 'parent_positions': []}, {'ticker': 'QUOT', 'security_id': '823579734840521990', 'session': '2023-08-31', 'native_session': '2023-09-01', 'native_term_sha256': 'c5476a5065675eb10be41e3feeb1ea7e108e86f85408d066dcd31f6e17342d80', 'parent_positions': []}, {'ticker': 'WWE', 'security_id': '426024777347801008', 'session': '2023-09-08', 'native_session': '2023-09-11', 'native_term_sha256': 'aa99115df1cfdc59e142e6572adb258decc4adedefcb9815e5cce7dcb030c035', 'parent_positions': []}, {'ticker': 'RADI', 'security_id': '477309164594500719', 'session': '2023-09-19', 'native_session': '2023-09-20', 'native_term_sha256': 'ace7f8e508c49e9862bebc47f5b85a37894e6437a7d42d5abdafd777efa13307', 'parent_positions': []}, {'ticker': 'RETA', 'security_id': '877716075426179792', 'session': '2023-09-22', 'native_session': '2023-09-25', 'native_term_sha256': 'bb0719c54b4ff45a5dc107d9fcfa8f7cd5669dd6ade1d1a361805f2b8135983b', 'parent_positions': []}, {'ticker': 'SYNH', 'security_id': '842403186726794681', 'session': '2023-09-26', 'native_session': '2023-09-27', 'native_term_sha256': 'f39a11f470b2c55aa34ba2fee92b70e9c4d1f68eec97c8bf3873af5d61a98feb', 'parent_positions': []}, {'ticker': 'KLR', 'security_id': '130923305193858293', 'session': '2023-10-03', 'native_session': '2023-10-04', 'native_term_sha256': '9b6dcf1a6f93e6a563f4a0bc2312f856bfb08c2d9fc75a6e0b38916dcd78826a', 'parent_positions': []}, {'ticker': 'HZNP', 'security_id': '383424504385495727', 'session': '2023-10-04', 'native_session': '2023-10-05', 'native_term_sha256': '975c5509c7016e4d4c9f414727ed6a3c40838484cf6da343b472385003b13114', 'parent_positions': []}, {'ticker': 'NATI', 'security_id': '889446746390919934', 'session': '2023-10-09', 'native_session': '2023-10-10', 'native_term_sha256': '8ee5dd6fe1c436bc7a30d96e7ec20e929cdf8c242369af91464bacee3eb2f704', 'parent_positions': []}, {'ticker': 'ATVI', 'security_id': '390513115168803332', 'session': '2023-10-11', 'native_session': '2023-10-12', 'native_term_sha256': 'b8322b6513499f4f499c114e9c9fadd724844fdeedbbefcc760b3e195c5f0b96', 'parent_positions': []}, {'ticker': 'THRN', 'security_id': '835478709412082111', 'session': '2023-10-12', 'native_session': '2023-10-13', 'native_term_sha256': '97b2cb4ce89bb219ecd3e7d67da606e0ac9fdd81d7f4be882ff9047e01e151e7', 'parent_positions': []}, {'ticker': 'HCCI', 'security_id': '717278895849758441', 'session': '2023-10-13', 'native_session': '2023-10-16', 'native_term_sha256': 'f9db95537eff65526bf2f14a0db55bc4b56ec4af6e15b06ae5b6e1b6c0c558c3', 'parent_positions': []}, {'ticker': 'EMAN', 'security_id': '702386900757567766', 'session': '2023-10-16', 'native_session': '2023-10-17', 'native_term_sha256': 'c9df437dd7980f250f9cffff09a21f55d02e0ed5a0267c704036b93411b82f6e', 'parent_positions': []}, {'ticker': 'SCPL', 'security_id': '499254345947670980', 'session': '2023-10-19', 'native_session': '2023-10-20', 'native_term_sha256': '3c90ae13a077222a34f759258b1b26282802a7a92e55993f8ed004716528d299', 'parent_positions': []}, {'ticker': 'PFSW', 'security_id': '343955049285071424', 'session': '2023-10-20', 'native_session': '2023-10-23', 'native_term_sha256': '2281e27d40ce01b2d2de4ba1f5b0599697e3b56c18f519b7d93c2ee2c9eb098f', 'parent_positions': []}, {'ticker': 'FRGI', 'security_id': '1134582194511063389', 'session': '2023-10-26', 'native_session': '2023-10-27', 'native_term_sha256': '923dcea368530e78d8eb6e78459aac40310efe047b812e5ef99d6b9e2e7f31a7', 'parent_positions': []}, {'ticker': 'TRHC', 'security_id': '565033869086694544', 'session': '2023-11-01', 'native_session': '2023-11-02', 'native_term_sha256': '1108ea9d0a40f5e0430bb4bec43b63684134c43d21741868c78e5c7e1d00f835', 'parent_positions': []}, {'ticker': 'AVID', 'security_id': '203591011054715248', 'session': '2023-11-03', 'native_session': '2023-11-06', 'native_term_sha256': '042e3c4ef6a4dde2ce9f6856f7e724c153d5ebe2845fe50d28bf0ae99dfcb0c7', 'parent_positions': []}, {'ticker': 'TWNK', 'security_id': '533554648046407798', 'session': '2023-11-03', 'native_session': '2023-11-06', 'native_term_sha256': '5997cc84706bab5bd04a5c6d9fb6e4fb030ece8d8c5792d8235e36c74d071018', 'parent_positions': []}, {'ticker': 'ICPT', 'security_id': '24026445320701582', 'session': '2023-11-06', 'native_session': '2023-11-07', 'native_term_sha256': '785b1e7a91a20d2184844a21a4c088d32d15ef68991d1771e070f438748eeba1', 'parent_positions': []}, {'ticker': 'NXGN', 'security_id': '666950814132995667', 'session': '2023-11-07', 'native_session': '2023-11-08', 'native_term_sha256': 'ed9cb4e73661df4a643697ed97054a00608f69de0d9285412a9572841a7c446f', 'parent_positions': []}, {'ticker': 'APRN', 'security_id': '50945802619249724', 'session': '2023-11-09', 'native_session': '2023-11-10', 'native_term_sha256': 'a2d09a62db63201dd04a8c12ef4787e60a1c6076c599cd7d3a2ac6985871b707', 'parent_positions': []}, {'ticker': 'CCF', 'security_id': '296189780333092312', 'session': '2023-11-13', 'native_session': '2023-11-14', 'native_term_sha256': '33540560e81521cdf9e039726ce9e883376fbc76ad2450c12c873c820ba872e5', 'parent_positions': []}, {'ticker': 'ARGO', 'security_id': '742455654792357520', 'session': '2023-11-14', 'native_session': '2023-11-15', 'native_term_sha256': '7e48b25b34915b0efa300614288abeb8d1d7216af5826ea0239f37fe8eaafb20', 'parent_positions': []}, {'ticker': 'SCU', 'security_id': '430094077611721082', 'session': '2023-11-15', 'native_session': '2023-11-16', 'native_term_sha256': '82351662c1b14efd3d8dbd1da67afb8bdd40a87e430a6888186036e119f864d3', 'parent_positions': []}, {'ticker': 'AVTA', 'security_id': '208186199728699255', 'session': '2023-11-24', 'native_session': '2023-11-27', 'native_term_sha256': 'd918e87a2fecd07beb73b36b004f1fd702905fbbed9d2d0a2b881fc313c8c660', 'parent_positions': []}, {'ticker': 'HT', 'security_id': '507062967556352769', 'session': '2023-11-24', 'native_session': '2023-11-27', 'native_term_sha256': '238d86ca42a2db880685f2a7c8293ea58b41862bcff8e438c42fd7b4b35ba482', 'parent_positions': []}, {'ticker': 'VRTV', 'security_id': '383149493474077830', 'session': '2023-11-28', 'native_session': '2023-11-29', 'native_term_sha256': '69ea34393e67ec4cdd0af7f85f5620871305daf50315fd66da35efb50734b847', 'parent_positions': []}, {'ticker': 'GHL', 'security_id': '922568749150320567', 'session': '2023-11-29', 'native_session': '2023-11-30', 'native_term_sha256': '99ea1082f03eba7fcf76b43b7c3c36559c38d4a8d2374d4e557f8c2db3f9819b', 'parent_positions': []}, {'ticker': 'BSQR', 'security_id': '62222139879558786', 'session': '2023-12-06', 'native_session': '2023-12-07', 'native_term_sha256': 'b3838bb28dceabc1c76ac26ac27b90f5db5ac843dbef547b7253c4fa5687ca08', 'parent_positions': []}, {'ticker': 'CTG', 'security_id': '300142723740074716', 'session': '2023-12-11', 'native_session': '2023-12-12', 'native_term_sha256': '4292e34ae26b19e99252bb4c628b69df54db0e23b8b6de5bda8e43f4c3e8bff5', 'parent_positions': []}, {'ticker': 'SGEN', 'security_id': '64011142132727200', 'session': '2023-12-12', 'native_session': '2023-12-13', 'native_term_sha256': '8cf9ddef5b17730a2a94f8cd1a269254addb17d66a5f9b03aa11d9c0b5913f24', 'parent_positions': []}, {'ticker': 'PCTI', 'security_id': '1141467240476407851', 'session': '2023-12-14', 'native_session': '2023-12-15', 'native_term_sha256': '8db22cc6a930d1cd5fc7b4da11e0ef32e57ccad1db59e297acbee83878f1429f', 'parent_positions': []}, {'ticker': 'MDWT', 'security_id': '1032365920179969095', 'session': '2023-12-19', 'native_session': '2023-12-20', 'native_term_sha256': '504add145eb0a287d9566d16d84545a21da7c5678e2880e9be12f35ccfb87e9a', 'parent_positions': []}, {'ticker': 'PATI', 'security_id': '809685213630446666', 'session': '2023-12-20', 'native_session': '2023-12-21', 'native_term_sha256': '6d7e1fca086a7b78aa9c2d7e03a1dc2962624b11581e4e576c50fcbd48fb274e', 'parent_positions': []}, {'ticker': 'LVOX', 'security_id': '321856714299697497', 'session': '2023-12-21', 'native_session': '2023-12-22', 'native_term_sha256': '9252c8e3835e4cac30dc95fcce05def1c1d4f73312b749f8830040fd562a94be', 'parent_positions': []}, {'ticker': 'PNT', 'security_id': '148089382008743586', 'session': '2023-12-22', 'native_session': '2023-12-26', 'native_term_sha256': '2bef242fbc33ad035d6a7d00c35d9d060383d0d6545dd1acb682e4b5527229ce', 'parent_positions': []}, {'ticker': 'CHS', 'security_id': '889536937307159083', 'session': '2024-01-03', 'native_session': '2024-01-04', 'native_term_sha256': '1229c375c50234e641330553576ed882cdcadaf456414e3458f7cbffcf830c5f', 'parent_positions': []}, {'ticker': 'BVH', 'security_id': '156282255624886742', 'session': '2024-01-12', 'native_session': '2024-01-16', 'native_term_sha256': 'a60952df8ed1087a87e58cd1a5a96dc2db90909a91ef321a0ad9ac3a34b51470', 'parent_positions': []}, {'ticker': 'ESMT', 'security_id': '569372934016384054', 'session': '2024-01-24', 'native_session': '2024-01-25', 'native_term_sha256': 'b26f3e70f27e9e8104335899a2485ac05555c1678f5c7cf29f93eb82b9a152c0', 'parent_positions': []}, {'ticker': 'SPLK', 'security_id': '562947493199996351', 'session': '2024-03-14', 'native_session': '2024-03-15', 'native_term_sha256': '2bfcf1c193d2d87430648498ec0aeb6466c2b924280960aa77bc4120cd85c451', 'parent_positions': []}, {'ticker': 'CBAY', 'security_id': '1020879448423638006', 'session': '2024-03-20', 'native_session': '2024-03-21', 'native_term_sha256': 'd61a1c3436d5ed8b2f5d3535c534ee6dd8aefefa2d95362e2ece751c44198be7', 'parent_positions': []}, {'ticker': 'KAMN', 'security_id': '1131981377127137469', 'session': '2024-04-17', 'native_session': '2024-04-18', 'native_term_sha256': 'f4ad1a4b048535b57c95230ab704f0b20396d89345b75fae190e10d878522bef', 'parent_positions': []}, {'ticker': 'MDC', 'security_id': '990238054080584816', 'session': '2024-04-17', 'native_session': '2024-04-18', 'native_term_sha256': '008b11876071a34917bef3d7cdfe2bfa3385813c1d53165a1a36ae1121677eee', 'parent_positions': []}, {'ticker': 'PXD', 'security_id': '276044719892003870', 'session': '2024-05-01', 'native_session': '2024-05-02', 'native_term_sha256': '75634fb117503001b3c9e09b14f381c25aa4de0dbb9f6cf05db57eee57adde3f', 'parent_positions': []}, {'ticker': 'ALPN', 'security_id': '1079367959124332531', 'session': '2024-05-16', 'native_session': '2024-05-17', 'native_term_sha256': '501ef01c210d47e1194cf165eca0b17cc2e014f52a7b01ea6aef622b1f95a300', 'parent_positions': []}, {'ticker': 'SWAV', 'security_id': '158012003593585084', 'session': '2024-05-29', 'native_session': '2024-05-30', 'native_term_sha256': '011cbd286ef8f6e57519452164b18187177190814dfe5742ce4ac52d70f02a0c', 'parent_positions': []}, {'ticker': 'DCPH', 'security_id': '710952026927009495', 'session': '2024-06-07', 'native_session': '2024-06-10', 'native_term_sha256': '0176813ad5782f9bf8ac9d288c890209119c6e1030675018523f6ba660ed979c', 'parent_positions': []}, {'ticker': 'EVBG', 'security_id': '741035362761868119', 'session': '2024-06-28', 'native_session': '2024-07-01', 'native_term_sha256': '3945592c297ca7206c046072586f3ae7dc328922b05b96e1db7e6f6530b783c9', 'parent_positions': []}, {'ticker': 'ASTR', 'security_id': '1011284967859810069', 'session': '2024-07-16', 'native_session': '2024-07-17', 'native_term_sha256': '4d014735e70d00fde30af61fc710a750d3c724c888a517d220e4fdc864dd8982', 'parent_positions': []}, {'ticker': 'MORF', 'security_id': '977112340201324412', 'session': '2024-08-15', 'native_session': '2024-08-16', 'native_term_sha256': '86f0b41fbd1d1e2489011ed3649696b50ad7cebd4375cc1725a382724ed60235', 'parent_positions': []}, {'ticker': 'PRFT', 'security_id': '183768544366008802', 'session': '2024-09-30', 'native_session': '2024-10-01', 'native_term_sha256': '3e51dd694101fef4a99b3f1fbfb9764802b072776546b77886be7036c6a47602', 'parent_positions': []}, {'ticker': 'LBPH', 'security_id': '355279027800974395', 'session': '2024-11-27', 'native_session': '2024-11-29', 'native_term_sha256': 'e65b583e8e8358e98294987b3fcaa172ce122bb744aa1fc51a875ee73a48d669', 'parent_positions': []}, {'ticker': 'CDMO', 'security_id': '641708992638960500', 'session': '2025-02-03', 'native_session': '2025-02-04', 'native_term_sha256': '7b2b81fd18a7ea21785d94eb2d6b0a2a6094d071cdf39e29adc90f9c676955fd', 'parent_positions': []}, {'ticker': 'RVNC', 'security_id': '561615213934063912', 'session': '2025-02-04', 'native_session': '2025-02-05', 'native_term_sha256': '9cc4f56192bc679401bac4693ef257ac1b8cf604d3fc3b3e3ba2e078ff3115de', 'parent_positions': []}, {'ticker': 'SUM', 'security_id': '364431306575234844', 'session': '2025-02-06', 'native_session': '2025-02-07', 'native_term_sha256': '5255ddbfa9b5ea696b66534c6b3164df88d207f1b11376bfb1b3fba9c8676e97', 'parent_positions': []}, {'ticker': 'ZUO', 'security_id': '699288853008671138', 'session': '2025-02-12', 'native_session': '2025-02-13', 'native_term_sha256': '21579cffcc2f2314a8b6c950019e8f9712892ab0cfd48e790acbf605fd0f2842', 'parent_positions': []}, {'ticker': 'NARI', 'security_id': '543768354908702200', 'session': '2025-02-14', 'native_session': '2025-02-18', 'native_term_sha256': '762b3b541e1666ae72f6f3acf2715ada57262f3663b9262e94f04e01bbcdf584', 'parent_positions': []}, {'ticker': 'OMIC', 'security_id': '252574123696847206', 'session': '2025-02-19', 'native_session': '2025-02-20', 'native_term_sha256': 'd34f99ecf7288747480d57847fe6e0e037a62958a82bbe1b2705e09dd2c81932', 'parent_positions': []}, {'ticker': 'HCP', 'security_id': '610550191134128154', 'session': '2025-02-25', 'native_session': '2025-02-26', 'native_term_sha256': '1ff4c354fc5ce990d341e498439ddae9a0ee850bb942067d25cfb75b04b91d95', 'parent_positions': []}, {'ticker': 'MTTR', 'security_id': '268723442486744870', 'session': '2025-02-26', 'native_session': '2025-02-27', 'native_term_sha256': '421d2c626abc23c56c22ffc5ecf7f94f5b42620dd5af1255c4464c232b2b3fbb', 'parent_positions': []}, {'ticker': 'INFN', 'security_id': '472454776648049441', 'session': '2025-02-26', 'native_session': '2025-02-27', 'native_term_sha256': 'fa976bbcc5bd0458c6eb3e8018c80f42d0b7133b2d11a9e32ac3ea5ff12c15f1', 'parent_positions': []}, {'ticker': 'EMKR', 'security_id': '106733641894872523', 'session': '2025-02-27', 'native_session': '2025-02-28', 'native_term_sha256': '4065446c280d39ce8be2e4d835e35462eebccddb90cd77e3cf98ddc4aaa501d0', 'parent_positions': []}, {'ticker': 'ALTM', 'security_id': '683269517186158393', 'session': '2025-03-04', 'native_session': '2025-03-05', 'native_term_sha256': '96ab26959f6e9d842ba4410a4903bca9907a1ca5465bc95bc156b32121acb0f3', 'parent_positions': []}, {'ticker': 'AZPN', 'security_id': '556944515102158299', 'session': '2025-03-10', 'native_session': '2025-03-11', 'native_term_sha256': '173f226d9a15bf7e782de041d3679c4480aca4b96952f910c4add848fa94bfa6', 'parent_positions': []}, {'ticker': 'DFS', 'security_id': '884366050981445610', 'session': '2025-05-15', 'native_session': '2025-05-16', 'native_term_sha256': '638b0d51e7a7601a41b651932bec0d789a2da27e17159048300b29f7f2d33fdb', 'parent_positions': []}, {'ticker': 'JNPR', 'security_id': '949392331435765708', 'session': '2025-06-30', 'native_session': '2025-07-01', 'native_term_sha256': 'eea71df25ce86ef99f87d8505cf6920884cc8a66b3aeb2d7557e74f6d295aa4c', 'parent_positions': []}, {'ticker': 'BPMC', 'security_id': '142211284179578270', 'session': '2025-07-16', 'native_session': '2025-07-17', 'native_term_sha256': '77b3dd31d5a77ecbdcaf505630a891933e79b09e614dcfdff19ec56a025e7e5b', 'parent_positions': []}, {'ticker': 'TGI', 'security_id': '498918945550351909', 'session': '2025-07-23', 'native_session': '2025-07-24', 'native_term_sha256': 'd64927eb0e80aa8e0a5e596cb60a510b45896548ea33f082442ae8a7a9a40580', 'parent_positions': []}, {'ticker': 'AMED', 'security_id': '207977697074649672', 'session': '2025-08-13', 'native_session': '2025-08-14', 'native_term_sha256': '22df39e836fa2f92088ae209ad2a09c085d18d7828432cf1b7b262576064be4e', 'parent_positions': []}, {'ticker': 'ETNB', 'security_id': '146334772721825722', 'session': '2025-10-29', 'native_session': '2025-10-30', 'native_term_sha256': 'bf5577c47d4d69ceaf8bf547c840580a079b495852b4d089f661bc1e5a4b7c89', 'parent_positions': []}, {'ticker': 'LNWO', 'security_id': '467726443352731838', 'session': '2025-11-13', 'native_session': '2025-11-14', 'native_term_sha256': '6cc2c176c4e2289531450e4bbfc11a0434114506766daed1310363a9ad6aff8d', 'parent_positions': []}, {'ticker': 'CDTX', 'security_id': '1113557341267806383', 'session': '2026-01-05', 'native_session': '2026-01-06', 'native_term_sha256': '944993f17a9eb2dcf26081fed8e05fba416f9a136b69a8e9255f5a2150f1374e', 'parent_positions': []}, {'ticker': 'SHCO', 'security_id': '162004720301108303', 'session': '2026-01-27', 'native_session': '2026-01-28', 'native_term_sha256': '1925b21534a70b9b25ab331350bf9cf46d37f397925c733c7f96a8e0c22d27c5', 'parent_positions': []}, {'ticker': 'RAPT', 'security_id': '117211213247402731', 'session': '2026-03-02', 'native_session': '2026-03-03', 'native_term_sha256': '77a4ab952aca53203df5a4972a51aac2d8d55669f32ac56c863fa64b896dbed0', 'parent_positions': []}, {'ticker': 'EXAS', 'security_id': '637262944715750985', 'session': '2026-03-19', 'native_session': '2026-03-20', 'native_term_sha256': '689adccb69cd2f499298678e43c60d83e73de51f1af1ba8f4de739aabc85ccbd', 'parent_positions': []}, {'ticker': 'TERN', 'security_id': '961294553911856115', 'session': '2026-05-01', 'native_session': '2026-05-04', 'native_term_sha256': 'ee9a9ee8b82e907c6b0024834ae9e9ac4aef4341358e57556926fa955e0139d0', 'parent_positions': []}, {'ticker': 'SLNO', 'security_id': '736275735073520563', 'session': '2026-05-15', 'native_session': '2026-05-18', 'native_term_sha256': '2394da8743a299b2acf321096a51c90ac0e499222a56832d58a50b28bcba849a', 'parent_positions': []}, {'ticker': 'AMWD', 'security_id': '332224216763941431', 'session': '2026-05-27', 'native_session': '2026-05-28', 'native_term_sha256': '51e18a8ab3c72cae703c490a0a432edc46bae19bbf5146f8228127d2ab9b21eb', 'parent_positions': []}, {'ticker': 'TMHC', 'security_id': '13062188894457483', 'session': '2026-07-22', 'native_session': '2026-07-23', 'native_term_sha256': '11fd2c4548f637a6ce8f3083ca50cb2f616f4f4e4c185ff46f745b5b51a4a2c8', 'parent_positions': []}, {'ticker': 'ORLA', 'security_id': '622077003929363486', 'session': '2026-07-30', 'native_session': '2026-07-31', 'native_term_sha256': '38af459b36abb7bbd88339f114ac17c3755db5be8836982edd3077f36e8b65da', 'parent_positions': []}], 'additional_rows': []}
EXTRA_WITNESS_SCOPES[('P03', '2019-10-31-remaining-original-cash-natives')] = {'parent_outer_sha256': 'e229d73086f5c907ebff065be97c9a8eb090520a6dc3a55e6a1649c1e3efd3fd', 'parent_cursor': '2019-10-31', 'terms': [{'ticker': 'DOVA', 'security_id': '471435039050105714', 'session': '2019-11-11', 'native_session': '2019-11-12', 'native_term_sha256': 'f2b36754d579bab94b67cc9628f9e32cd927189466c99c428b7c1ca977dfd41f', 'parent_positions': []}, {'ticker': 'WPX', 'security_id': '993356691887576902', 'session': '2021-01-05', 'native_session': '2021-01-06', 'native_term_sha256': '457c96c2ef3e941e99f23d23570fc5ebf7b74adc1526b3758a6f9ddf6b2f71e3', 'parent_positions': []}, {'ticker': 'PE', 'security_id': '980948154175032078', 'session': '2021-01-11', 'native_session': '2021-01-12', 'native_term_sha256': 'e90cbdcc47e4210620a777fbf5da4b24b097c62dae6a9be92310e36def8148d2', 'parent_positions': []}, {'ticker': 'BEAT1', 'security_id': '67573316626643986', 'session': '2021-02-05', 'native_session': '2021-02-08', 'native_term_sha256': '61ae8c758f78cf78e5ba10830395ff7bfc4c3f247f8235a44bd28854b3791370', 'parent_positions': []}, {'ticker': 'VRTU', 'security_id': '148561310122246389', 'session': '2021-02-09', 'native_session': '2021-02-10', 'native_term_sha256': '0f9384af445d749b38084dd39e6e18486bf1d548cb595573818dbaee455bc8ec', 'parent_positions': []}, {'ticker': 'ACIA', 'security_id': '43443874000076334', 'session': '2021-02-25', 'native_session': '2021-02-26', 'native_term_sha256': '34e39e53f1bd2e528acb414422fc3c0e9cde54d3811b556e7f96d64fde390cce', 'parent_positions': []}, {'ticker': 'VAR', 'security_id': '258412215698403601', 'session': '2021-04-13', 'native_session': '2021-04-14', 'native_term_sha256': 'a184b667de19c35ba2c9a3ba3e1b80e0e132ef9c20d6bae283ef5d5644fde7d8', 'parent_positions': []}, {'ticker': 'MIK', 'security_id': '350829412574453923', 'session': '2021-04-13', 'native_session': '2021-04-14', 'native_term_sha256': '92b5b048e834f32ec0b4b8679cbace152ec986b064e5d0637c80a937ea472202', 'parent_positions': []}, {'ticker': 'IPHI', 'security_id': '417303318744640788', 'session': '2021-04-19', 'native_session': '2021-04-20', 'native_term_sha256': '784f0b044d83705dd144f20dda7dc87392ce7567336185b84d49811aabf2f518', 'parent_positions': []}, {'ticker': 'APHA', 'security_id': '1056418588994492299', 'session': '2021-04-29', 'native_session': '2021-04-30', 'native_term_sha256': '31b315bf0ae426ae1216fb3fa44dc6d4d084313ce05786b4c7b2082a62b5f6bb', 'parent_positions': []}, {'ticker': 'CATM', 'security_id': '1127660475946542495', 'session': '2021-06-17', 'native_session': '2021-06-18', 'native_term_sha256': '070bed00fbafec28dd4c16c22728f6655e10bb1c1f67468bc06265bb33acb8cc', 'parent_positions': []}, {'ticker': 'NAV', 'security_id': '515332170991709358', 'session': '2021-06-29', 'native_session': '2021-06-30', 'native_term_sha256': '87224dc2937f8eba47e669e77e4f4ad676c56da6102f9975987482009709b621', 'parent_positions': []}, {'ticker': 'WORK', 'security_id': '753795210944150814', 'session': '2021-07-19', 'native_session': '2021-07-20', 'native_term_sha256': 'c14243b48f1f69a67752c093015abd9f415c235fe78c0802383c961b3600891b', 'parent_positions': []}, {'ticker': 'HOME', 'security_id': '914962085458002202', 'session': '2021-07-21', 'native_session': '2021-07-22', 'native_term_sha256': '7d3c8178c314fbdc8ae67722803989e46fa94e91c9843a2fe15602bd2823ac97', 'parent_positions': []}, {'ticker': 'TBIO1', 'security_id': '806305554838952699', 'session': '2021-09-13', 'native_session': '2021-09-14', 'native_term_sha256': '21a8dbee62e98d9e505d01edfd7350622e2e35294ab52bc014698d625b0f7859', 'parent_positions': []}, {'ticker': 'TRIL1', 'security_id': '1119755750402433659', 'session': '2021-11-15', 'native_session': '2021-11-16', 'native_term_sha256': '5057f8ad3fa88626ef5f2898847655a461bc8cea4c2d09270e199716b365dd43', 'parent_positions': []}, {'ticker': 'UFS', 'security_id': '1123376669724901530', 'session': '2021-11-26', 'native_session': '2021-11-29', 'native_term_sha256': '93470bf15871ab34659f8452d9d4bfa96242d8eee58bff2d5918d9f28c824447', 'parent_positions': []}, {'ticker': 'MDP', 'security_id': '1072510367992802359', 'session': '2021-11-30', 'native_session': '2021-12-01', 'native_term_sha256': 'c0415c1aa5fc0a0205ade497e308f194d403687c8db4c77cd413da22a21748b8', 'parent_positions': []}, {'ticker': 'COR2', 'security_id': '1112840042710916617', 'session': '2021-12-23', 'native_session': '2021-12-27', 'native_term_sha256': 'd45db785ce4ce0fdad553a53b34f1426666de01e076b9e2e841b6b199b8049dd', 'parent_positions': []}, {'ticker': 'DRNA', 'security_id': '241515261501228040', 'session': '2021-12-23', 'native_session': '2021-12-27', 'native_term_sha256': '8d9afe459a7f4253f3c1f489449c0b835ca6de6fae45120ab733ce5a304ae554', 'parent_positions': []}, {'ticker': 'VCRA', 'security_id': '576374012507208201', 'session': '2022-02-18', 'native_session': '2022-02-22', 'native_term_sha256': '96d66e520046facaa9871daea03f370b8714e39c410e508854b7abaf72cdb649', 'parent_positions': []}, {'ticker': 'ZGNX', 'security_id': '732226698577723721', 'session': '2022-03-03', 'native_session': '2022-03-04', 'native_term_sha256': '34fa057e5cca33a2885a6b2025c0ebde09f03a6f8ab2371fa5136b67c7b1fcb7', 'parent_positions': []}, {'ticker': 'ARNA', 'security_id': '1028361513614760286', 'session': '2022-03-10', 'native_session': '2022-03-11', 'native_term_sha256': 'afccf7b8698e0c04849091bc7f7f3a7758595cf52fa775a37f22e040cad3b6bb', 'parent_positions': []}, {'ticker': 'HMHC', 'security_id': '875684930968851666', 'session': '2022-04-05', 'native_session': '2022-04-06', 'native_term_sha256': '2e28ff8f4c521842ff9344f35ff1fcd7b14059897930661bd53dc75e92c64abf', 'parent_positions': []}, {'ticker': 'GNOG', 'security_id': '492385206273420565', 'session': '2022-05-03', 'native_session': '2022-05-04', 'native_term_sha256': '04c3597fed20e3dde7fa44db154cad48a097d1737f419fafd1b70074a95cfe33', 'parent_positions': []}, {'ticker': 'XENT', 'security_id': '948589239641460025', 'session': '2022-05-11', 'native_session': '2022-05-12', 'native_term_sha256': '7ec878d790620777a8e43b53ee60903959627938b58e36397560051d5eacb03f', 'parent_positions': []}, {'ticker': 'EPAY', 'security_id': '302828589827843603', 'session': '2022-05-12', 'native_session': '2022-05-13', 'native_term_sha256': '5eb674cff87d9baba04ab103475f0bccc7fef9ba1dcfb03d476ae6a7c20a80f4', 'parent_positions': []}, {'ticker': 'AZPN1', 'security_id': '223345417151181882', 'session': '2022-05-13', 'native_session': '2022-05-16', 'native_term_sha256': '79fc7e1f6db87e47b08a3dcbd746b92021c7d9d7627a9bf1473605be4e00608a', 'parent_positions': []}, {'ticker': 'MIME', 'security_id': '988236261397113691', 'session': '2022-05-17', 'native_session': '2022-05-18', 'native_term_sha256': '1ea2abbb8cd4e10bae112ca8aaa7cd87822db91afbcaaa52ad6da417b8c4d0d6', 'parent_positions': []}, {'ticker': 'ANAT', 'security_id': '43437726633884038', 'session': '2022-05-23', 'native_session': '2022-05-24', 'native_term_sha256': 'aa8af4c300137446a2cadbeed4361abab75e51e5fc5df0aeb86720fa501629f2', 'parent_positions': []}, {'ticker': 'REGI', 'security_id': '1012599037173653936', 'session': '2022-06-09', 'native_session': '2022-06-10', 'native_term_sha256': 'db8331a6239b9aadba37604efb31c8e0cec398a975859cd376bc8a7c53ffb619', 'parent_positions': []}, {'ticker': 'PLAN', 'security_id': '621163045039428157', 'session': '2022-06-17', 'native_session': '2022-06-21', 'native_term_sha256': 'dd03d1787c5e048af217a9f9313ea4347123dd290c0ee01feac24811b68c89e6', 'parent_positions': []}, {'ticker': 'MSP', 'security_id': '892733995247202485', 'session': '2022-06-21', 'native_session': '2022-06-22', 'native_term_sha256': '5018fbc936ffda49edf56862746b3be103144fd0b7b400c46e7e6ac4dfca71f7', 'parent_positions': []}, {'ticker': 'TVTY', 'security_id': '506048722516044547', 'session': '2022-06-24', 'native_session': '2022-06-27', 'native_term_sha256': 'aca7bf92b9c5faea11cf82b77b7e081e728242a3775f9ba2f435da3015236e95', 'parent_positions': []}, {'ticker': 'CCMP', 'security_id': '361307705630329294', 'session': '2022-07-01', 'native_session': '2022-07-05', 'native_term_sha256': 'e6b906f60567135af8a2d339bb3cfbb866d6a3236b446f4a7e402d6456ad915d', 'parent_positions': []}, {'ticker': 'SAFM', 'security_id': '962454383671746307', 'session': '2022-07-20', 'native_session': '2022-07-21', 'native_term_sha256': 'd00cf559bcc50db02d1e30e69194f3f92949e1085b4bd23b53c4f134aba86d09', 'parent_positions': []}, {'ticker': 'ACC', 'security_id': '209530306982231273', 'session': '2022-08-08', 'native_session': '2022-08-09', 'native_term_sha256': 'dedc2034f8b43302ab25e6be16e3c4896563412b8510b3cb4083281b6cbf21a7', 'parent_positions': []}, {'ticker': 'CTXS', 'security_id': '554480052825212855', 'session': '2022-09-28', 'native_session': '2022-09-29', 'native_term_sha256': '6c306190c326bc01b52d3fb9fda5f2cd2cdf09fdc447cb5a41064136c6c4329a', 'parent_positions': []}, {'ticker': 'DRE', 'security_id': '518054177581800417', 'session': '2022-09-29', 'native_session': '2022-09-30', 'native_term_sha256': '713092be4dbb3c3f9ba9d72f027191a8e5394a69087bbd98b7351d19c7d94c3c', 'parent_positions': []}, {'ticker': 'GBT', 'security_id': '827416728546053456', 'session': '2022-10-03', 'native_session': '2022-10-04', 'native_term_sha256': '24ecdb67869b11470699c0bf1a02ca59f46d671bd9008d196f4a80cd05c46500', 'parent_positions': []}, {'ticker': 'FMTX', 'security_id': '321650252292096156', 'session': '2022-10-12', 'native_session': '2022-10-13', 'native_term_sha256': '520764575d781727341e687841e205e9404aff6726da7de2bc8e58a9864d18d4', 'parent_positions': []}, {'ticker': 'PING', 'security_id': '23427772744584579', 'session': '2022-10-14', 'native_session': '2022-10-17', 'native_term_sha256': 'b1481b42046cb67003a896150c6f7f9b28910b29f1b5a53ec35ef219bd4a78f0', 'parent_positions': []}, {'ticker': 'AVLR', 'security_id': '652370478798714876', 'session': '2022-10-17', 'native_session': '2022-10-18', 'native_term_sha256': '10943a680bf8b4a98575225ee89ecabce5e8ed3bf066ed318e8ef5db55d5bc5f', 'parent_positions': []}, {'ticker': 'Y', 'security_id': '683977592320274232', 'session': '2022-10-17', 'native_session': '2022-10-18', 'native_term_sha256': 'a32a8b2e023dedf84185a5b7d3847b546bc29f0ff99b0186c05019dd91d9ab90', 'parent_positions': []}, {'ticker': 'CCXI1', 'security_id': '659896685009177378', 'session': '2022-10-18', 'native_session': '2022-10-19', 'native_term_sha256': 'f1c92007dac927423e7703ac280ca4de869a7b275b323e127b7b6e0c5f9c6dca', 'parent_positions': []}, {'ticker': 'CYBE', 'security_id': '738630690199421979', 'session': '2022-11-02', 'native_session': '2022-11-03', 'native_term_sha256': '4284b79a3b3954191aa59af15c07a06e626cb2340fc4834100ec506631670ef1', 'parent_positions': []}, {'ticker': 'ZEN', 'security_id': '870865871230451373', 'session': '2022-11-18', 'native_session': '2022-11-21', 'native_term_sha256': '4eb6cbadfb1fd10a87741ed05f2e3d7025700280835e49f4f838d071b0600dd2', 'parent_positions': []}, {'ticker': 'ABMD', 'security_id': '1050970006012443443', 'session': '2022-12-20', 'native_session': '2022-12-21', 'native_term_sha256': '815f61b085dee89b89956834f250763522bff5402fdcc3d36ebb36c85d0796e4', 'parent_positions': []}, {'ticker': 'SJI', 'security_id': '255755003526074655', 'session': '2023-01-30', 'native_session': '2023-01-31', 'native_term_sha256': '3cdb7e9ae9227a2ff6d47e2e40240b74e8d10854ec1eb4591c5c2a039f2a72fb', 'parent_positions': []}, {'ticker': 'LHCG', 'security_id': '348961068556052300', 'session': '2023-02-17', 'native_session': '2023-02-21', 'native_term_sha256': 'b13c3cdc8ce1b9651108d79ca572c1a7f10aefa5a204c35fb1c8fbd28b3e3e37', 'parent_positions': []}, {'ticker': 'ONEM', 'security_id': '677864286983813096', 'session': '2023-02-21', 'native_session': '2023-02-22', 'native_term_sha256': '7930c9741ebd86ef403aa2c1f8a64e36a627c9db3bc4e3993fae29a438ca6d1d', 'parent_positions': []}, {'ticker': 'COUP', 'security_id': '840778708963135084', 'session': '2023-02-24', 'native_session': '2023-02-27', 'native_term_sha256': '23dcc826824e13c0137d03ff260ecac5fc4a79b0f945363946c9511ae6e567c7', 'parent_positions': []}, {'ticker': 'EVOP', 'security_id': '754975132000056845', 'session': '2023-03-22', 'native_session': '2023-03-23', 'native_term_sha256': '4ae01e26dfd27924a8973b40c79e755ff31adfba0be52e9ee9779fd8ca9679b3', 'parent_positions': []}, {'ticker': 'SGFY', 'security_id': '151225572607695758', 'session': '2023-03-27', 'native_session': '2023-03-28', 'native_term_sha256': 'b62f3cd219734387c09081d63dac7858e2b28ffd6f41ae29b39a9ebe0dcaa940', 'parent_positions': []}, {'ticker': 'CEMI', 'security_id': '1089594935488302817', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': 'c3fe2a1af242ed612fe1d9d7a4042bcde7a840011b1c2843c9227285f625101c', 'parent_positions': []}, {'ticker': 'CSII', 'security_id': '50040477475186027', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': '04260434a5ee3eccb4a082ab5f969d49790e8a76738cb3534260811cbd14cf58', 'parent_positions': []}, {'ticker': 'PRVB', 'security_id': '858933953652218125', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': '0425d032b38ebf0099beec0a7556f66368d3cba1a7ee82a455d28d3908331d39', 'parent_positions': []}, {'ticker': 'OSH', 'security_id': '917666101373510238', 'session': '2023-04-28', 'native_session': '2023-05-01', 'native_term_sha256': '3bfd185a3434b5e62dde7aa56683f1f9c82f61150541f8ae0871d0f2b16db450', 'parent_positions': []}, {'ticker': 'MAXR', 'security_id': '192029376284057522', 'session': '2023-05-01', 'native_session': '2023-05-02', 'native_term_sha256': '8165277eedd833036d96db039d1432df89514fc53800e6d5cd8f05c977efcd8b', 'parent_positions': []}, {'ticker': 'SUMO', 'security_id': '233469495168272142', 'session': '2023-05-10', 'native_session': '2023-05-11', 'native_term_sha256': 'cd4f6ea36d9e3a6475dcd9a6f34f93feefd20699f4df36992a4a6c1f9aad2a23', 'parent_positions': []}, {'ticker': 'TA', 'security_id': '273582270998538925', 'session': '2023-05-11', 'native_session': '2023-05-12', 'native_term_sha256': '77d6eedc0731bf0b61f05abbe341d3a6d0ededaff2b99f5f18efe6d7047bcff2', 'parent_positions': []}, {'ticker': 'MNTV', 'security_id': '62458272022348266', 'session': '2023-05-30', 'native_session': '2023-05-31', 'native_term_sha256': 'dc62d52a52598231f5a244624e60bca0f72789db27ccc30ddf212c568ec3f870', 'parent_positions': []}, {'ticker': 'MGI', 'security_id': '631714153765036714', 'session': '2023-05-30', 'native_session': '2023-05-31', 'native_term_sha256': '5d5e99a5c938874325db2c8ca83c2c8aaee2901eb86599b21a250fd6a4880b6c', 'parent_positions': []}, {'ticker': 'HSKA', 'security_id': '1132165486668118439', 'session': '2023-06-09', 'native_session': '2023-06-12', 'native_term_sha256': 'be6349194d300cb9195944599ddba0d2c80c0f3afbb7e22295d12033c20a5fe0', 'parent_positions': []}, {'ticker': 'RUTH', 'security_id': '129751434275280834', 'session': '2023-06-12', 'native_session': '2023-06-13', 'native_term_sha256': '882d416fd8b3dd611ec9d7c0c83b6b08d4499cffdd2a0e93d656fa5371e7c016', 'parent_positions': []}, {'ticker': 'CVT', 'security_id': '373813670584114036', 'session': '2023-06-13', 'native_session': '2023-06-14', 'native_term_sha256': 'edbc4944cd6c2348a4fc175801a4869a5b0f2bebd324701dad850720876eb002', 'parent_positions': []}, {'ticker': 'RXDX', 'security_id': '1140650572960055100', 'session': '2023-06-14', 'native_session': '2023-06-15', 'native_term_sha256': '47b894ab6a5b05ba753783dbe031d6ec14c47abd32a2db18bd0c529c5039c91c', 'parent_positions': []}, {'ticker': 'CTIC', 'security_id': '394927144545790620', 'session': '2023-06-22', 'native_session': '2023-06-23', 'native_term_sha256': '4a9acb1a7af4fccfbb8ba40f0c072130e4fb8215ee46caef40740fe3a5ba97e7', 'parent_positions': []}, {'ticker': 'XM', 'security_id': '348606319062466815', 'session': '2023-06-26', 'native_session': '2023-06-27', 'native_term_sha256': '131487cf7ccf68c542c39afe70909c80e6c445fc8bf83367c973f5f8b107eded', 'parent_positions': []}, {'ticker': 'ISEE', 'security_id': '477302961403569227', 'session': '2023-07-07', 'native_session': '2023-07-10', 'native_term_sha256': '670cd42f7b0bd828e76d5ac0f5b8e9f7e311271278275ce261efd8fe0e368c79', 'parent_positions': []}, {'ticker': 'LSI', 'security_id': '753641750484343508', 'session': '2023-07-18', 'native_session': '2023-07-19', 'native_term_sha256': 'ccb498dd580b7f803166463271de8bfb95d1c9f362efaa4f50c0398ed7fdf677', 'parent_positions': []}, {'ticker': 'AJRD', 'security_id': '721679296374852573', 'session': '2023-07-26', 'native_session': '2023-07-27', 'native_term_sha256': 'c18c68ef2a138d80a1bf1325d3ece4707e45c2bb6d51ea96a9a3c6dbb402237d', 'parent_positions': []}, {'ticker': 'UNVR', 'security_id': '220188358195861572', 'session': '2023-07-28', 'native_session': '2023-07-31', 'native_term_sha256': 'a268aa3d4745bff6faab92aac962c554b3d771849acb55a4b32479cddf72f047', 'parent_positions': []}, {'ticker': 'DICE', 'security_id': '349504371207456722', 'session': '2023-08-07', 'native_session': '2023-08-08', 'native_term_sha256': '38a801a52f9077b135500f4810995ad7ef957a5b4b7a5482d76478bef2104868', 'parent_positions': []}, {'ticker': 'KDNY', 'security_id': '47247117758471252', 'session': '2023-08-09', 'native_session': '2023-08-10', 'native_term_sha256': '8779121eb314297caa8a05ab20d8b3c5c990fe0849d21026d37e50dee95d4060', 'parent_positions': []}, {'ticker': 'ARNC', 'security_id': '814822139570731593', 'session': '2023-08-16', 'native_session': '2023-08-17', 'native_term_sha256': 'daf6fb3e9cf5d61d39b506306a9fc2694ea08dcde843fb6cbbc2e718adb01084', 'parent_positions': []}, {'ticker': 'FRG', 'security_id': '906280636792711059', 'session': '2023-08-17', 'native_session': '2023-08-18', 'native_term_sha256': 'f3c80eb81e56926df1d9d53c81ab4b84b82386d7cefed6814b61ae3b8cc11187', 'parent_positions': []}, {'ticker': 'FORG', 'security_id': '927598213803887960', 'session': '2023-08-21', 'native_session': '2023-08-22', 'native_term_sha256': '154b48f99dbae1e994a7633ecd833f93f76c00e28e3cdc1976fcee45b050fb04', 'parent_positions': []}, {'ticker': 'CFMS', 'security_id': '356455035813755306', 'session': '2023-08-31', 'native_session': '2023-09-01', 'native_term_sha256': 'aa3825d28c44a4b64c55a3b02a4cbbfef597ab48404d2a1e32f9486a2f9a2ec7', 'parent_positions': []}, {'ticker': 'QUOT', 'security_id': '823579734840521990', 'session': '2023-08-31', 'native_session': '2023-09-01', 'native_term_sha256': 'c5476a5065675eb10be41e3feeb1ea7e108e86f85408d066dcd31f6e17342d80', 'parent_positions': []}, {'ticker': 'WWE', 'security_id': '426024777347801008', 'session': '2023-09-08', 'native_session': '2023-09-11', 'native_term_sha256': 'aa99115df1cfdc59e142e6572adb258decc4adedefcb9815e5cce7dcb030c035', 'parent_positions': [{'slot_id': 14, 'ticker': 'WWE', 'quantity': 68, 'entry_date': '2018-04-27'}]}, {'ticker': 'RADI', 'security_id': '477309164594500719', 'session': '2023-09-19', 'native_session': '2023-09-20', 'native_term_sha256': 'ace7f8e508c49e9862bebc47f5b85a37894e6437a7d42d5abdafd777efa13307', 'parent_positions': []}, {'ticker': 'RETA', 'security_id': '877716075426179792', 'session': '2023-09-22', 'native_session': '2023-09-25', 'native_term_sha256': 'bb0719c54b4ff45a5dc107d9fcfa8f7cd5669dd6ade1d1a361805f2b8135983b', 'parent_positions': []}, {'ticker': 'SYNH', 'security_id': '842403186726794681', 'session': '2023-09-26', 'native_session': '2023-09-27', 'native_term_sha256': 'f39a11f470b2c55aa34ba2fee92b70e9c4d1f68eec97c8bf3873af5d61a98feb', 'parent_positions': []}, {'ticker': 'KLR', 'security_id': '130923305193858293', 'session': '2023-10-03', 'native_session': '2023-10-04', 'native_term_sha256': '9b6dcf1a6f93e6a563f4a0bc2312f856bfb08c2d9fc75a6e0b38916dcd78826a', 'parent_positions': []}, {'ticker': 'HZNP', 'security_id': '383424504385495727', 'session': '2023-10-04', 'native_session': '2023-10-05', 'native_term_sha256': '975c5509c7016e4d4c9f414727ed6a3c40838484cf6da343b472385003b13114', 'parent_positions': []}, {'ticker': 'NATI', 'security_id': '889446746390919934', 'session': '2023-10-09', 'native_session': '2023-10-10', 'native_term_sha256': '8ee5dd6fe1c436bc7a30d96e7ec20e929cdf8c242369af91464bacee3eb2f704', 'parent_positions': []}, {'ticker': 'ATVI', 'security_id': '390513115168803332', 'session': '2023-10-11', 'native_session': '2023-10-12', 'native_term_sha256': 'b8322b6513499f4f499c114e9c9fadd724844fdeedbbefcc760b3e195c5f0b96', 'parent_positions': []}, {'ticker': 'THRN', 'security_id': '835478709412082111', 'session': '2023-10-12', 'native_session': '2023-10-13', 'native_term_sha256': '97b2cb4ce89bb219ecd3e7d67da606e0ac9fdd81d7f4be882ff9047e01e151e7', 'parent_positions': []}, {'ticker': 'HCCI', 'security_id': '717278895849758441', 'session': '2023-10-13', 'native_session': '2023-10-16', 'native_term_sha256': 'f9db95537eff65526bf2f14a0db55bc4b56ec4af6e15b06ae5b6e1b6c0c558c3', 'parent_positions': []}, {'ticker': 'EMAN', 'security_id': '702386900757567766', 'session': '2023-10-16', 'native_session': '2023-10-17', 'native_term_sha256': 'c9df437dd7980f250f9cffff09a21f55d02e0ed5a0267c704036b93411b82f6e', 'parent_positions': []}, {'ticker': 'SCPL', 'security_id': '499254345947670980', 'session': '2023-10-19', 'native_session': '2023-10-20', 'native_term_sha256': '3c90ae13a077222a34f759258b1b26282802a7a92e55993f8ed004716528d299', 'parent_positions': []}, {'ticker': 'PFSW', 'security_id': '343955049285071424', 'session': '2023-10-20', 'native_session': '2023-10-23', 'native_term_sha256': '2281e27d40ce01b2d2de4ba1f5b0599697e3b56c18f519b7d93c2ee2c9eb098f', 'parent_positions': []}, {'ticker': 'FRGI', 'security_id': '1134582194511063389', 'session': '2023-10-26', 'native_session': '2023-10-27', 'native_term_sha256': '923dcea368530e78d8eb6e78459aac40310efe047b812e5ef99d6b9e2e7f31a7', 'parent_positions': []}, {'ticker': 'TRHC', 'security_id': '565033869086694544', 'session': '2023-11-01', 'native_session': '2023-11-02', 'native_term_sha256': '1108ea9d0a40f5e0430bb4bec43b63684134c43d21741868c78e5c7e1d00f835', 'parent_positions': []}, {'ticker': 'AVID', 'security_id': '203591011054715248', 'session': '2023-11-03', 'native_session': '2023-11-06', 'native_term_sha256': '042e3c4ef6a4dde2ce9f6856f7e724c153d5ebe2845fe50d28bf0ae99dfcb0c7', 'parent_positions': []}, {'ticker': 'TWNK', 'security_id': '533554648046407798', 'session': '2023-11-03', 'native_session': '2023-11-06', 'native_term_sha256': '5997cc84706bab5bd04a5c6d9fb6e4fb030ece8d8c5792d8235e36c74d071018', 'parent_positions': []}, {'ticker': 'ICPT', 'security_id': '24026445320701582', 'session': '2023-11-06', 'native_session': '2023-11-07', 'native_term_sha256': '785b1e7a91a20d2184844a21a4c088d32d15ef68991d1771e070f438748eeba1', 'parent_positions': []}, {'ticker': 'NEWR', 'security_id': '333926898180811276', 'session': '2023-11-06', 'native_session': '2023-11-07', 'native_term_sha256': '23d0dfe7e1d209f84a68c666878673381b1748f10a891edcd9a00ad55f66b6c0', 'parent_positions': []}, {'ticker': 'NXGN', 'security_id': '666950814132995667', 'session': '2023-11-07', 'native_session': '2023-11-08', 'native_term_sha256': 'ed9cb4e73661df4a643697ed97054a00608f69de0d9285412a9572841a7c446f', 'parent_positions': []}, {'ticker': 'APRN', 'security_id': '50945802619249724', 'session': '2023-11-09', 'native_session': '2023-11-10', 'native_term_sha256': 'a2d09a62db63201dd04a8c12ef4787e60a1c6076c599cd7d3a2ac6985871b707', 'parent_positions': []}, {'ticker': 'CCF', 'security_id': '296189780333092312', 'session': '2023-11-13', 'native_session': '2023-11-14', 'native_term_sha256': '33540560e81521cdf9e039726ce9e883376fbc76ad2450c12c873c820ba872e5', 'parent_positions': []}, {'ticker': 'ARGO', 'security_id': '742455654792357520', 'session': '2023-11-14', 'native_session': '2023-11-15', 'native_term_sha256': '7e48b25b34915b0efa300614288abeb8d1d7216af5826ea0239f37fe8eaafb20', 'parent_positions': []}, {'ticker': 'SCU', 'security_id': '430094077611721082', 'session': '2023-11-15', 'native_session': '2023-11-16', 'native_term_sha256': '82351662c1b14efd3d8dbd1da67afb8bdd40a87e430a6888186036e119f864d3', 'parent_positions': []}, {'ticker': 'AVTA', 'security_id': '208186199728699255', 'session': '2023-11-24', 'native_session': '2023-11-27', 'native_term_sha256': 'd918e87a2fecd07beb73b36b004f1fd702905fbbed9d2d0a2b881fc313c8c660', 'parent_positions': []}, {'ticker': 'HT', 'security_id': '507062967556352769', 'session': '2023-11-24', 'native_session': '2023-11-27', 'native_term_sha256': '238d86ca42a2db880685f2a7c8293ea58b41862bcff8e438c42fd7b4b35ba482', 'parent_positions': []}, {'ticker': 'VRTV', 'security_id': '383149493474077830', 'session': '2023-11-28', 'native_session': '2023-11-29', 'native_term_sha256': '69ea34393e67ec4cdd0af7f85f5620871305daf50315fd66da35efb50734b847', 'parent_positions': []}, {'ticker': 'GHL', 'security_id': '922568749150320567', 'session': '2023-11-29', 'native_session': '2023-11-30', 'native_term_sha256': '99ea1082f03eba7fcf76b43b7c3c36559c38d4a8d2374d4e557f8c2db3f9819b', 'parent_positions': []}, {'ticker': 'BSQR', 'security_id': '62222139879558786', 'session': '2023-12-06', 'native_session': '2023-12-07', 'native_term_sha256': 'b3838bb28dceabc1c76ac26ac27b90f5db5ac843dbef547b7253c4fa5687ca08', 'parent_positions': []}, {'ticker': 'CTG', 'security_id': '300142723740074716', 'session': '2023-12-11', 'native_session': '2023-12-12', 'native_term_sha256': '4292e34ae26b19e99252bb4c628b69df54db0e23b8b6de5bda8e43f4c3e8bff5', 'parent_positions': []}, {'ticker': 'SGEN', 'security_id': '64011142132727200', 'session': '2023-12-12', 'native_session': '2023-12-13', 'native_term_sha256': '8cf9ddef5b17730a2a94f8cd1a269254addb17d66a5f9b03aa11d9c0b5913f24', 'parent_positions': []}, {'ticker': 'PCTI', 'security_id': '1141467240476407851', 'session': '2023-12-14', 'native_session': '2023-12-15', 'native_term_sha256': '8db22cc6a930d1cd5fc7b4da11e0ef32e57ccad1db59e297acbee83878f1429f', 'parent_positions': []}, {'ticker': 'MDWT', 'security_id': '1032365920179969095', 'session': '2023-12-19', 'native_session': '2023-12-20', 'native_term_sha256': '504add145eb0a287d9566d16d84545a21da7c5678e2880e9be12f35ccfb87e9a', 'parent_positions': []}, {'ticker': 'PATI', 'security_id': '809685213630446666', 'session': '2023-12-20', 'native_session': '2023-12-21', 'native_term_sha256': '6d7e1fca086a7b78aa9c2d7e03a1dc2962624b11581e4e576c50fcbd48fb274e', 'parent_positions': []}, {'ticker': 'LVOX', 'security_id': '321856714299697497', 'session': '2023-12-21', 'native_session': '2023-12-22', 'native_term_sha256': '9252c8e3835e4cac30dc95fcce05def1c1d4f73312b749f8830040fd562a94be', 'parent_positions': []}, {'ticker': 'PNT', 'security_id': '148089382008743586', 'session': '2023-12-22', 'native_session': '2023-12-26', 'native_term_sha256': '2bef242fbc33ad035d6a7d00c35d9d060383d0d6545dd1acb682e4b5527229ce', 'parent_positions': []}, {'ticker': 'CHS', 'security_id': '889536937307159083', 'session': '2024-01-03', 'native_session': '2024-01-04', 'native_term_sha256': '1229c375c50234e641330553576ed882cdcadaf456414e3458f7cbffcf830c5f', 'parent_positions': []}, {'ticker': 'BVH', 'security_id': '156282255624886742', 'session': '2024-01-12', 'native_session': '2024-01-16', 'native_term_sha256': 'a60952df8ed1087a87e58cd1a5a96dc2db90909a91ef321a0ad9ac3a34b51470', 'parent_positions': []}, {'ticker': 'ESMT', 'security_id': '569372934016384054', 'session': '2024-01-24', 'native_session': '2024-01-25', 'native_term_sha256': 'b26f3e70f27e9e8104335899a2485ac05555c1678f5c7cf29f93eb82b9a152c0', 'parent_positions': []}, {'ticker': 'IMGN', 'security_id': '170441452346015322', 'session': '2024-02-08', 'native_session': '2024-02-09', 'native_term_sha256': 'c09607c58f8ec9489f838f63ff6527059c755d2cdf9438f5925f8d8a496951b5', 'parent_positions': []}, {'ticker': 'SPLK', 'security_id': '562947493199996351', 'session': '2024-03-14', 'native_session': '2024-03-15', 'native_term_sha256': '2bfcf1c193d2d87430648498ec0aeb6466c2b924280960aa77bc4120cd85c451', 'parent_positions': []}, {'ticker': 'CBAY', 'security_id': '1020879448423638006', 'session': '2024-03-20', 'native_session': '2024-03-21', 'native_term_sha256': 'd61a1c3436d5ed8b2f5d3535c534ee6dd8aefefa2d95362e2ece751c44198be7', 'parent_positions': []}, {'ticker': 'KAMN', 'security_id': '1131981377127137469', 'session': '2024-04-17', 'native_session': '2024-04-18', 'native_term_sha256': 'f4ad1a4b048535b57c95230ab704f0b20396d89345b75fae190e10d878522bef', 'parent_positions': []}, {'ticker': 'MDC', 'security_id': '990238054080584816', 'session': '2024-04-17', 'native_session': '2024-04-18', 'native_term_sha256': '008b11876071a34917bef3d7cdfe2bfa3385813c1d53165a1a36ae1121677eee', 'parent_positions': []}, {'ticker': 'PXD', 'security_id': '276044719892003870', 'session': '2024-05-01', 'native_session': '2024-05-02', 'native_term_sha256': '75634fb117503001b3c9e09b14f381c25aa4de0dbb9f6cf05db57eee57adde3f', 'parent_positions': []}, {'ticker': 'ALPN', 'security_id': '1079367959124332531', 'session': '2024-05-16', 'native_session': '2024-05-17', 'native_term_sha256': '501ef01c210d47e1194cf165eca0b17cc2e014f52a7b01ea6aef622b1f95a300', 'parent_positions': []}, {'ticker': 'SWAV', 'security_id': '158012003593585084', 'session': '2024-05-29', 'native_session': '2024-05-30', 'native_term_sha256': '011cbd286ef8f6e57519452164b18187177190814dfe5742ce4ac52d70f02a0c', 'parent_positions': []}, {'ticker': 'DCPH', 'security_id': '710952026927009495', 'session': '2024-06-07', 'native_session': '2024-06-10', 'native_term_sha256': '0176813ad5782f9bf8ac9d288c890209119c6e1030675018523f6ba660ed979c', 'parent_positions': []}, {'ticker': 'EVBG', 'security_id': '741035362761868119', 'session': '2024-06-28', 'native_session': '2024-07-01', 'native_term_sha256': '3945592c297ca7206c046072586f3ae7dc328922b05b96e1db7e6f6530b783c9', 'parent_positions': []}, {'ticker': 'ASTR', 'security_id': '1011284967859810069', 'session': '2024-07-16', 'native_session': '2024-07-17', 'native_term_sha256': '4d014735e70d00fde30af61fc710a750d3c724c888a517d220e4fdc864dd8982', 'parent_positions': []}, {'ticker': 'MORF', 'security_id': '977112340201324412', 'session': '2024-08-15', 'native_session': '2024-08-16', 'native_term_sha256': '86f0b41fbd1d1e2489011ed3649696b50ad7cebd4375cc1725a382724ed60235', 'parent_positions': []}, {'ticker': 'PRFT', 'security_id': '183768544366008802', 'session': '2024-09-30', 'native_session': '2024-10-01', 'native_term_sha256': '3e51dd694101fef4a99b3f1fbfb9764802b072776546b77886be7036c6a47602', 'parent_positions': []}, {'ticker': 'LBPH', 'security_id': '355279027800974395', 'session': '2024-11-27', 'native_session': '2024-11-29', 'native_term_sha256': 'e65b583e8e8358e98294987b3fcaa172ce122bb744aa1fc51a875ee73a48d669', 'parent_positions': []}, {'ticker': 'CTLT', 'security_id': '926139522403724450', 'session': '2024-12-16', 'native_session': '2024-12-17', 'native_term_sha256': '3271de7e17ba66ccba86e074949c81af628173cc56a19774ced304bedd7669ba', 'parent_positions': []}, {'ticker': 'CDMO', 'security_id': '641708992638960500', 'session': '2025-02-03', 'native_session': '2025-02-04', 'native_term_sha256': '7b2b81fd18a7ea21785d94eb2d6b0a2a6094d071cdf39e29adc90f9c676955fd', 'parent_positions': []}, {'ticker': 'RVNC', 'security_id': '561615213934063912', 'session': '2025-02-04', 'native_session': '2025-02-05', 'native_term_sha256': '9cc4f56192bc679401bac4693ef257ac1b8cf604d3fc3b3e3ba2e078ff3115de', 'parent_positions': []}, {'ticker': 'SUM', 'security_id': '364431306575234844', 'session': '2025-02-06', 'native_session': '2025-02-07', 'native_term_sha256': '5255ddbfa9b5ea696b66534c6b3164df88d207f1b11376bfb1b3fba9c8676e97', 'parent_positions': []}, {'ticker': 'ZUO', 'security_id': '699288853008671138', 'session': '2025-02-12', 'native_session': '2025-02-13', 'native_term_sha256': '21579cffcc2f2314a8b6c950019e8f9712892ab0cfd48e790acbf605fd0f2842', 'parent_positions': []}, {'ticker': 'NARI', 'security_id': '543768354908702200', 'session': '2025-02-14', 'native_session': '2025-02-18', 'native_term_sha256': '762b3b541e1666ae72f6f3acf2715ada57262f3663b9262e94f04e01bbcdf584', 'parent_positions': []}, {'ticker': 'OMIC', 'security_id': '252574123696847206', 'session': '2025-02-19', 'native_session': '2025-02-20', 'native_term_sha256': 'd34f99ecf7288747480d57847fe6e0e037a62958a82bbe1b2705e09dd2c81932', 'parent_positions': []}, {'ticker': 'HCP', 'security_id': '610550191134128154', 'session': '2025-02-25', 'native_session': '2025-02-26', 'native_term_sha256': '1ff4c354fc5ce990d341e498439ddae9a0ee850bb942067d25cfb75b04b91d95', 'parent_positions': []}, {'ticker': 'MTTR', 'security_id': '268723442486744870', 'session': '2025-02-26', 'native_session': '2025-02-27', 'native_term_sha256': '421d2c626abc23c56c22ffc5ecf7f94f5b42620dd5af1255c4464c232b2b3fbb', 'parent_positions': []}, {'ticker': 'INFN', 'security_id': '472454776648049441', 'session': '2025-02-26', 'native_session': '2025-02-27', 'native_term_sha256': 'fa976bbcc5bd0458c6eb3e8018c80f42d0b7133b2d11a9e32ac3ea5ff12c15f1', 'parent_positions': []}, {'ticker': 'EMKR', 'security_id': '106733641894872523', 'session': '2025-02-27', 'native_session': '2025-02-28', 'native_term_sha256': '4065446c280d39ce8be2e4d835e35462eebccddb90cd77e3cf98ddc4aaa501d0', 'parent_positions': []}, {'ticker': 'ALTM', 'security_id': '683269517186158393', 'session': '2025-03-04', 'native_session': '2025-03-05', 'native_term_sha256': '96ab26959f6e9d842ba4410a4903bca9907a1ca5465bc95bc156b32121acb0f3', 'parent_positions': []}, {'ticker': 'AZPN', 'security_id': '556944515102158299', 'session': '2025-03-10', 'native_session': '2025-03-11', 'native_term_sha256': '173f226d9a15bf7e782de041d3679c4480aca4b96952f910c4add848fa94bfa6', 'parent_positions': []}, {'ticker': 'DFS', 'security_id': '884366050981445610', 'session': '2025-05-15', 'native_session': '2025-05-16', 'native_term_sha256': '638b0d51e7a7601a41b651932bec0d789a2da27e17159048300b29f7f2d33fdb', 'parent_positions': []}, {'ticker': 'JNPR', 'security_id': '949392331435765708', 'session': '2025-06-30', 'native_session': '2025-07-01', 'native_term_sha256': 'eea71df25ce86ef99f87d8505cf6920884cc8a66b3aeb2d7557e74f6d295aa4c', 'parent_positions': []}, {'ticker': 'BPMC', 'security_id': '142211284179578270', 'session': '2025-07-16', 'native_session': '2025-07-17', 'native_term_sha256': '77b3dd31d5a77ecbdcaf505630a891933e79b09e614dcfdff19ec56a025e7e5b', 'parent_positions': []}, {'ticker': 'AMED', 'security_id': '207977697074649672', 'session': '2025-08-13', 'native_session': '2025-08-14', 'native_term_sha256': '22df39e836fa2f92088ae209ad2a09c085d18d7828432cf1b7b262576064be4e', 'parent_positions': []}, {'ticker': 'ETNB', 'security_id': '146334772721825722', 'session': '2025-10-29', 'native_session': '2025-10-30', 'native_term_sha256': 'bf5577c47d4d69ceaf8bf547c840580a079b495852b4d089f661bc1e5a4b7c89', 'parent_positions': []}, {'ticker': 'LNWO', 'security_id': '467726443352731838', 'session': '2025-11-13', 'native_session': '2025-11-14', 'native_term_sha256': '6cc2c176c4e2289531450e4bbfc11a0434114506766daed1310363a9ad6aff8d', 'parent_positions': []}, {'ticker': 'CDTX', 'security_id': '1113557341267806383', 'session': '2026-01-05', 'native_session': '2026-01-06', 'native_term_sha256': '944993f17a9eb2dcf26081fed8e05fba416f9a136b69a8e9255f5a2150f1374e', 'parent_positions': []}, {'ticker': 'SHCO', 'security_id': '162004720301108303', 'session': '2026-01-27', 'native_session': '2026-01-28', 'native_term_sha256': '1925b21534a70b9b25ab331350bf9cf46d37f397925c733c7f96a8e0c22d27c5', 'parent_positions': []}, {'ticker': 'RAPT', 'security_id': '117211213247402731', 'session': '2026-03-02', 'native_session': '2026-03-03', 'native_term_sha256': '77a4ab952aca53203df5a4972a51aac2d8d55669f32ac56c863fa64b896dbed0', 'parent_positions': []}, {'ticker': 'EXAS', 'security_id': '637262944715750985', 'session': '2026-03-19', 'native_session': '2026-03-20', 'native_term_sha256': '689adccb69cd2f499298678e43c60d83e73de51f1af1ba8f4de739aabc85ccbd', 'parent_positions': []}, {'ticker': 'TERN', 'security_id': '961294553911856115', 'session': '2026-05-01', 'native_session': '2026-05-04', 'native_term_sha256': 'ee9a9ee8b82e907c6b0024834ae9e9ac4aef4341358e57556926fa955e0139d0', 'parent_positions': []}, {'ticker': 'SLNO', 'security_id': '736275735073520563', 'session': '2026-05-15', 'native_session': '2026-05-18', 'native_term_sha256': '2394da8743a299b2acf321096a51c90ac0e499222a56832d58a50b28bcba849a', 'parent_positions': []}, {'ticker': 'AMWD', 'security_id': '332224216763941431', 'session': '2026-05-27', 'native_session': '2026-05-28', 'native_term_sha256': '51e18a8ab3c72cae703c490a0a432edc46bae19bbf5146f8228127d2ab9b21eb', 'parent_positions': []}, {'ticker': 'TMHC', 'security_id': '13062188894457483', 'session': '2026-07-22', 'native_session': '2026-07-23', 'native_term_sha256': '11fd2c4548f637a6ce8f3083ca50cb2f616f4f4e4c185ff46f745b5b51a4a2c8', 'parent_positions': []}, {'ticker': 'ORLA', 'security_id': '622077003929363486', 'session': '2026-07-30', 'native_session': '2026-07-31', 'native_term_sha256': '38af459b36abb7bbd88339f114ac17c3755db5be8836982edd3077f36e8b65da', 'parent_positions': []}], 'additional_rows': []}
EXTRA_WITNESS_SCOPES[('P07', '2022-09-30-remaining-original-cash-natives')] = {'parent_outer_sha256': '6e3e15d25a055f5025e51b08712b56cadf8e396eb5866918d43ec4fe08fb4917', 'parent_cursor': '2022-09-30', 'terms': [{'ticker': 'GBT', 'security_id': '827416728546053456', 'session': '2022-10-03', 'native_session': '2022-10-04', 'native_term_sha256': '24ecdb67869b11470699c0bf1a02ca59f46d671bd9008d196f4a80cd05c46500', 'parent_positions': []}, {'ticker': 'ABMD', 'security_id': '1050970006012443443', 'session': '2022-12-20', 'native_session': '2022-12-21', 'native_term_sha256': '815f61b085dee89b89956834f250763522bff5402fdcc3d36ebb36c85d0796e4', 'parent_positions': []}, {'ticker': 'SJI', 'security_id': '255755003526074655', 'session': '2023-01-30', 'native_session': '2023-01-31', 'native_term_sha256': '3cdb7e9ae9227a2ff6d47e2e40240b74e8d10854ec1eb4591c5c2a039f2a72fb', 'parent_positions': []}, {'ticker': 'LHCG', 'security_id': '348961068556052300', 'session': '2023-02-17', 'native_session': '2023-02-21', 'native_term_sha256': 'b13c3cdc8ce1b9651108d79ca572c1a7f10aefa5a204c35fb1c8fbd28b3e3e37', 'parent_positions': []}, {'ticker': 'ONEM', 'security_id': '677864286983813096', 'session': '2023-02-21', 'native_session': '2023-02-22', 'native_term_sha256': '7930c9741ebd86ef403aa2c1f8a64e36a627c9db3bc4e3993fae29a438ca6d1d', 'parent_positions': []}, {'ticker': 'COUP', 'security_id': '840778708963135084', 'session': '2023-02-24', 'native_session': '2023-02-27', 'native_term_sha256': '23dcc826824e13c0137d03ff260ecac5fc4a79b0f945363946c9511ae6e567c7', 'parent_positions': []}, {'ticker': 'EVOP', 'security_id': '754975132000056845', 'session': '2023-03-22', 'native_session': '2023-03-23', 'native_term_sha256': '4ae01e26dfd27924a8973b40c79e755ff31adfba0be52e9ee9779fd8ca9679b3', 'parent_positions': []}, {'ticker': 'SGFY', 'security_id': '151225572607695758', 'session': '2023-03-27', 'native_session': '2023-03-28', 'native_term_sha256': 'b62f3cd219734387c09081d63dac7858e2b28ffd6f41ae29b39a9ebe0dcaa940', 'parent_positions': []}, {'ticker': 'CEMI', 'security_id': '1089594935488302817', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': 'c3fe2a1af242ed612fe1d9d7a4042bcde7a840011b1c2843c9227285f625101c', 'parent_positions': []}, {'ticker': 'CSII', 'security_id': '50040477475186027', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': '04260434a5ee3eccb4a082ab5f969d49790e8a76738cb3534260811cbd14cf58', 'parent_positions': []}, {'ticker': 'PRVB', 'security_id': '858933953652218125', 'session': '2023-04-26', 'native_session': '2023-04-27', 'native_term_sha256': '0425d032b38ebf0099beec0a7556f66368d3cba1a7ee82a455d28d3908331d39', 'parent_positions': []}, {'ticker': 'OSH', 'security_id': '917666101373510238', 'session': '2023-04-28', 'native_session': '2023-05-01', 'native_term_sha256': '3bfd185a3434b5e62dde7aa56683f1f9c82f61150541f8ae0871d0f2b16db450', 'parent_positions': []}, {'ticker': 'MAXR', 'security_id': '192029376284057522', 'session': '2023-05-01', 'native_session': '2023-05-02', 'native_term_sha256': '8165277eedd833036d96db039d1432df89514fc53800e6d5cd8f05c977efcd8b', 'parent_positions': []}, {'ticker': 'SUMO', 'security_id': '233469495168272142', 'session': '2023-05-10', 'native_session': '2023-05-11', 'native_term_sha256': 'cd4f6ea36d9e3a6475dcd9a6f34f93feefd20699f4df36992a4a6c1f9aad2a23', 'parent_positions': []}, {'ticker': 'TA', 'security_id': '273582270998538925', 'session': '2023-05-11', 'native_session': '2023-05-12', 'native_term_sha256': '77d6eedc0731bf0b61f05abbe341d3a6d0ededaff2b99f5f18efe6d7047bcff2', 'parent_positions': []}, {'ticker': 'MNTV', 'security_id': '62458272022348266', 'session': '2023-05-30', 'native_session': '2023-05-31', 'native_term_sha256': 'dc62d52a52598231f5a244624e60bca0f72789db27ccc30ddf212c568ec3f870', 'parent_positions': []}, {'ticker': 'MGI', 'security_id': '631714153765036714', 'session': '2023-05-30', 'native_session': '2023-05-31', 'native_term_sha256': '5d5e99a5c938874325db2c8ca83c2c8aaee2901eb86599b21a250fd6a4880b6c', 'parent_positions': []}, {'ticker': 'HSKA', 'security_id': '1132165486668118439', 'session': '2023-06-09', 'native_session': '2023-06-12', 'native_term_sha256': 'be6349194d300cb9195944599ddba0d2c80c0f3afbb7e22295d12033c20a5fe0', 'parent_positions': []}, {'ticker': 'RUTH', 'security_id': '129751434275280834', 'session': '2023-06-12', 'native_session': '2023-06-13', 'native_term_sha256': '882d416fd8b3dd611ec9d7c0c83b6b08d4499cffdd2a0e93d656fa5371e7c016', 'parent_positions': []}, {'ticker': 'CVT', 'security_id': '373813670584114036', 'session': '2023-06-13', 'native_session': '2023-06-14', 'native_term_sha256': 'edbc4944cd6c2348a4fc175801a4869a5b0f2bebd324701dad850720876eb002', 'parent_positions': []}, {'ticker': 'RXDX', 'security_id': '1140650572960055100', 'session': '2023-06-14', 'native_session': '2023-06-15', 'native_term_sha256': '47b894ab6a5b05ba753783dbe031d6ec14c47abd32a2db18bd0c529c5039c91c', 'parent_positions': []}, {'ticker': 'CTIC', 'security_id': '394927144545790620', 'session': '2023-06-22', 'native_session': '2023-06-23', 'native_term_sha256': '4a9acb1a7af4fccfbb8ba40f0c072130e4fb8215ee46caef40740fe3a5ba97e7', 'parent_positions': []}, {'ticker': 'XM', 'security_id': '348606319062466815', 'session': '2023-06-26', 'native_session': '2023-06-27', 'native_term_sha256': '131487cf7ccf68c542c39afe70909c80e6c445fc8bf83367c973f5f8b107eded', 'parent_positions': []}, {'ticker': 'ISEE', 'security_id': '477302961403569227', 'session': '2023-07-07', 'native_session': '2023-07-10', 'native_term_sha256': '670cd42f7b0bd828e76d5ac0f5b8e9f7e311271278275ce261efd8fe0e368c79', 'parent_positions': []}, {'ticker': 'LSI', 'security_id': '753641750484343508', 'session': '2023-07-18', 'native_session': '2023-07-19', 'native_term_sha256': 'ccb498dd580b7f803166463271de8bfb95d1c9f362efaa4f50c0398ed7fdf677', 'parent_positions': []}, {'ticker': 'AJRD', 'security_id': '721679296374852573', 'session': '2023-07-26', 'native_session': '2023-07-27', 'native_term_sha256': 'c18c68ef2a138d80a1bf1325d3ece4707e45c2bb6d51ea96a9a3c6dbb402237d', 'parent_positions': []}, {'ticker': 'UNVR', 'security_id': '220188358195861572', 'session': '2023-07-28', 'native_session': '2023-07-31', 'native_term_sha256': 'a268aa3d4745bff6faab92aac962c554b3d771849acb55a4b32479cddf72f047', 'parent_positions': []}, {'ticker': 'DICE', 'security_id': '349504371207456722', 'session': '2023-08-07', 'native_session': '2023-08-08', 'native_term_sha256': '38a801a52f9077b135500f4810995ad7ef957a5b4b7a5482d76478bef2104868', 'parent_positions': []}, {'ticker': 'KDNY', 'security_id': '47247117758471252', 'session': '2023-08-09', 'native_session': '2023-08-10', 'native_term_sha256': '8779121eb314297caa8a05ab20d8b3c5c990fe0849d21026d37e50dee95d4060', 'parent_positions': []}, {'ticker': 'ARNC', 'security_id': '814822139570731593', 'session': '2023-08-16', 'native_session': '2023-08-17', 'native_term_sha256': 'daf6fb3e9cf5d61d39b506306a9fc2694ea08dcde843fb6cbbc2e718adb01084', 'parent_positions': []}, {'ticker': 'FRG', 'security_id': '906280636792711059', 'session': '2023-08-17', 'native_session': '2023-08-18', 'native_term_sha256': 'f3c80eb81e56926df1d9d53c81ab4b84b82386d7cefed6814b61ae3b8cc11187', 'parent_positions': []}, {'ticker': 'FORG', 'security_id': '927598213803887960', 'session': '2023-08-21', 'native_session': '2023-08-22', 'native_term_sha256': '154b48f99dbae1e994a7633ecd833f93f76c00e28e3cdc1976fcee45b050fb04', 'parent_positions': []}, {'ticker': 'CFMS', 'security_id': '356455035813755306', 'session': '2023-08-31', 'native_session': '2023-09-01', 'native_term_sha256': 'aa3825d28c44a4b64c55a3b02a4cbbfef597ab48404d2a1e32f9486a2f9a2ec7', 'parent_positions': []}, {'ticker': 'QUOT', 'security_id': '823579734840521990', 'session': '2023-08-31', 'native_session': '2023-09-01', 'native_term_sha256': 'c5476a5065675eb10be41e3feeb1ea7e108e86f85408d066dcd31f6e17342d80', 'parent_positions': []}, {'ticker': 'WWE', 'security_id': '426024777347801008', 'session': '2023-09-08', 'native_session': '2023-09-11', 'native_term_sha256': 'aa99115df1cfdc59e142e6572adb258decc4adedefcb9815e5cce7dcb030c035', 'parent_positions': []}, {'ticker': 'RADI', 'security_id': '477309164594500719', 'session': '2023-09-19', 'native_session': '2023-09-20', 'native_term_sha256': 'ace7f8e508c49e9862bebc47f5b85a37894e6437a7d42d5abdafd777efa13307', 'parent_positions': []}, {'ticker': 'RETA', 'security_id': '877716075426179792', 'session': '2023-09-22', 'native_session': '2023-09-25', 'native_term_sha256': 'bb0719c54b4ff45a5dc107d9fcfa8f7cd5669dd6ade1d1a361805f2b8135983b', 'parent_positions': []}, {'ticker': 'SYNH', 'security_id': '842403186726794681', 'session': '2023-09-26', 'native_session': '2023-09-27', 'native_term_sha256': 'f39a11f470b2c55aa34ba2fee92b70e9c4d1f68eec97c8bf3873af5d61a98feb', 'parent_positions': []}, {'ticker': 'KLR', 'security_id': '130923305193858293', 'session': '2023-10-03', 'native_session': '2023-10-04', 'native_term_sha256': '9b6dcf1a6f93e6a563f4a0bc2312f856bfb08c2d9fc75a6e0b38916dcd78826a', 'parent_positions': []}, {'ticker': 'HZNP', 'security_id': '383424504385495727', 'session': '2023-10-04', 'native_session': '2023-10-05', 'native_term_sha256': '975c5509c7016e4d4c9f414727ed6a3c40838484cf6da343b472385003b13114', 'parent_positions': []}, {'ticker': 'NATI', 'security_id': '889446746390919934', 'session': '2023-10-09', 'native_session': '2023-10-10', 'native_term_sha256': '8ee5dd6fe1c436bc7a30d96e7ec20e929cdf8c242369af91464bacee3eb2f704', 'parent_positions': []}, {'ticker': 'ATVI', 'security_id': '390513115168803332', 'session': '2023-10-11', 'native_session': '2023-10-12', 'native_term_sha256': 'b8322b6513499f4f499c114e9c9fadd724844fdeedbbefcc760b3e195c5f0b96', 'parent_positions': []}, {'ticker': 'THRN', 'security_id': '835478709412082111', 'session': '2023-10-12', 'native_session': '2023-10-13', 'native_term_sha256': '97b2cb4ce89bb219ecd3e7d67da606e0ac9fdd81d7f4be882ff9047e01e151e7', 'parent_positions': []}, {'ticker': 'HCCI', 'security_id': '717278895849758441', 'session': '2023-10-13', 'native_session': '2023-10-16', 'native_term_sha256': 'f9db95537eff65526bf2f14a0db55bc4b56ec4af6e15b06ae5b6e1b6c0c558c3', 'parent_positions': []}, {'ticker': 'EMAN', 'security_id': '702386900757567766', 'session': '2023-10-16', 'native_session': '2023-10-17', 'native_term_sha256': 'c9df437dd7980f250f9cffff09a21f55d02e0ed5a0267c704036b93411b82f6e', 'parent_positions': []}, {'ticker': 'SCPL', 'security_id': '499254345947670980', 'session': '2023-10-19', 'native_session': '2023-10-20', 'native_term_sha256': '3c90ae13a077222a34f759258b1b26282802a7a92e55993f8ed004716528d299', 'parent_positions': []}, {'ticker': 'PFSW', 'security_id': '343955049285071424', 'session': '2023-10-20', 'native_session': '2023-10-23', 'native_term_sha256': '2281e27d40ce01b2d2de4ba1f5b0599697e3b56c18f519b7d93c2ee2c9eb098f', 'parent_positions': []}, {'ticker': 'FRGI', 'security_id': '1134582194511063389', 'session': '2023-10-26', 'native_session': '2023-10-27', 'native_term_sha256': '923dcea368530e78d8eb6e78459aac40310efe047b812e5ef99d6b9e2e7f31a7', 'parent_positions': []}, {'ticker': 'TRHC', 'security_id': '565033869086694544', 'session': '2023-11-01', 'native_session': '2023-11-02', 'native_term_sha256': '1108ea9d0a40f5e0430bb4bec43b63684134c43d21741868c78e5c7e1d00f835', 'parent_positions': []}, {'ticker': 'AVID', 'security_id': '203591011054715248', 'session': '2023-11-03', 'native_session': '2023-11-06', 'native_term_sha256': '042e3c4ef6a4dde2ce9f6856f7e724c153d5ebe2845fe50d28bf0ae99dfcb0c7', 'parent_positions': []}, {'ticker': 'TWNK', 'security_id': '533554648046407798', 'session': '2023-11-03', 'native_session': '2023-11-06', 'native_term_sha256': '5997cc84706bab5bd04a5c6d9fb6e4fb030ece8d8c5792d8235e36c74d071018', 'parent_positions': []}, {'ticker': 'ICPT', 'security_id': '24026445320701582', 'session': '2023-11-06', 'native_session': '2023-11-07', 'native_term_sha256': '785b1e7a91a20d2184844a21a4c088d32d15ef68991d1771e070f438748eeba1', 'parent_positions': []}, {'ticker': 'NXGN', 'security_id': '666950814132995667', 'session': '2023-11-07', 'native_session': '2023-11-08', 'native_term_sha256': 'ed9cb4e73661df4a643697ed97054a00608f69de0d9285412a9572841a7c446f', 'parent_positions': []}, {'ticker': 'APRN', 'security_id': '50945802619249724', 'session': '2023-11-09', 'native_session': '2023-11-10', 'native_term_sha256': 'a2d09a62db63201dd04a8c12ef4787e60a1c6076c599cd7d3a2ac6985871b707', 'parent_positions': []}, {'ticker': 'CCF', 'security_id': '296189780333092312', 'session': '2023-11-13', 'native_session': '2023-11-14', 'native_term_sha256': '33540560e81521cdf9e039726ce9e883376fbc76ad2450c12c873c820ba872e5', 'parent_positions': []}, {'ticker': 'ARGO', 'security_id': '742455654792357520', 'session': '2023-11-14', 'native_session': '2023-11-15', 'native_term_sha256': '7e48b25b34915b0efa300614288abeb8d1d7216af5826ea0239f37fe8eaafb20', 'parent_positions': []}, {'ticker': 'SCU', 'security_id': '430094077611721082', 'session': '2023-11-15', 'native_session': '2023-11-16', 'native_term_sha256': '82351662c1b14efd3d8dbd1da67afb8bdd40a87e430a6888186036e119f864d3', 'parent_positions': []}, {'ticker': 'AVTA', 'security_id': '208186199728699255', 'session': '2023-11-24', 'native_session': '2023-11-27', 'native_term_sha256': 'd918e87a2fecd07beb73b36b004f1fd702905fbbed9d2d0a2b881fc313c8c660', 'parent_positions': []}, {'ticker': 'HT', 'security_id': '507062967556352769', 'session': '2023-11-24', 'native_session': '2023-11-27', 'native_term_sha256': '238d86ca42a2db880685f2a7c8293ea58b41862bcff8e438c42fd7b4b35ba482', 'parent_positions': []}, {'ticker': 'VRTV', 'security_id': '383149493474077830', 'session': '2023-11-28', 'native_session': '2023-11-29', 'native_term_sha256': '69ea34393e67ec4cdd0af7f85f5620871305daf50315fd66da35efb50734b847', 'parent_positions': []}, {'ticker': 'GHL', 'security_id': '922568749150320567', 'session': '2023-11-29', 'native_session': '2023-11-30', 'native_term_sha256': '99ea1082f03eba7fcf76b43b7c3c36559c38d4a8d2374d4e557f8c2db3f9819b', 'parent_positions': []}, {'ticker': 'BSQR', 'security_id': '62222139879558786', 'session': '2023-12-06', 'native_session': '2023-12-07', 'native_term_sha256': 'b3838bb28dceabc1c76ac26ac27b90f5db5ac843dbef547b7253c4fa5687ca08', 'parent_positions': []}, {'ticker': 'CTG', 'security_id': '300142723740074716', 'session': '2023-12-11', 'native_session': '2023-12-12', 'native_term_sha256': '4292e34ae26b19e99252bb4c628b69df54db0e23b8b6de5bda8e43f4c3e8bff5', 'parent_positions': []}, {'ticker': 'SGEN', 'security_id': '64011142132727200', 'session': '2023-12-12', 'native_session': '2023-12-13', 'native_term_sha256': '8cf9ddef5b17730a2a94f8cd1a269254addb17d66a5f9b03aa11d9c0b5913f24', 'parent_positions': []}, {'ticker': 'PCTI', 'security_id': '1141467240476407851', 'session': '2023-12-14', 'native_session': '2023-12-15', 'native_term_sha256': '8db22cc6a930d1cd5fc7b4da11e0ef32e57ccad1db59e297acbee83878f1429f', 'parent_positions': []}, {'ticker': 'MDWT', 'security_id': '1032365920179969095', 'session': '2023-12-19', 'native_session': '2023-12-20', 'native_term_sha256': '504add145eb0a287d9566d16d84545a21da7c5678e2880e9be12f35ccfb87e9a', 'parent_positions': []}, {'ticker': 'PATI', 'security_id': '809685213630446666', 'session': '2023-12-20', 'native_session': '2023-12-21', 'native_term_sha256': '6d7e1fca086a7b78aa9c2d7e03a1dc2962624b11581e4e576c50fcbd48fb274e', 'parent_positions': []}, {'ticker': 'LVOX', 'security_id': '321856714299697497', 'session': '2023-12-21', 'native_session': '2023-12-22', 'native_term_sha256': '9252c8e3835e4cac30dc95fcce05def1c1d4f73312b749f8830040fd562a94be', 'parent_positions': []}, {'ticker': 'PNT', 'security_id': '148089382008743586', 'session': '2023-12-22', 'native_session': '2023-12-26', 'native_term_sha256': '2bef242fbc33ad035d6a7d00c35d9d060383d0d6545dd1acb682e4b5527229ce', 'parent_positions': []}, {'ticker': 'CHS', 'security_id': '889536937307159083', 'session': '2024-01-03', 'native_session': '2024-01-04', 'native_term_sha256': '1229c375c50234e641330553576ed882cdcadaf456414e3458f7cbffcf830c5f', 'parent_positions': []}, {'ticker': 'BVH', 'security_id': '156282255624886742', 'session': '2024-01-12', 'native_session': '2024-01-16', 'native_term_sha256': 'a60952df8ed1087a87e58cd1a5a96dc2db90909a91ef321a0ad9ac3a34b51470', 'parent_positions': []}, {'ticker': 'ESMT', 'security_id': '569372934016384054', 'session': '2024-01-24', 'native_session': '2024-01-25', 'native_term_sha256': 'b26f3e70f27e9e8104335899a2485ac05555c1678f5c7cf29f93eb82b9a152c0', 'parent_positions': []}, {'ticker': 'SPLK', 'security_id': '562947493199996351', 'session': '2024-03-14', 'native_session': '2024-03-15', 'native_term_sha256': '2bfcf1c193d2d87430648498ec0aeb6466c2b924280960aa77bc4120cd85c451', 'parent_positions': []}, {'ticker': 'CBAY', 'security_id': '1020879448423638006', 'session': '2024-03-20', 'native_session': '2024-03-21', 'native_term_sha256': 'd61a1c3436d5ed8b2f5d3535c534ee6dd8aefefa2d95362e2ece751c44198be7', 'parent_positions': []}, {'ticker': 'KAMN', 'security_id': '1131981377127137469', 'session': '2024-04-17', 'native_session': '2024-04-18', 'native_term_sha256': 'f4ad1a4b048535b57c95230ab704f0b20396d89345b75fae190e10d878522bef', 'parent_positions': []}, {'ticker': 'MDC', 'security_id': '990238054080584816', 'session': '2024-04-17', 'native_session': '2024-04-18', 'native_term_sha256': '008b11876071a34917bef3d7cdfe2bfa3385813c1d53165a1a36ae1121677eee', 'parent_positions': []}, {'ticker': 'PXD', 'security_id': '276044719892003870', 'session': '2024-05-01', 'native_session': '2024-05-02', 'native_term_sha256': '75634fb117503001b3c9e09b14f381c25aa4de0dbb9f6cf05db57eee57adde3f', 'parent_positions': []}, {'ticker': 'ALPN', 'security_id': '1079367959124332531', 'session': '2024-05-16', 'native_session': '2024-05-17', 'native_term_sha256': '501ef01c210d47e1194cf165eca0b17cc2e014f52a7b01ea6aef622b1f95a300', 'parent_positions': []}, {'ticker': 'SWAV', 'security_id': '158012003593585084', 'session': '2024-05-29', 'native_session': '2024-05-30', 'native_term_sha256': '011cbd286ef8f6e57519452164b18187177190814dfe5742ce4ac52d70f02a0c', 'parent_positions': []}, {'ticker': 'DCPH', 'security_id': '710952026927009495', 'session': '2024-06-07', 'native_session': '2024-06-10', 'native_term_sha256': '0176813ad5782f9bf8ac9d288c890209119c6e1030675018523f6ba660ed979c', 'parent_positions': []}, {'ticker': 'EVBG', 'security_id': '741035362761868119', 'session': '2024-06-28', 'native_session': '2024-07-01', 'native_term_sha256': '3945592c297ca7206c046072586f3ae7dc328922b05b96e1db7e6f6530b783c9', 'parent_positions': []}, {'ticker': 'ASTR', 'security_id': '1011284967859810069', 'session': '2024-07-16', 'native_session': '2024-07-17', 'native_term_sha256': '4d014735e70d00fde30af61fc710a750d3c724c888a517d220e4fdc864dd8982', 'parent_positions': []}, {'ticker': 'MORF', 'security_id': '977112340201324412', 'session': '2024-08-15', 'native_session': '2024-08-16', 'native_term_sha256': '86f0b41fbd1d1e2489011ed3649696b50ad7cebd4375cc1725a382724ed60235', 'parent_positions': []}, {'ticker': 'PRFT', 'security_id': '183768544366008802', 'session': '2024-09-30', 'native_session': '2024-10-01', 'native_term_sha256': '3e51dd694101fef4a99b3f1fbfb9764802b072776546b77886be7036c6a47602', 'parent_positions': []}, {'ticker': 'LBPH', 'security_id': '355279027800974395', 'session': '2024-11-27', 'native_session': '2024-11-29', 'native_term_sha256': 'e65b583e8e8358e98294987b3fcaa172ce122bb744aa1fc51a875ee73a48d669', 'parent_positions': []}, {'ticker': 'CDMO', 'security_id': '641708992638960500', 'session': '2025-02-03', 'native_session': '2025-02-04', 'native_term_sha256': '7b2b81fd18a7ea21785d94eb2d6b0a2a6094d071cdf39e29adc90f9c676955fd', 'parent_positions': []}, {'ticker': 'RVNC', 'security_id': '561615213934063912', 'session': '2025-02-04', 'native_session': '2025-02-05', 'native_term_sha256': '9cc4f56192bc679401bac4693ef257ac1b8cf604d3fc3b3e3ba2e078ff3115de', 'parent_positions': []}, {'ticker': 'SUM', 'security_id': '364431306575234844', 'session': '2025-02-06', 'native_session': '2025-02-07', 'native_term_sha256': '5255ddbfa9b5ea696b66534c6b3164df88d207f1b11376bfb1b3fba9c8676e97', 'parent_positions': []}, {'ticker': 'ZUO', 'security_id': '699288853008671138', 'session': '2025-02-12', 'native_session': '2025-02-13', 'native_term_sha256': '21579cffcc2f2314a8b6c950019e8f9712892ab0cfd48e790acbf605fd0f2842', 'parent_positions': []}, {'ticker': 'NARI', 'security_id': '543768354908702200', 'session': '2025-02-14', 'native_session': '2025-02-18', 'native_term_sha256': '762b3b541e1666ae72f6f3acf2715ada57262f3663b9262e94f04e01bbcdf584', 'parent_positions': []}, {'ticker': 'OMIC', 'security_id': '252574123696847206', 'session': '2025-02-19', 'native_session': '2025-02-20', 'native_term_sha256': 'd34f99ecf7288747480d57847fe6e0e037a62958a82bbe1b2705e09dd2c81932', 'parent_positions': []}, {'ticker': 'HCP', 'security_id': '610550191134128154', 'session': '2025-02-25', 'native_session': '2025-02-26', 'native_term_sha256': '1ff4c354fc5ce990d341e498439ddae9a0ee850bb942067d25cfb75b04b91d95', 'parent_positions': []}, {'ticker': 'MTTR', 'security_id': '268723442486744870', 'session': '2025-02-26', 'native_session': '2025-02-27', 'native_term_sha256': '421d2c626abc23c56c22ffc5ecf7f94f5b42620dd5af1255c4464c232b2b3fbb', 'parent_positions': []}, {'ticker': 'INFN', 'security_id': '472454776648049441', 'session': '2025-02-26', 'native_session': '2025-02-27', 'native_term_sha256': 'fa976bbcc5bd0458c6eb3e8018c80f42d0b7133b2d11a9e32ac3ea5ff12c15f1', 'parent_positions': []}, {'ticker': 'EMKR', 'security_id': '106733641894872523', 'session': '2025-02-27', 'native_session': '2025-02-28', 'native_term_sha256': '4065446c280d39ce8be2e4d835e35462eebccddb90cd77e3cf98ddc4aaa501d0', 'parent_positions': []}, {'ticker': 'ALTM', 'security_id': '683269517186158393', 'session': '2025-03-04', 'native_session': '2025-03-05', 'native_term_sha256': '96ab26959f6e9d842ba4410a4903bca9907a1ca5465bc95bc156b32121acb0f3', 'parent_positions': []}, {'ticker': 'AZPN', 'security_id': '556944515102158299', 'session': '2025-03-10', 'native_session': '2025-03-11', 'native_term_sha256': '173f226d9a15bf7e782de041d3679c4480aca4b96952f910c4add848fa94bfa6', 'parent_positions': []}, {'ticker': 'DFS', 'security_id': '884366050981445610', 'session': '2025-05-15', 'native_session': '2025-05-16', 'native_term_sha256': '638b0d51e7a7601a41b651932bec0d789a2da27e17159048300b29f7f2d33fdb', 'parent_positions': []}, {'ticker': 'JNPR', 'security_id': '949392331435765708', 'session': '2025-06-30', 'native_session': '2025-07-01', 'native_term_sha256': 'eea71df25ce86ef99f87d8505cf6920884cc8a66b3aeb2d7557e74f6d295aa4c', 'parent_positions': []}, {'ticker': 'BPMC', 'security_id': '142211284179578270', 'session': '2025-07-16', 'native_session': '2025-07-17', 'native_term_sha256': '77b3dd31d5a77ecbdcaf505630a891933e79b09e614dcfdff19ec56a025e7e5b', 'parent_positions': []}, {'ticker': 'AMED', 'security_id': '207977697074649672', 'session': '2025-08-13', 'native_session': '2025-08-14', 'native_term_sha256': '22df39e836fa2f92088ae209ad2a09c085d18d7828432cf1b7b262576064be4e', 'parent_positions': []}, {'ticker': 'ETNB', 'security_id': '146334772721825722', 'session': '2025-10-29', 'native_session': '2025-10-30', 'native_term_sha256': 'bf5577c47d4d69ceaf8bf547c840580a079b495852b4d089f661bc1e5a4b7c89', 'parent_positions': []}, {'ticker': 'LNWO', 'security_id': '467726443352731838', 'session': '2025-11-13', 'native_session': '2025-11-14', 'native_term_sha256': '6cc2c176c4e2289531450e4bbfc11a0434114506766daed1310363a9ad6aff8d', 'parent_positions': []}, {'ticker': 'CDTX', 'security_id': '1113557341267806383', 'session': '2026-01-05', 'native_session': '2026-01-06', 'native_term_sha256': '944993f17a9eb2dcf26081fed8e05fba416f9a136b69a8e9255f5a2150f1374e', 'parent_positions': []}, {'ticker': 'SHCO', 'security_id': '162004720301108303', 'session': '2026-01-27', 'native_session': '2026-01-28', 'native_term_sha256': '1925b21534a70b9b25ab331350bf9cf46d37f397925c733c7f96a8e0c22d27c5', 'parent_positions': []}, {'ticker': 'RAPT', 'security_id': '117211213247402731', 'session': '2026-03-02', 'native_session': '2026-03-03', 'native_term_sha256': '77a4ab952aca53203df5a4972a51aac2d8d55669f32ac56c863fa64b896dbed0', 'parent_positions': []}, {'ticker': 'EXAS', 'security_id': '637262944715750985', 'session': '2026-03-19', 'native_session': '2026-03-20', 'native_term_sha256': '689adccb69cd2f499298678e43c60d83e73de51f1af1ba8f4de739aabc85ccbd', 'parent_positions': []}, {'ticker': 'TERN', 'security_id': '961294553911856115', 'session': '2026-05-01', 'native_session': '2026-05-04', 'native_term_sha256': 'ee9a9ee8b82e907c6b0024834ae9e9ac4aef4341358e57556926fa955e0139d0', 'parent_positions': []}, {'ticker': 'SLNO', 'security_id': '736275735073520563', 'session': '2026-05-15', 'native_session': '2026-05-18', 'native_term_sha256': '2394da8743a299b2acf321096a51c90ac0e499222a56832d58a50b28bcba849a', 'parent_positions': []}, {'ticker': 'AMWD', 'security_id': '332224216763941431', 'session': '2026-05-27', 'native_session': '2026-05-28', 'native_term_sha256': '51e18a8ab3c72cae703c490a0a432edc46bae19bbf5146f8228127d2ab9b21eb', 'parent_positions': []}, {'ticker': 'TMHC', 'security_id': '13062188894457483', 'session': '2026-07-22', 'native_session': '2026-07-23', 'native_term_sha256': '11fd2c4548f637a6ce8f3083ca50cb2f616f4f4e4c185ff46f745b5b51a4a2c8', 'parent_positions': []}, {'ticker': 'ORLA', 'security_id': '622077003929363486', 'session': '2026-07-30', 'native_session': '2026-07-31', 'native_term_sha256': '38af459b36abb7bbd88339f114ac17c3755db5be8836982edd3077f36e8b65da', 'parent_positions': []}], 'additional_rows': []}
EXTRA_WITNESS_SCOPES[('P07', '2022-09-30-trq-normalization-source')] = {'parent_outer_sha256': '6e3e15d25a055f5025e51b08712b56cadf8e396eb5866918d43ec4fe08fb4917', 'parent_cursor': '2022-09-30', 'terms': [{'ticker': 'TRQ', 'security_id': '655209666181687436', 'session': '2022-12-14', 'native_session': '2022-12-15', 'native_term_sha256': '88fc01228c4183c26a1eb963e38d251081453f2bc8acf89d30315309b7376a6a', 'parent_positions': []}], 'additional_rows': []}
WITNESS_SCOPE_REGISTRY = {digest(scope): deepcopy(scope)
    for scopes in (HISTORICAL_WITNESS_SCOPES, NEXT_WITNESS_SCOPES, DISCOVERY_WITNESS_SCOPES, RESOLVED_WITNESS_SCOPES, EXTRA_WITNESS_SCOPES, INITIAL_WITNESS_SCOPES, RESOLVED_TENDER_WITNESS_SCOPES, ROW_QUERY_WITNESS_SCOPES, NATIVE_DATE_WITNESS_SCOPES, NATIVE_INVENTORY_WITNESS_SCOPES, RESOLVED_NATIVE_WITNESS_SCOPES, DISTRIBUTION_WITNESS_SCOPES) for scope in scopes.values()}
ACTIVE_WITNESS_SCOPES = {**{arm: digest(NEXT_WITNESS_SCOPES[arm]) for arm in ('P00', 'P07')},
                         'P04': digest(DISCOVERY_WITNESS_SCOPES['P04'])}
ACTIVE_WITNESS_SCOPES['P00'] = digest(EXTRA_WITNESS_SCOPES['P00', '2025-06-30'])
ACTIVE_WITNESS_SCOPES.update({arm: digest(scope) for arm, scope in INITIAL_WITNESS_SCOPES.items()})
ACTIVE_WITNESS_SCOPES['P04'] = digest(EXTRA_WITNESS_SCOPES['P04', '2025-10-31'])
ACTIVE_WITNESS_SCOPES['P11'] = digest(EXTRA_WITNESS_SCOPES['P11', '2022-05-31'])
ACTIVE_WITNESS_SCOPES['P03'] = digest(ROW_QUERY_WITNESS_SCOPES['P03_PREFIX'])
ACTIVE_WITNESS_SCOPES.update({arm: digest(scope) for arm, scope in NATIVE_DATE_WITNESS_SCOPES.items()})
ACTIVE_WITNESS_SCOPES.update({arm: digest(scope) for arm, scope in NATIVE_INVENTORY_WITNESS_SCOPES.items()})
ACTIVE_WITNESS_SCOPES.update({arm: digest(scope) for arm, scope in RESOLVED_NATIVE_WITNESS_SCOPES.items()})
ACTIVE_WITNESS_SCOPES['P05'] = digest(EXTRA_WITNESS_SCOPES['P05', '2020-01-31'])
ACTIVE_WITNESS_SCOPES['P03'] = digest(EXTRA_WITNESS_SCOPES['P03', '2018-11-30'])
ACTIVE_WITNESS_SCOPES.update({arm: digest(scope) for arm, scope in DISTRIBUTION_WITNESS_SCOPES.items()})
ACTIVE_WITNESS_SCOPES['P05'] = digest(EXTRA_WITNESS_SCOPES['P05', '2020-06-30'])
ACTIVE_WITNESS_SCOPES['P11'] = digest(EXTRA_WITNESS_SCOPES['P11', '2023-06-30'])
ACTIVE_WITNESS_SCOPES['P03'] = digest(EXTRA_WITNESS_SCOPES['P03', '2018-12-31'])
ACTIVE_WITNESS_SCOPES['P05'] = digest(EXTRA_WITNESS_SCOPES[('P05', '2020-11-30')])
ACTIVE_WITNESS_SCOPES['P05'] = digest(EXTRA_WITNESS_SCOPES['P05', '2021-03-31'])
ACTIVE_WITNESS_SCOPES['P06'] = digest(EXTRA_WITNESS_SCOPES['P06', '2020-06-30'])
ACTIVE_WITNESS_SCOPES['P06'] = digest(EXTRA_WITNESS_SCOPES['P06', '2021-03-31'])
ACTIVE_WITNESS_SCOPES['P11'] = digest(DISTRIBUTION_WITNESS_SCOPES['P11'])
ACTIVE_WITNESS_SCOPES['P03'] = digest(EXTRA_WITNESS_SCOPES[('P03', '2019-09-30-CBLK-MDCO-ARQL')])
ACTIVE_WITNESS_SCOPES['P11'] = digest(EXTRA_WITNESS_SCOPES['P11', '2025-06-30'])
ACTIVE_WITNESS_SCOPES['P05'] = digest(EXTRA_WITNESS_SCOPES[('P05', '2021-10-29')])
ACTIVE_WITNESS_SCOPES['P11'] = digest(EXTRA_WITNESS_SCOPES[('P11', '2026-02-27')])
ACTIVE_WITNESS_SCOPES['P03'] = digest(EXTRA_WITNESS_SCOPES[('P03', '2019-09-30-ALDR-and-2020-originals')])
ACTIVE_WITNESS_SCOPES['P07'] = digest(EXTRA_WITNESS_SCOPES[('P07', '2022-02-28')])
ACTIVE_WITNESS_SCOPES['P06'] = digest(EXTRA_WITNESS_SCOPES['P06', '2022-04-29'])
ACTIVE_WITNESS_SCOPES['P11'] = digest(EXTRA_WITNESS_SCOPES[('P11', '2026-04-30')])
ACTIVE_WITNESS_SCOPES['P05'] = digest(EXTRA_WITNESS_SCOPES[('P05', '2021-11-30')])
ACTIVE_WITNESS_SCOPES['P06'] = digest(EXTRA_WITNESS_SCOPES[('P06', '2022-11-30')])
ACTIVE_WITNESS_SCOPES['P03'] = digest(EXTRA_WITNESS_SCOPES[('P03', '2019-10-31')])
ACTIVE_WITNESS_SCOPES['P05'] = digest(EXTRA_WITNESS_SCOPES[('P05', '2021-11-30-seven-next-cash-natives')])
ACTIVE_WITNESS_SCOPES['P06'] = digest(EXTRA_WITNESS_SCOPES[('P06', '2022-11-30-remaining-original-cash-natives')])
ACTIVE_WITNESS_SCOPES['P05'] = digest(EXTRA_WITNESS_SCOPES[('P05', '2022-03-31-remaining-original-cash-natives')])
ACTIVE_WITNESS_SCOPES['P03'] = digest(EXTRA_WITNESS_SCOPES[('P03', '2019-10-31-remaining-original-cash-natives')])
ACTIVE_WITNESS_SCOPES['P07'] = digest(EXTRA_WITNESS_SCOPES[('P07', '2022-09-30-remaining-original-cash-natives')])
ACTIVE_WITNESS_SCOPES['P07'] = digest(EXTRA_WITNESS_SCOPES[('P07', '2022-09-30-trq-normalization-source')])
WITNESS_SCOPES = {arm: deepcopy(WITNESS_SCOPE_REGISTRY[key]) for arm, key in ACTIVE_WITNESS_SCOPES.items()}


def registered_scope(key):
    scope = WITNESS_SCOPE_REGISTRY.get(key)
    need(scope is not None and digest(scope) == key, 'SOURCE_WITNESS_EXACT_REGISTERED_SCOPE_DIGEST')
    return deepcopy(scope)


def resolved_query_scope(scope, natives):
    if 'native_preimage_query' not in scope:
        return deepcopy(scope)
    NativePreimageQuery.model_validate(scope['native_preimage_query'])
    terms = scope['terms']
    need(len(terms) == len(natives) == 1 and not scope.get('additional_rows')
         and type(scope['native_preimage_query']['maximum_terms']) is int
         and scope['native_preimage_query']['financial_use_authorized'] is False
         and 'pending_at_parent' not in terms[0]
         and terms[0]['native_term_sha256'] is None
         and scope['parent_cursor'] < terms[0]['native_session']
         and terms[0]['session'] < terms[0]['native_session'],
         'SOURCE_DISCOVERY_ONLY_ONE_EXPLICIT_UNCONSUMED_NATIVE_QUERY')
    term, native = terms[0], natives[0]
    fields = {'session', 'security_id', 'kind', 'reference', 'cash_per_share',
              'delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
              'exchange_ratio', 'cash_in_lieu_price_per_delivered_share', 'entitlement_aggregation'}
    need(set(native) == fields and native['session'] == term['native_session']
         and native['security_id'] == term['security_id'] and native['kind'] == 'CASH_MERGER'
         and type(native['reference']) is str and bool(native['reference'])
         and native['entitlement_aggregation'] == 'HOLDER'
         and all(native[k] is None for k in ('cash_per_share', 'delivered_security_id',
              'delivered_ticker', 'delivered_issuer_id', 'exchange_ratio',
              'cash_in_lieu_price_per_delivered_share')),
         'SOURCE_DISCOVERY_EXACT_FROZEN_INCOMPLETE_CASH_NATIVE_SHAPE')
    result = deepcopy(scope)
    del result['native_preimage_query']
    result['terms'][0]['native_term_sha256'] = digest(native)
    return result


def source_terms(scope, natives, rows, positions, pending_contexts=None):
    """Validate only declared source preimages and parent-role observations."""
    from datetime import date
    declared = scope['terms']
    pending_contexts = [None] * len(declared) if pending_contexts is None else pending_contexts
    keys = {(t['session'], t['security_id']) for t in declared}
    need(declared and len(keys) == len(declared) == len(rows) == len(positions) == len(natives) == len(pending_contexts),
         'SOURCE_WITNESS_EXACT_UNIQUE_DECLARED_COUNTS')
    need({(r['session'], r['security_id']) for r in rows} == keys,
         'SOURCE_WITNESS_NO_MISSING_DUPLICATE_OR_EXTRA_ROWS')
    result = []
    for term, native, held, pending in zip(declared, natives, positions, pending_contexts):
        sid = term['security_id']
        row, = [r for r in rows if (r['session'], r['security_id']) == (term['session'], sid)]
        future = scope['parent_cursor'] < term['native_session']
        if future:
            need(pending is None and 'pending_at_parent' not in term, 'SOURCE_WITNESS_FUTURE_NATIVE_UNCONSUMED_SCOPE')
        else:
            need(term['native_session'] == scope['parent_cursor'] and held
                 and pending == term.get('pending_at_parent') and pending is not None
                 and type(pending['pending_sessions']) is int and pending['pending_sessions'] == 0
                 and type(pending['stale_at_event']) is int and pending['stale_at_event'] == 0
                 and pending['unresolved'] is False and pending['native_term_sha256'] == term['native_term_sha256'],
                 'SOURCE_WITNESS_ONLY_EXACT_OWN_PENDING_NATIVE_AT_PARENT')
        need(term['session'] < term['native_session']
             and date.fromisoformat(row['listing_first_session']) <= date.fromisoformat(row['session'])
             and row['ticker'] == term['ticker'] and row['security_type_eligible'] in ('0', '1')
             and type(row['issuer_id']) is str, 'SOURCE_WITNESS_EXACT_UNMODIFIED_IDENTITY')
        need(native['session'] == term['native_session'] and native['security_id'] == sid
             and native['kind'] == 'CASH_MERGER' and native['cash_per_share'] is None
             and digest(native) == term['native_term_sha256'], 'SOURCE_WITNESS_EXACT_INCOMPLETE_NATIVE')
        need(held == term['parent_positions'], 'SOURCE_WITNESS_EXACT_PARENT_POSITION_SCOPE')
        witness = {k: row[k] for k in ('session', 'security_id', 'ticker', 'issuer_id',
                                       'listing_first_session', 'security_type_eligible')}
        witness['source_observation_sha256'] = digest(row)
        result.append(dict(source_row=deepcopy(row), identity_witness=witness,
                           native_term=deepcopy(native), parent_positions=deepcopy(held)))
        if pending is not None:
            result[-1]['pending_context'] = deepcopy(pending)
    return result


def source_schema(scope):
    if scope.get('schema') == 'research.distribution-only-source-scope/1':
        return 'research.own-parent-frozen-source-witnesses/7'
    if 'native_distribution_queries' in scope:
        return 'research.own-parent-frozen-source-witnesses/6'
    if 'native_date_query' in scope:
        return SOURCE_WITNESS_DATE_QUERY_SCHEMA
    if 'additional_row_queries' in scope:
        return SOURCE_WITNESS_ROW_QUERY_SCHEMA
    if 'native_preimage_query' in scope:
        return SOURCE_WITNESS_DISCOVERY_SCHEMA
    return (SOURCE_WITNESS_PENDING_SCHEMA if scope.get('additional_rows')
            or any('pending_at_parent' in t for t in scope['terms']) else SOURCE_WITNESS_SCHEMA)


def native_date_query(scope):
    from datetime import date
    query = scope['native_date_query']
    NativeDateQuery.model_validate(query)
    need(set(scope) == {'parent_outer_sha256', 'parent_cursor', 'terms', 'native_date_query'}
         and len(scope['terms']) == 1, 'SOURCE_NATIVE_DATE_ONE_DECLARED_SECURITY')
    term, = scope['terms']
    start, end = date.fromisoformat(query['session_from']), date.fromisoformat(query['session_to'])
    need(set(term) == {'ticker', 'security_id', 'session', 'parent_positions'}
         and query['security_id'] == term['security_id']
         and scope['parent_cursor'] < term['session'] < query['session_from'] <= query['session_to']
         and 0 <= (end-start).days <= 31 and type(query['maximum_records']) is int
         and ((query['schema'].endswith('/1') and 'include_outside_window' not in query)
              or (query['schema'].endswith('/2') and query.get('include_outside_window') is True))
         and query['financial_use_authorized'] is False, 'SOURCE_NATIVE_DATE_EXACT_BOUNDED_QUERY')
    return query, term


def native_date_candidates(terminal, scope):
    query, term = native_date_query(scope)
    rows = []
    for day in sorted(terminal):
        if not query.get('include_outside_window') and not query['session_from'] <= day <= query['session_to']:
            continue
        for item in terminal[day]:
            row = asdict(item) if is_dataclass(item) else deepcopy(item)
            if row['security_id'] == term['security_id']:
                rows.append(row)
    return rows


def native_date_material(scope, natives, rows, positions):
    from datetime import date
    query, term = native_date_query(scope)
    need(len(rows) == 1 and rows[0]['session'] == term['session']
         and rows[0]['security_id'] == term['security_id'] and rows[0]['ticker'] == term['ticker']
         and rows[0]['security_type_eligible'] in ('0', '1') and type(rows[0]['issuer_id']) is str
         and date.fromisoformat(rows[0]['listing_first_session']) <= date.fromisoformat(term['session'])
         and positions == term['parent_positions'], 'SOURCE_NATIVE_DATE_FULL_IDENTITY_AND_ACTUAL_ROLE')
    fields = {'session', 'security_id', 'kind', 'reference', 'cash_per_share', 'delivered_security_id',
              'delivered_ticker', 'delivered_issuer_id', 'exchange_ratio',
              'cash_in_lieu_price_per_delivered_share', 'entitlement_aggregation'}
    need(len(natives) <= query['maximum_records'] and len({digest(v) for v in natives}) == len(natives)
         and all(set(v) == fields and v['security_id'] == term['security_id']
                 and (query.get('include_outside_window') is True or query['session_from'] <= v['session'] <= query['session_to'])
                 and isinstance(v['kind'], str) and bool(v['kind']) for v in natives),
         'SOURCE_NATIVE_DATE_ALL_CANDIDATES_WITHOUT_TRUNCATION')
    candidates = sorted((dict(native_term=deepcopy(v), native_term_sha256=digest(v)) for v in natives),
                        key=lambda v: (v['native_term']['session'], v['native_term_sha256']))
    if query.get('include_outside_window'):
        for candidate in candidates:
            day = candidate['native_term']['session']
            candidate['window_relation'] = ('BEFORE_WINDOW' if day < query['session_from'] else
                'AFTER_WINDOW' if day > query['session_to'] else 'IN_WINDOW')
    witness = {k: rows[0][k] for k in ('session', 'security_id', 'ticker', 'issuer_id',
                                      'listing_first_session', 'security_type_eligible')}
    witness['source_observation_sha256'] = digest(rows[0])
    suffix = 'FROZEN_INDEX' if query.get('include_outside_window') else 'WINDOW'
    return dict(native_candidates=candidates, match_status=('NO_NATIVE_IN_'+suffix if not candidates
        else 'UNIQUE_NATIVE_CAPTURED' if len(candidates) == 1 else 'MULTIPLE_NATIVES_IN_'+suffix),
        terms=[dict(source_row=deepcopy(rows[0]), identity_witness=witness, parent_positions=deepcopy(positions))])


def native_date_payload(spec, scope, material):
    return dict(schema=SOURCE_WITNESS_DATE_QUERY_SCHEMA, arm=spec['arm'],
        parent_outer_sha256=scope['parent_outer_sha256'], parent_cursor=scope['parent_cursor'],
        archive_sha256=spec['base']['archive_sha256'], bundle_sha256=spec['base']['bundle_sha256'],
        scope=deepcopy(scope), scope_sha256=digest(scope), producer_sha256=sha(Path(__file__).read_bytes()),
        **material, financial_sessions_advanced=0, financial_authority=False, input_adopted=False,
        provider_metadata_upgraded=False, production_contacted=False)


def resolved_row_query_scope(scope, rows):
    if 'additional_row_queries' not in scope:
        return deepcopy(scope)
    queries = scope['additional_row_queries']
    need(len(queries) == len(rows) == 1 and not scope.get('additional_rows'),
         'SOURCE_OBSERVATION_QUERY_SINGLE_EXPLICIT_ROW')
    query, row = queries[0], rows[0]
    ObservationIdentityQuery.model_validate(query)
    need(type(query['maximum_rows']) is int and query['maximum_rows'] == 1
         and query['financial_use_authorized'] is False and query['require_unheld_at_parent'] is True
         and scope['parent_cursor'] < query['session'] == row['session']
         and observation_query_matches(query, row)
         and type(row['security_id']) is str and bool(row['security_id'])
         and (row['session'], row['security_id']) not in {
             (t['session'], t['security_id']) for t in scope['terms']},
         'SOURCE_OBSERVATION_QUERY_EXACT_FUTURE_IDENTITY')
    result = deepcopy(scope)
    del result['additional_row_queries']
    result['additional_rows'] = [dict(session=row['session'], security_id=row['security_id'],
        ticker=row['ticker'], source_observation_sha256=digest(row), parent_positions=[])]
    return result


def observation_query_matches(query, row):
    # Both callers validate each typed query before scanning any archive rows.
    return row['session'] == query['session'] and (
        row['ticker'] == query['ticker'] if query.get('match_mode', 'EXACT') == 'EXACT'
        else row['ticker'].startswith(query['ticker']))


def additional_source_rows(scope, rows, positions):
    from datetime import date
    declared = scope.get('additional_rows', [])
    keys = {(t['session'], t['security_id']) for t in declared}
    native_keys = {(t['session'], t['security_id']) for t in scope['terms']}
    need(len(keys) == len(declared) == len(rows) == len(positions) and not keys & native_keys
         and {(r['session'], r['security_id']) for r in rows} == keys,
         'SOURCE_WITNESS_EXACT_ADDITIONAL_IDENTITY_ROWS')
    result = []
    for term, held in zip(declared, positions):
        row, = [r for r in rows if (r['session'], r['security_id']) == (term['session'], term['security_id'])]
        need(scope['parent_cursor'] < row['session'] and row['ticker'] == term['ticker']
             and row['security_type_eligible'] in ('0', '1') and type(row['issuer_id']) is str
             and date.fromisoformat(row['listing_first_session']) <= date.fromisoformat(row['session'])
             and digest(row) == term['source_observation_sha256'] and held == term['parent_positions'],
             'SOURCE_WITNESS_UNMODIFIED_ADDITIONAL_ROW_AND_PARENT_ROLE')
        witness = {k: row[k] for k in ('session', 'security_id', 'ticker', 'issuer_id',
                                       'listing_first_session', 'security_type_eligible')}
        witness['source_observation_sha256'] = digest(row)
        result.append(dict(source_row=deepcopy(row), identity_witness=witness, parent_positions=deepcopy(held)))
    return result


def witness_payload(cp, arm, scope, natives, rows, additional_rows=()):
    need(cp['sha256'] == scope['parent_outer_sha256'] and cp['source_cursor'] == scope['parent_cursor'],
         'SOURCE_WITNESS_EXACT_OWN_PARENT')
    if source_schema(scope) == SOURCE_WITNESS_DATE_QUERY_SCHEMA:
        term, = scope['terms']
        positions = [dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
                     for _, e in sorted(cp['run']['state']['wealth_core']['episodes'].items(), key=lambda item: int(item[0]))
                     if e['security_id'] == term['security_id']]
        material = native_date_material(scope, natives, rows, positions)
        return native_date_payload(dict(arm=arm, base=cp['base']), scope, material)
    resolved = resolved_row_query_scope(resolved_query_scope(scope, natives), additional_rows)
    episodes = cp['run']['state']['wealth_core']['episodes']
    def positions(terms):
        return [[dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'],
                       entry_date=e['entry_date'])
                  for _, e in sorted(episodes.items(), key=lambda item: int(item[0]))
                  if e['security_id'] == t['security_id']] for t in terms]
    w = cp['run']['state']['wealth_core']
    pending = []
    for term in scope['terms']:
        sid = term['security_id']
        recorded = w.get('terminal_pending_terms', {}).get(sid, {})
        pending.append(dict(pending_sessions=w.get('terminal_pending_sessions', {}).get(sid),
            stale_at_event=recorded.get('stale_at_event'), native_term_sha256=digest(recorded.get('terms')),
            unresolved=sid in w.get('unresolved_terminals', {})) if 'pending_at_parent' in term else None)
    payload = dict(schema=source_schema(scope), arm=arm, parent_outer_sha256=cp['sha256'],
        parent_cursor=cp['source_cursor'], archive_sha256=cp['base']['archive_sha256'],
        bundle_sha256=cp['base']['bundle_sha256'], scope=resolved, scope_sha256=digest(resolved),
        producer_sha256=sha(Path(__file__).read_bytes()), terms=source_terms(resolved, natives, rows, positions(scope['terms']), pending),
        financial_sessions_advanced=0, financial_authority=False, input_adopted=False,
        provider_metadata_upgraded=False, production_contacted=False)
    if source_schema(scope) == SOURCE_WITNESS_DISCOVERY_SCHEMA:
        need(not additional_rows, 'SOURCE_DISCOVERY_NO_UNDECLARED_ADDITIONAL_ROWS')
        payload.update(query_scope=deepcopy(scope), query_scope_sha256=digest(scope))
    if source_schema(scope) == SOURCE_WITNESS_ROW_QUERY_SCHEMA:
        payload.update(query_scope=deepcopy(scope), query_scope_sha256=digest(scope))
    if source_schema(scope) in (SOURCE_WITNESS_PENDING_SCHEMA, SOURCE_WITNESS_ROW_QUERY_SCHEMA):
        payload['additional_rows'] = additional_source_rows(resolved, additional_rows, positions(resolved.get('additional_rows', [])))
    return payload


def validate_witness_capture(payload, spec, scope):
    if 'native_distribution_queries' in scope:
        from system_campaign_financial_distribution_source import validate
        return validate(payload, spec, scope, sha(Path(__file__).read_bytes()))
    if source_schema(scope) == SOURCE_WITNESS_DATE_QUERY_SCHEMA:
        material = native_date_material(scope, [v['native_term'] for v in payload['native_candidates']],
            [v['source_row'] for v in payload['terms']], payload['terms'][0]['parent_positions'])
        need(spec['outer_sha256'] == scope['parent_outer_sha256']
             and spec['selected_session'] == scope['parent_cursor']
             and type(payload['financial_sessions_advanced']) is int
             and all(payload[k] is False for k in ('financial_authority', 'input_adopted',
                                                   'provider_metadata_upgraded', 'production_contacted'))
             and payload == native_date_payload(spec, scope, material),
             'SOURCE_NATIVE_DATE_EXACT_SOURCE_ONLY_RECONSTRUCTION')
        return payload
    resolved = resolved_row_query_scope(resolved_query_scope(scope, [v['native_term'] for v in payload['terms']]),
                                        [v['source_row'] for v in payload.get('additional_rows', [])])
    need(payload['schema'] == source_schema(scope) and payload['arm'] == spec['arm']
         and payload['parent_outer_sha256'] == spec['outer_sha256'] == scope['parent_outer_sha256']
         and payload['parent_cursor'] == spec['selected_session'] == scope['parent_cursor']
         and payload['archive_sha256'] == spec['base']['archive_sha256']
         and payload['bundle_sha256'] == spec['base']['bundle_sha256']
         and payload['scope'] == resolved and payload['scope_sha256'] == digest(resolved)
         and payload['producer_sha256'] == sha(Path(__file__).read_bytes())
         and type(payload['financial_sessions_advanced']) is int and payload['financial_sessions_advanced'] == 0
         and all(payload[k] is False for k in ('financial_authority', 'input_adopted',
                                               'provider_metadata_upgraded', 'production_contacted')),
         'SOURCE_WITNESS_EXACT_SOURCE_ONLY_CAPTURE')
    if source_schema(scope) in (SOURCE_WITNESS_DISCOVERY_SCHEMA, SOURCE_WITNESS_ROW_QUERY_SCHEMA):
        need(digest(payload['query_scope']) == digest(scope) and payload['query_scope_sha256'] == digest(scope),
             'SOURCE_DISCOVERY_ORIGINAL_QUERY_AND_RESOLVED_SCOPE_BOUND')
    terms = payload['terms']
    need(terms == source_terms(resolved, [v['native_term'] for v in terms],
          [v['source_row'] for v in terms], [v['parent_positions'] for v in terms],
          [v.get('pending_context') for v in terms]),
          'SOURCE_WITNESS_FULL_PAYLOAD_RECONSTRUCTION')
    if source_schema(scope) in (SOURCE_WITNESS_PENDING_SCHEMA, SOURCE_WITNESS_ROW_QUERY_SCHEMA):
        rows = payload['additional_rows']
        need(rows == additional_source_rows(resolved, [v['source_row'] for v in rows],
                                           [v['parent_positions'] for v in rows]),
             'SOURCE_WITNESS_COMPLETE_ADDITIONAL_ROW_RECONSTRUCTION')
    return payload


def capture_source_witnesses(cp, out, arm, scope):
    if 'native_distribution_queries' in scope:
        from system_campaign_financial_distribution_source import capture
        return capture(cp, out, arm, scope, sha(Path(__file__).read_bytes()))
    hosted()
    from research.pooled_input_support import inputs
    before = digest(cp)
    actions = inputs.load_actions(Path('/frozen/bundle'))
    natives = []
    if source_schema(scope) == SOURCE_WITNESS_DATE_QUERY_SCHEMA:
        natives = native_date_candidates(actions.terminal, scope)
        save(out / 'native-date-query-diagnostic.json', dict(schema='research.native-date-query-diagnostic/1',
            scope_sha256=digest(scope), candidate_count=len(natives), native_records=natives,
            native_kind_types=[type(v['kind']).__name__ for v in natives], financial_authority=False,
            financial_sessions_advanced=0))
    else:
        for term in scope['terms']:
            native, = [asdict(t) for t in actions.terminal.get(term['native_session'], ())
                       if t.security_id == term['security_id']]
            natives.append(native)
    native_keys = {(t['session'], t['security_id']) for t in scope['terms']}
    additional_keys = {(t['session'], t['security_id']) for t in scope.get('additional_rows', [])}
    queries = scope.get('additional_row_queries', [])
    for query in queries:
        ObservationIdentityQuery.model_validate(query)
    query_keys = {(q['session'], q['ticker']) for q in queries}
    keys = native_keys | additional_keys
    rows = []
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for year in sorted({day[:4] for day, _ in keys | query_keys}):
            for row in inputs._archive_rows(archive, 'observations-' + year + '.csv.gz'):
                if (row['session'], row['security_id']) in keys or any(observation_query_matches(q, row) for q in queries):
                    rows.append(row)
    if queries:
        candidates = [r for r in rows if any(observation_query_matches(q, r) for q in queries)]
        save(out / 'source-witness-query-diagnostic.json', dict(
            schema='research.source-observation-query-diagnostic/1', financial_authority=False,
            query_scope_sha256=digest(scope), matched_rows=len(candidates),
            candidates=[dict(session=r['session'], ticker=r['ticker'], security_id=r['security_id'],
                             source_observation_sha256=digest(r)) for r in candidates[:10]]))
    payload = witness_payload(cp, arm, scope, natives,
        [r for r in rows if (r['session'], r['security_id']) in native_keys],
        [r for r in rows if (r['session'], r['security_id']) in additional_keys
         or any(observation_query_matches(q, r) for q in queries)])
    need(digest(cp) == before, 'SOURCE_WITNESS_PARENT_STATE_UNCHANGED')
    save(out / SOURCE_WITNESS_FILE, payload)
    return payload


def selected_query_scope(term, query):
    """Reconstruct query resolution from captured identities; private rows stay private."""
    resolved = resolved_query_scope(query, [term['native']])
    if 'additional_row_queries' not in query:
        return resolved
    queries = query['additional_row_queries']
    need(len(queries) == 1 and not resolved.get('additional_rows'),
         'OWN_INPUT_ONE_CAPTURED_DELIVERY_QUERY')
    q, witness = queries[0], term['delivered_identity_witness']
    ObservationIdentityQuery.model_validate(q)
    need(type(q['maximum_rows']) is int and q['maximum_rows'] == 1
         and q['require_unheld_at_parent'] is True and q['financial_use_authorized'] is False
         and observation_query_matches(q, witness) and query['parent_cursor'] < witness['session']
         and witness['source_observation_sha256'] == term['proxy']['source_observation_sha256']
         and len(witness['source_observation_sha256']) == 64
         and all(c in '0123456789abcdef' for c in witness['source_observation_sha256']),
         'OWN_INPUT_CAPTURED_DELIVERY_QUERY_IDENTITY_AND_ROW_DIGEST')
    del resolved['additional_row_queries']
    resolved['additional_rows'] = [dict(session=witness['session'], security_id=witness['security_id'],
        ticker=witness['ticker'], source_observation_sha256=witness['source_observation_sha256'], parent_positions=[])]
    return resolved


def qualify_selected_query_resolution(term, query, scope):
    """Bind either captured discovery or exact known-native delivery query."""
    if 'native_preimage_query' not in query:
        need(set(query) == {'parent_outer_sha256', 'parent_cursor', 'terms', 'additional_row_queries'}
             and len(query['terms']) == 1,
             'OWN_INPUT_KNOWN_NATIVE_SINGLE_DELIVERY_QUERY_SCOPE')
        declared, = query['terms']
        need(set(declared) == {'ticker', 'security_id', 'session', 'native_session',
                              'native_term_sha256', 'parent_positions'}
             and query['parent_outer_sha256'] == term['parent_outer_sha256']
             and query['parent_cursor'] == term['parent_cursor']
             and declared == dict(ticker=term['ticker'], security_id=term['security_id'],
                 session=term['identity_witness']['session'], native_session=term['native_session'],
                 native_term_sha256=term['native_term_sha256'], parent_positions=term['parent_positions'])
             and declared['native_term_sha256'] == digest(term['native'])
             and term['native']['session'] == declared['native_session']
             and term['native']['security_id'] == declared['security_id']
             and query['parent_cursor'] < declared['session'] < declared['native_session'],
             'OWN_INPUT_KNOWN_NATIVE_EXACT_PREIMAGE_PARENT_AND_UNCONSUMED_SCOPE')
    need(digest(selected_query_scope(term, query)) == digest(scope),
         'OWN_CASH_EXACT_QUERY_RESOLUTION_NATIVE_PREIMAGE')

# Qualified own1090 source279: original date/amount/identity contracts remain exact.
CLOSED_CASH_GENERATIONS['5951b1ffa420910291a756b31b0a9a324ace68f4af77c854a9cc71a71b3115a5'] = 30
OWN_CASH_PHASES[('P06', '2022-04-29')] = 'XENT'
CASH_GENERATION_LENGTHS[('P06', '2022-04-29')] = 31
OWN_CASH_SOURCE_CLOCKS[('P06', '2022-04-29')] = (42006075396, '7c9f35d4a7a39f02fef82269466f5064780742f8', 13404817664)
SUPPLEMENTAL_PHASES[('P06', '2022-04-29')] = (('system_campaign_cash_calendar', 'CashCalendar', 'JSON', 'system-campaign-december-cash-calendar-terminal-facts.json', 'f7f5111041a7b22a6a9d0e2b627dc2b9e077fc0198ae0c3804061c2dcad3f6a6', '183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f', ('EPAY', 'CCXI1')), ('system_campaign_cash_calendar', 'CashCalendar', 'JSON', 'system-campaign-cash-calendar-terminal-facts.json', 'd296a00cecaa3ad807543f36186131c0ac2f7bf22c8a08a7aa30590f627e23f6', '183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f', ('MIME', 'CYBE')), ('system_campaign_cash_calendar', 'CashCalendar', 'JSON', 'system-campaign-october-cash-calendar-terminal-facts.json', '225b294cefd80c19b47090c24b246ac63456f6829dfe7816b41dfcdcfef2ad53', '183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f', ('AVLR', 'FMTX', 'PING', 'Y', 'ZEN')))
SUPPLEMENTAL_SAME_DAY_PHASES = SUPPLEMENTAL_SAME_DAY_PHASES | frozenset({('P06', '2022-04-29')})
SUPPLEMENTAL_SHARED_VALIDATOR_PHASES = frozenset({('P06', '2022-04-29')})


CASH_PHASES['P07', '2022-02-28'] = ('system-campaign-cash-calendar-terminal-facts.json', ('MIME', 'CYBE'))
SUPPLEMENTAL_PHASES['P07', '2022-02-28'] = (('system_campaign_cash_calendar', 'CashCalendar', 'JSON', 'system-campaign-october-cash-calendar-terminal-facts.json', '225b294cefd80c19b47090c24b246ac63456f6829dfe7816b41dfcdcfef2ad53', '183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f', ('AVLR', 'FMTX', 'PING', 'Y', 'ZEN')),)
ADDITIONAL_SENSOR_ALIAS_PHASES = frozenset({('P07', '2022-02-28')})
ROOT_BOUND_ALIAS_SOURCE_PHASES['P07', '2022-02-28'] = ('532e1e4ca1317d3631235cb0316860112a355ab1b4cf4f61704f5583245540fd', 'd4845ce85600d202fe99e3a67bc7241c14c93279edd51992fea0db0b5a19b058', 1047)



CLOSED_CASH_GENERATIONS['3640674e7049db653200c8c888e70fe9f645b6dfba7110b49295a0645f318304'] = 32
OWN_CASH_PHASES['P05', '2021-11-30'] = 'MDP'
CASH_GENERATION_LENGTHS['P05', '2021-11-30'] = 33
OWN_CASH_SOURCE_CLOCKS['P05', '2021-11-30'] = (42027761123, 'c0c96766d93b3f80afc2b2e9a88ecfc2b7d3573a', 13414936647)

CLOSED_CASH_GENERATIONS['9b2e32b0dddd53919f846b4b275ccd04afb59ab257b2652e5b63892971012fd9'] = 33
OWN_CASH_PHASES['P06', '2022-11-30'] = 'TRQ'
CASH_GENERATION_LENGTHS['P06', '2022-11-30'] = 34
OWN_CASH_SOURCE_CLOCKS['P06', '2022-11-30'] = (42031700046, '170b22c393322f048c76e44d67dd40857a8dc8a1', 13417195161)

SUPPLEMENTAL_PHASES['P05', '2021-11-30'] = (
    ('system_campaign_qualified_cash_batch', 'QualifiedCashBatch', 'JSON',
     'system-campaign-p05-seven-cash-inputs.json',
     '614ef0d349ae6ba82369ee7ecaa751f210023dbf2c16da60ee1d1915e9cf8681',
     '96c9763e021c72c784b04c7033dd32940b9809cff6b56ba0e394287e0cdd3f36',
     ('CXP', 'HRC', 'MGLN', 'PAE', 'RRD', 'MCFE', 'NUAN')),
)

FUTURE_LITERAL_PHASES['P05', '2022-03-31'] = ('system_campaign_qualified_cash_subset', 'QualifiedCashSubset', 'system-campaign-p05-own1070-supported-cash-inputs.json', ('HMHC', 'ANAT'))
SUPPLEMENTAL_PHASES['P05', '2022-03-31'] = (('system_campaign_qualified_cash_subset', 'QualifiedCashSubset', 'PATH', 'system-campaign-p05-own1070-supported-cash-inputs.json', '0215ae4293365f6327dfd38dce0493b05b67cb7cb400ff494876d835df61fb77', 'e0f7f8599032d6927a9fb84f156bcb60c8c0162b7abd37a47db5bdd1a7ae7ea2', ('XENT', 'MIME', 'TVTY', 'SAFM', 'GBT', 'FMTX', 'PING', 'AVLR', 'Y', 'ZEN', 'SJI', 'LHCG', 'ONEM', 'COUP', 'EVOP', 'SGFY', 'PRVB', 'OSH', 'MAXR', 'SUMO', 'TA', 'MGI', 'HSKA', 'RUTH')),)
SUPPLEMENTAL_SAME_DAY_PHASES = SUPPLEMENTAL_SAME_DAY_PHASES | frozenset({('P05', '2022-03-31')})


FUTURE_LITERAL_PHASES['P05', '2022-05-31'] = ('system_campaign_qualified_explicit_cash', 'QualifiedExplicitCash', 'system-campaign-p05-own1111-msp-explicit-cash-input-v3.json', ('MSP',))


def own_cash_selection(arm, cursor):
    from system_campaign_cash_calendar import validate_term
    import system_campaign_cash_calendar as calendar
    from system_campaign_financial_partial import root_spec
    raw = (HERE / OWN_CASH_CATALOG).read_bytes()
    need(sha(raw) == OWN_CASH_SHA, 'OWN_CASH_EXACT_REVIEWED_LITERAL_CATALOG')
    catalog = json.loads(raw)
    need(catalog['schema'] == 'research.selected-own-parent-completions/2'
         and all(catalog[k] is False for k in ('canonical_financial_source_changed',
                                              'provider_metadata_upgraded', 'production_contacted'))
         and len(catalog['terms']) == len(OWN_CASH_PHASES), 'OWN_CASH_EXACT_NEW_CATALOG_SCOPE')
    def generation(count):
        value = dict(deepcopy(catalog), terms=deepcopy(catalog['terms'][:count]))
        if count in (2, 3):
            value['schema'] = 'research.selected-own-parent-cash-completions/1'
        encoded = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
        return value, sha(encoded)
    for old_sha, count in CLOSED_CASH_GENERATIONS.items():
        need(generation(count)[1] == old_sha, 'OWN_CASH_CLOSED_CATALOG_GENERATION_BYTES')
    for term in catalog['terms']:
        if term['recognition_rule'] == RESEARCH_UNHELD_COMPOSITE:
            research_original_unheld_composite_term(term)
        elif term['recognition_rule'] == RESEARCH_MIXED:
            research_mixed_term(term)
        elif term['recognition_rule'] == RESEARCH_SOURCE_EXIT:
            research_source_exit_term(term)
        elif term['recognition_rule'] == RESEARCH_TENDER:
            research_tender_term(term)
        elif term['recognition_rule'] == RESEARCH_CASH:
            research_cash_term(term)
        elif term['recognition_rule'] == RESEARCH_UNHELD_CASH:
            research_unheld_cash_term(term)
        elif term['recognition_rule'] == SOURCE_CLOSE:
            source_cash_term(term)
        elif term['recognition_rule'] == NEXT_COMPLETION:
            completion_cash_term(term)
        elif term['added']['kind'] == 'CASH_MERGER':
            validate_term(term)
        else:
            selected_stock_term(term)
        phase = term['arm'], term['parent_cursor']
        source = term['source_capture']
        parent = root_spec(term['arm'], term['parent_root_admission_sha256'])
        scope = registered_scope(source['scope_sha256'])
        if len(scope['terms']) == 1:
            declared, = scope['terms']
        else:
            need(len({t['security_id'] for t in scope['terms']}) == len(scope['terms'])
                 and len({(t['native_session'], t['security_id']) for t in scope['terms']}) == len(scope['terms']),
                 'OWN_CASH_UNIQUE_MULTI_SOURCE_SECURITY_AND_NATIVE_KEYS')
            matches = [t for t in scope['terms'] if t['security_id'] == term['security_id']]
            need(len(matches) == 1, 'OWN_CASH_EXACT_SELECTED_MEMBER_OF_MULTI_SOURCE_SCOPE')
            declared, = matches
        if 'query_scope_sha256' in source:
            query = registered_scope(source['query_scope_sha256'])
            qualify_selected_query_resolution(term, query, scope)
        retained_primary(term)
        need(OWN_CASH_PHASES.get(phase) == term['ticker']
             and term['parent_outer_sha256'] == scope['parent_outer_sha256']
             and term['parent_outer_sha256'] == parent['outer_sha256']
             and term['parent_cursor'] == parent['selected_session']
             and term['parent_positions'] == declared['parent_positions']
             and term['identity_witness']['session'] == declared['session']
             and term['native_session'] == declared['native_session']
             and term['native_term_sha256'] == declared['native_term_sha256']
             and term['security_id'] == declared['security_id']
             and (source['run_id'], source['head'], source['artifact_id']) == OWN_CASH_SOURCE_CLOCKS.get(phase)
             and source['scope_sha256'] == digest(scope)
             and all(type(source[k]) is str and len(source[k]) == 64
                     and all(c in '0123456789abcdef' for c in source[k])
                     for k in ('payload_sha256', 'independent_data_review_sha256')),
             'OWN_CASH_EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE')
    chosen, = [t for t in catalog['terms'] if (t['arm'], t['parent_cursor']) == (arm, cursor)]
    need(len({(t['arm'], t['parent_cursor']) for t in catalog['terms']}) == len(catalog['terms']),
         'OWN_CASH_UNIQUE_DECLARED_PHASES')
    selected_catalog, selected_sha = generation(CASH_GENERATION_LENGTHS[arm, cursor])
    need(chosen in selected_catalog['terms'], 'OWN_CASH_EXACT_PHASE_CATALOG_GENERATION')
    codec = SimpleNamespace(catalog=selected_catalog, catalog_sha=selected_sha,
        compiler_sha=sha(Path(calendar.__file__).read_bytes()),
        parent_outer_sha256=chosen['parent_outer_sha256'], parent_positions=chosen['parent_positions'],
        validator_description='Unchanged cash-calendar term validator; new own-source catalog validated by the shared selector.')
    if chosen['recognition_rule'] == RESEARCH_MIXED:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Published cash precision declared by the versioned assumption and literal stock ratio with explicit daily research opening availability and frozen raw-open fractional proxy; actual settlement is not claimed.'
        return codec, OWN_CASH_CATALOG, [research_mixed_term(chosen)]
    if chosen['added']['kind'] != 'CASH_MERGER':
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Source-bound selected stock term; raw ratio preserved in catalog and exactly normalized for the canonical typed parser.'
        return codec, OWN_CASH_CATALOG, [selected_stock_term(chosen)]
    if chosen['recognition_rule'] == RESEARCH_SOURCE_EXIT:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Retained raw-close controller source exit only; actual portfolio no-op and never-held history are required. No statutory cash, held settlement or execution-price claim.'
    elif chosen['recognition_rule'] == RESEARCH_TENDER:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Published listed-unit cash with explicit modeled tender participation and opening recognition after the offer deadline; actual settlement and mandatory conversion are not claimed.'
    elif chosen['recognition_rule'] == RESEARCH_CASH:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        if chosen['research_assumption'].get('schema') == 'research.daily-normalized-usd-cash-assumption/1':
            codec.validator_description = 'Research CAD-to-USD cash normalization with exact raw consideration/prior-day rate/Decimal-to-float binding, actual dynamic own quantity, and UNVERIFIED historical FX availability; no actual USD payment or settlement claim.'
        else:
            codec.validator_description = 'Published cash consideration with explicit research opening availability on the completion calendar date; actual settlement and preopen completion are not claimed.'
    elif chosen['recognition_rule'] == NEXT_COMPLETION:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Shared source-bound mandatory cash right with explicit first-session-after-confirmed-completion timing convention.'
    elif chosen['recognition_rule'] == RESEARCH_UNHELD_COMPOSITE:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Exact original ordered composite source marker on its native research calendar day; actual never-held no-op and original source delegation only, without held/preopen/PIT authority.'
    elif chosen['recognition_rule'] == RESEARCH_UNHELD_CASH:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Original unheld-source cash amount with explicit research closing availability, no confirmed-by-close or held-completion claim; actual canonical absence, no-op and source delegation are mandatory.'
    elif chosen['recognition_rule'] == SOURCE_CLOSE:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Shared closing source valuation; actual unowned/unordered and canonical no-op proofs are mandatory, with no portfolio completion authority.'
    return codec, OWN_CASH_CATALOG, [deepcopy(chosen)]


def retained_own_cash_selection(arm, cursor):
    """Reuse qualified ordinary cash facts while binding a separate own book."""
    from system_campaign_cash_calendar import NEXT, PREOPEN, validate_term
    from system_campaign_financial_partial import root_spec
    plan = RETAINED_OWN_CASH_PHASES[arm, cursor]
    original_codec, catalog, originals = own_cash_selection(plan['source_arm'], plan['source_cursor'])
    need(len(originals) == 1 and original_codec.catalog_sha == plan['source_generation_sha256'],
         'RETAINED_CASH_EXACT_CLOSED_SOURCE_GENERATION')
    original, = originals
    old = root_spec(plan['source_arm'], original['parent_root_admission_sha256'])
    current = root_spec(arm, plan['parent_root_admission_sha256'])
    need(arm != plan['source_arm'] and current['selected_session'] == cursor
         and current['outer_sha256'] == plan['parent_outer_sha256']
         and all(old['base'][k] == current['base'][k] for k in ('archive_sha256', 'bundle_sha256')),
         'RETAINED_CASH_EXACT_OWN_PARENT_AND_FROZEN_HISTORY')
    need(original['ticker'] == plan['ticker'] and original['added']['kind'] == 'CASH_MERGER'
         and original['recognition_rule'] in (NEXT, PREOPEN)
         and original['native_session'] > cursor and original['added']['session'] > cursor
         and original['mandatory_common_share_completion_confirmed'] is True,
         'RETAINED_CASH_ORDINARY_MANDATORY_FUTURE_FACTS_ONLY')
    validate_term(original)
    book_fields = {'arm', 'parent_cursor', 'parent_outer_sha256', 'parent_root_admission_sha256', 'parent_positions'}
    term = {k: deepcopy(v) for k, v in original.items() if k not in book_fields}
    term['retained_qualified_source'] = dict(source_arm=plan['source_arm'], source_cursor=plan['source_cursor'],
        source_parent_admission_sha256=original['parent_root_admission_sha256'],
        source_term_sha256=digest(original), source_catalog_generation_sha256=original_codec.catalog_sha)
    codec = SimpleNamespace(catalog=deepcopy(original_codec.catalog), catalog_sha=original_codec.catalog_sha,
        compiler_sha=sha(Path(__file__).read_bytes()), parent_outer_sha256=current['outer_sha256'],
        parent_positions=deepcopy(plan['parent_positions']),
        validator_description='Retained qualified ordinary cash facts only; originating book fields removed. Exact own admitted parent and positions, frozen native and full source row must be reverified.')
    return codec, catalog, [term]


def research_source_exit_term(term):
    model = ResearchSourceExitAssumption.model_validate(term['research_assumption'])
    a, w, quote = term['added'], term['identity_witness'], term['retained_quote']
    need(term['recognition_rule'] == RESEARCH_SOURCE_EXIT
         and term['preopen_completion_confirmed'] is term['mandatory_common_share_completion_confirmed'] is False
         and term['portfolio_completion_authorized'] is False and term['require_unowned_and_unordered'] is True
         and term['parent_positions'] == [] and term['source_valuation_phase'] == 'CLOSE'
         and term['parent_cursor'] < w['session'] == model.retained_quote_session
             < model.recognition_session == a['session'] == term['native_session']
         and a['kind'] == 'CASH_MERGER' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and Fraction(str(a['cash_per_share'])) == Fraction(model.retained_raw_close)
         and quote == dict(security_id=term['security_id'], ticker=term['ticker'],
                           session=model.retained_quote_session, raw_close=a['cash_per_share'])
         and digest(quote) == model.retained_quote_sha256
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and a['entitlement_aggregation'] == 'HOLDER'
         and all(a[k] is None for k in ('delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
                                        'exchange_ratio', 'cash_in_lieu_price_per_delivered_share'))
         and a['reference'] == 'MODEL_UNHELD_SOURCE_EXIT_LAST_RETAINED_RAW_CLOSE:' + model.retained_quote_sha256,
         'OWN_INPUT_EXPLICIT_UNHELD_SOURCE_EXIT_NO_SETTLEMENT')


def source_exit_quote(term, row):
    quote = dict(security_id=row['security_id'], ticker=row['ticker'], session=row['session'],
                 raw_close=float(row['raw_close']))
    need(quote == term['retained_quote']
         and digest(quote) == term['research_assumption']['retained_quote_sha256'],
         'OWN_INPUT_SOURCE_EXIT_EXACT_FROZEN_RAW_QUOTE')


def research_tender_term(term):
    model = ResearchTenderAssumption.model_validate(term['research_assumption'])
    a, w = term['added'], term['identity_witness']
    need(term['recognition_rule'] == RESEARCH_TENDER
         and term['preopen_completion_confirmed'] is term['mandatory_common_share_completion_confirmed'] is False
         and term['parent_cursor'] == w['session'] == model.offer_deadline_session
         and model.offer_deadline_session < model.recognition_session == a['session'] < term['native_session']
         and a['kind'] == 'CASH_MERGER' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and Fraction(str(a['cash_per_share'])) == Fraction(model.published_cash_per_source_unit)
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and a['entitlement_aggregation'] == 'HOLDER'
         and all(a[k] is None for k in ('delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
                                        'exchange_ratio', 'cash_in_lieu_price_per_delivered_share'))
         and a['reference'] == term['primary_source'] + ' | ' + term['description'],
         'OWN_INPUT_EXPLICIT_ASSUMED_TENDER_AND_PUBLISHED_CASH')


def research_normalized_usd_cash_term(term):
    """Reuse the cash input family with an exact, disclosed CAD/USD derivation."""
    from decimal import Decimal, localcontext
    from datetime import date
    model = ResearchNormalizedUSDCashAssumption.model_validate(term['research_assumption'])
    raw_model = term['research_assumption']
    need(raw_model['opening_availability_assumed'] is True
         and all(raw_model[k] is False for k in ('actual_usd_payment_claimed', 'actual_settlement_claimed', 'fx_publication_before_open_proven'))
         and type(raw_model['decimal_precision']) is int and raw_model['decimal_precision'] == 50,
         'OWN_INPUT_NORMALIZED_USD_EXACT_RESEARCH_SCOPE_FLAGS')
    a, w, primary = term['added'], term['identity_witness'], term['primary_extraction']
    encoded = (json.dumps(primary, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    fx = primary['corporate_valuation_fx_footnote']
    sources = {v['url'] for v in primary['primary_sources']}
    fx_sources = [v for v in primary['primary_sources'] if v['url'] == model.exchange_rate_source]
    need(sha(encoded) == term['primary_extraction_sha256'] == model.primary_extraction_sha256
         and primary['mandatory_ordinary_common_share_consideration'] == dict(amount=model.raw_cash_per_share, currency=model.raw_cash_currency)
         and fx['quoted_pair'] == 'USD/CAD' and fx['quoted_rate'] == model.exchange_rate
         and fx['as_of'] == model.exchange_rate_as_of_session
         and len(fx_sources) == 1 and digest(fx_sources[0]) == model.exchange_rate_source_record_sha256
         and term['primary_source'] in sources and term['timing_source'] in sources
         and primary['actual_completion_date'] == term['actual_completion_date'] == model.recognition_session
         and primary['security_id'] == term['security_id'] and primary['ticker'] == term['ticker']
         and primary['preopen_completion_confirmed'] is True
         and primary['actual_opening_cash_availability_proved'] is False
         and fx['selected_as_holder_conversion_rate'] is False,
         'OWN_INPUT_NORMALIZED_USD_EXACT_RAW_PRIMARY_AND_FX_QUOTE')
    raw, rate = Decimal(model.raw_cash_per_share), Decimal(model.exchange_rate)
    need(raw.is_finite() and rate.is_finite() and raw > 0 and rate > 0,
         'OWN_INPUT_NORMALIZED_USD_POSITIVE_FINITE_RAW_AND_RATE')
    need(date.fromisoformat(model.exchange_rate_as_of_session).isoformat() == model.exchange_rate_as_of_session
         and date.fromisoformat(model.recognition_session).isoformat() == model.recognition_session
         and model.exchange_rate_as_of_session <= term['native_session'] < model.recognition_session,
         'OWN_INPUT_NORMALIZED_USD_PRIOR_RATE_DATE')
    with localcontext() as context:
        context.prec = model.decimal_precision
        normalized = raw / rate
    need(str(normalized) == model.normalized_usd_decimal,
         'OWN_INPUT_NORMALIZED_USD_EXACT_DECIMAL_DIVISION')
    value = float(normalized)
    need(type(a['cash_per_share']) is float and math.isfinite(value) and value > 0
         and a['cash_per_share'].hex() == value.hex() == model.canonical_usd_float_hex
         and str(value) == model.canonical_usd_float_decimal,
         'OWN_INPUT_NORMALIZED_USD_EXACT_CANONICAL_FLOAT_REPRESENTATION')
    need(term['recognition_rule'] == RESEARCH_CASH and term['preopen_completion_confirmed'] is True
         and term['mandatory_common_share_completion_confirmed'] is True
         and a['kind'] == 'CASH_MERGER' and a['session'] == model.recognition_session
         and term['parent_cursor'] < w['session'] < term['native_session'] == term['last_trading_session'] < a['session']
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and a['entitlement_aggregation'] == 'HOLDER'
         and all(a[k] is None for k in ('delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
                                        'exchange_ratio', 'cash_in_lieu_price_per_delivered_share'))
         and a['reference'] == term['primary_source'] + ' | ' + term['description'],
         'OWN_INPUT_NORMALIZED_USD_EXACT_RESEARCH_CASH_AND_SOURCE_IDENTITY')


def research_cash_term(term):
    if term['research_assumption'].get('schema') == 'research.daily-normalized-usd-cash-assumption/1':
        return research_normalized_usd_cash_term(term)
    model = ResearchCashAssumption.model_validate(term['research_assumption'])
    a, w = term['added'], term['identity_witness']
    need(term['recognition_rule'] == RESEARCH_CASH
         and term['preopen_completion_confirmed'] is False
         and term['mandatory_common_share_completion_confirmed'] is True
         and a['kind'] == 'CASH_MERGER' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and Fraction(str(a['cash_per_share'])) == Fraction(model.published_cash_per_share)
         and a['session'] == model.recognition_session == term['actual_completion_date']
         and w['session'] < term['native_session'] == term['last_trading_session'] < a['session']
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and a['entitlement_aggregation'] == 'HOLDER'
         and all(a[k] is None for k in ('delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
                                        'exchange_ratio', 'cash_in_lieu_price_per_delivered_share'))
         and a['reference'] == term['primary_source'] + ' | ' + term['description'],
         'OWN_INPUT_EXPLICIT_RESEARCH_CASH_AMOUNT_AND_DAILY_RECOGNITION')


def research_after_close_mixed_timing(term, model):
    """Qualify legal post-close timing without moving the legal completion date."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    effective = datetime.fromisoformat(model.legal_effective_local)
    local = effective.astimezone(ZoneInfo(model.legal_effective_timezone))
    need(effective.isoformat() == local.isoformat() == model.legal_effective_local
         and local.date().isoformat() == term['actual_completion_date']
             == term['native_session'] == term['last_trading_session']
         and (local.hour, local.minute, local.second) > (16, 0, 0)
         and model.completed_after_close_confirmed is True
         and model.recognition_session == term['added']['session'] > term['actual_completion_date'],
         'OWN_INPUT_MIXED_CONFIRMED_POSTCLOSE_LEGAL_TIME_AND_DISTINCT_RECOGNITION')
    return model.recognition_session


def research_mixed_term(term):
    assumption = term['research_assumption']
    model_class = (ResearchAfterCloseMixedAssumption
                   if assumption.get('schema') == 'research.daily-mixed-consideration-assumption/3' else
                   (ResearchExactCashMixedAssumption
                    if assumption.get('schema') == 'research.daily-mixed-consideration-assumption/2'
                    else ResearchMixedAssumption))
    model = model_class.model_validate(assumption)
    recognition = (research_after_close_mixed_timing(term, model)
                   if isinstance(model, ResearchAfterCloseMixedAssumption) else term['actual_completion_date'])
    a, w, dw, proxy = term['added'], term['identity_witness'], term['delivered_identity_witness'], term['proxy']
    ratio = a['exchange_ratio']
    value = float(ratio)
    need(term['recognition_rule'] == RESEARCH_MIXED
         and type(assumption['published_cash_is_approximate']) is bool
         and model.opening_availability_assumed is True
         and model.actual_settlement_claimed is False
         and term['preopen_completion_confirmed'] is False
         and term['mandatory_common_share_completion_confirmed'] is True
         and a['kind'] == 'CASH_PLUS_STOCK' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and Fraction(str(a['cash_per_share'])) == Fraction(model.published_cash_per_share)
         and type(ratio) is str and math.isfinite(value) and value > 0
         and Fraction(str(value)) == Fraction(ratio) == Fraction(model.published_exchange_ratio)
         and a['session'] == model.recognition_session == recognition
         and term['parent_cursor'] < w['session'] < term['native_session'] == term['last_trading_session'] < a['session']
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and a['entitlement_aggregation'] == 'HOLDER' and a['cash_in_lieu_price_per_delivered_share'] is None
         and (a['delivered_security_id'], a['delivered_ticker'], a['delivered_issuer_id'])
             == (dw['security_id'], dw['ticker'], dw['issuer_id'])
         and dw['security_id'] == proxy['security_id']
         and dw['session'] == proxy['session'] == a['session']
         and dw['source_observation_sha256'] == proxy['source_observation_sha256']
         and dw['ticker'] == proxy['ticker']
         and proxy['convention'] == 'RETAINED_CHILD_RAW_OPEN_RESEARCH_PROXY'
         and proxy['actual_settlement_rate_observed'] is False
         and a['reference'] == term['primary_source'] + ' | ' + term['description'],
         'OWN_INPUT_EXPLICIT_RESEARCH_MIXED_AMOUNT_RATIO_IDENTITY_AND_TIMING')
    result = deepcopy(term)
    result['added']['exchange_ratio'] = value
    return result


def research_unheld_cash_term(term):
    """Validate one original source-only amount without inventing a clock fact."""
    model = ResearchUnheldCashAssumption.model_validate(term['research_assumption'])
    reference = term['retained_original_legal_record']
    name = reference['catalog_file']
    need(Path(name).name == name and name.endswith('.json'), 'OWN_INPUT_UNHELD_SINGLE_ORIGINAL_CATALOG')
    raw = (HERE / name).read_bytes()
    need(sha(raw) == reference['sha256'], 'OWN_INPUT_UNHELD_EXACT_ORIGINAL_CATALOG_BYTES')
    originals = [v for v in json.loads(raw)['records'] if digest(v) == reference['record_sha256']]
    need(len(originals) == 1, 'OWN_INPUT_UNHELD_EXACT_ORIGINAL_RECORD')
    original, = originals
    a, w = term['added'], term['identity_witness']
    need(original['kind'] == 'CASH_MERGER'
         and original['clock_scope'] == 'DAILY_MARKET_UNHELD_SOURCE'
         and original['held_representation_scope'] == 'SOURCE_UNHELD'
         and original['source_pending_scope'] == 'REFUSE_ALL_SOURCE_INTENTS'
         and original['exact_legal_effective_minute_proven'] is False
         and original['entitlement_aggregation'] == 'HOLDER'
         and original['native_events'] == [dict(session=term['native_session'], sha256=term['native_term_sha256'])],
         'OWN_INPUT_UNHELD_ORIGINAL_RECORD_AND_SCOPE')
    need(term['recognition_rule'] == RESEARCH_UNHELD_CASH
         and term['parent_cursor'] < w['session'] < term['native_session'] == term['last_trading_session']
             < a['session'] == term['actual_completion_date'] == original['legal_calendar_day']
             == original['economic_session'] == model.recognition_session
         and a['kind'] == 'CASH_MERGER' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and Fraction(str(a['cash_per_share'])) == Fraction(original['cash_per_share'])
             == Fraction(model.published_cash_per_share)
         and a['security_id'] == term['security_id'] == w['security_id'] == original['source_security_id']
         and term['ticker'] == w['ticker'] == original['source_ticker']
         and a['entitlement_aggregation'] == 'HOLDER'
         and all(a[k] is None for k in ('delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
                                        'exchange_ratio', 'cash_in_lieu_price_per_delivered_share'))
         and term['primary_source'] == original['primary_reference']
         and a['reference'] == term['primary_source'] + ' | ' + term['description'],
         'OWN_INPUT_UNHELD_RESEARCH_CLOSING_CASH_AND_IDENTITY')
    need(term['source_valuation_phase'] == 'CLOSE' and term['parent_positions'] == []
         and term['preopen_completion_confirmed'] is term['mandatory_common_share_completion_confirmed'] is False
         and term['completion_confirmed_by_close'] is False
         and term['portfolio_completion_authorized'] is False and term['require_unowned_and_unordered'] is True,
         'OWN_INPUT_UNHELD_NO_PORTFOLIO_COMPLETION_AUTHORITY')


def source_cash_term(term):
    a, w, primary = term['added'], term['identity_witness'], term['primary_extraction']
    need(term['recognition_rule'] == SOURCE_CLOSE
         and term['source_valuation_phase'] == 'CLOSE'
         and term['portfolio_completion_authorized'] is False
         and term['require_unowned_and_unordered'] is True
         and term['parent_positions'] == []
         and term['preopen_completion_confirmed'] is False
         and term['mandatory_common_share_completion_confirmed'] is True
         and a['kind'] == 'CASH_MERGER' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and term['parent_cursor'] < w['session'] < term['last_trading_session'] == term['native_session']
             < term['actual_completion_date'] == a['session']
         and a['entitlement_aggregation'] == 'HOLDER'
         and all(a[k] is None for k in ('delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
                                        'exchange_ratio', 'cash_in_lieu_price_per_delivered_share'))
         and a['reference'] == term['primary_source'] + ' | ' + term['description']
         and primary['actual_completion_date'] == term['actual_completion_date']
         and Fraction(primary['cash_per_ordinary_common_share']) == Fraction(str(a['cash_per_share']))
         and primary['mandatory_conversion'] is True and primary['preopen_time_established'] is False
         and primary['completion_confirmed_by_close'] is True
         and primary['recognition_convention'] == SOURCE_CLOSE,
         'OWN_INPUT_CLOSING_SOURCE_ONLY_NO_PORTFOLIO_COMPLETION_AUTHORITY')


def completion_cash_term(term):
    a, w = term['added'], term['identity_witness']
    primary = term['primary_extraction']
    need(term['recognition_rule'] == NEXT_COMPLETION and term['preopen_completion_confirmed'] is False
         and term['mandatory_common_share_completion_confirmed'] is True
         and a['kind'] == 'CASH_MERGER' and type(a['cash_per_share']) is float
         and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and w['session'] < term['last_trading_session'] == term['native_session']
             <= term['actual_completion_date'] < a['session']
         and a['entitlement_aggregation'] == 'HOLDER'
         and all(a[k] is None for k in ('delivered_security_id', 'delivered_ticker', 'delivered_issuer_id',
                                        'exchange_ratio', 'cash_in_lieu_price_per_delivered_share'))
         and a['reference'] == term['primary_source'] + ' | ' + term['description']
         and primary['actual_completion_date'] == term['actual_completion_date']
         and Fraction(primary['cash_per_ordinary_common_share']) == Fraction(str(a['cash_per_share']))
         and primary['mandatory_conversion'] is True and primary['preopen_time_established'] is False
         and primary['recognition_convention'] == 'FIRST_FROZEN_SESSION_STRICTLY_AFTER_CONFIRMED_COMPLETION',
         'OWN_INPUT_EXACT_CONFIRMED_CASH_RIGHT_AND_LATER_SESSION_CONVENTION')


def completion_session(term, dates):
    if term.get('recognition_rule') == PRIOR_STOCK:
        native = term['native_session']; completed = term['actual_completion_date']
        later = [day for day in dates if day > completed]
        need(dates == sorted(set(dates)) and native in dates and dates.index(native) > 0
             and dates.index(native) + 1 < len(dates) and later
             and dates[dates.index(native) - 1] == term['identity_witness']['session']
             and term['last_trading_session'] == native <= completed < term['added']['session']
             and later[0] == dates[dates.index(native) + 1] == term['added']['session'],
             'OWN_INPUT_PRIOR_STOCK_FIRST_FROZEN_SESSION_AFTER_COMPLETION')
        return
    if term.get('recognition_rule') == PREOPEN_STOCK:
        native = term['native_session']
        need(dates == sorted(set(dates)) and native in dates and dates.index(native) > 0
             and dates.index(native) + 1 < len(dates)
             and dates[dates.index(native) - 1] == term['identity_witness']['session']
             and term['last_trading_session'] == native
             and dates[dates.index(native) + 1] == term['added']['session'] == term['actual_completion_date'],
             'OWN_INPUT_PREOPEN_STOCK_EXACT_FROZEN_NEXT_SESSION')
        return
    if term.get('recognition_rule') == RESEARCH_MIXED:
        if term['research_assumption'].get('schema') == 'research.daily-mixed-consideration-assumption/3':
            model = ResearchAfterCloseMixedAssumption.model_validate(term['research_assumption'])
            recognition = research_after_close_mixed_timing(term, model)
            need(dates == sorted(set(dates)) and term['native_session'] in dates
                 and dates.index(term['native_session']) + 1 < len(dates)
                 and dates[dates.index(term['native_session']) + 1] == term['added']['session'] == recognition,
                 'OWN_INPUT_AFTERCLOSE_MIXED_EXACT_NEXT_FROZEN_DAILY_BOUNDARY')
        else:
            need(dates == sorted(set(dates)) and term['native_session'] in dates
                 and dates.index(term['native_session']) + 1 < len(dates)
                 and dates[dates.index(term['native_session']) + 1] == term['added']['session'] == term['actual_completion_date'],
                 'OWN_INPUT_RESEARCH_MIXED_NEXT_FROZEN_DAILY_BOUNDARY')
        return
    if term.get('recognition_rule') == RESEARCH_UNHELD_CASH:
        research_unheld_cash_term(term)
        native = term['native_session']
        need(dates == sorted(set(dates)) and native in dates and dates.index(native) > 0
             and dates.index(native) + 1 < len(dates)
             and dates[dates.index(native) - 1] == term['identity_witness']['session']
             and dates[dates.index(native) + 1] == term['added']['session'],
             'OWN_INPUT_UNHELD_RESEARCH_EXACT_NEXT_FROZEN_BOUNDARY')
        return
    if term.get('recognition_rule') == RESEARCH_SOURCE_EXIT:
        model = ResearchSourceExitAssumption.model_validate(term['research_assumption'])
        need(dates == sorted(set(dates)) and model.retained_quote_session in dates
             and dates.index(model.retained_quote_session) + 1 < len(dates)
             and dates[dates.index(model.retained_quote_session) + 1]
                 == term['native_session'] == term['added']['session'] == model.recognition_session,
             'OWN_INPUT_SOURCE_EXIT_EXACT_NEXT_FROZEN_DAILY_BOUNDARY')
        return
    if term.get('recognition_rule') == RESEARCH_TENDER:
        model = ResearchTenderAssumption.model_validate(term['research_assumption'])
        need(dates == sorted(set(dates)) and model.offer_deadline_session in dates
             and term['native_session'] in dates and dates.index(model.offer_deadline_session) + 1 < len(dates)
             and dates[dates.index(model.offer_deadline_session) + 1] == term['added']['session'] == model.recognition_session,
             'OWN_INPUT_TENDER_EXACT_NEXT_FROZEN_DAILY_BOUNDARY')
        return
    if term.get('recognition_rule') == RESEARCH_CASH:
        need(dates == sorted(set(dates)) and term['native_session'] in dates
             and dates.index(term['native_session']) + 1 < len(dates)
             and dates[dates.index(term['native_session']) + 1] == term['added']['session'],
             'OWN_INPUT_RESEARCH_EXACT_NEXT_FROZEN_DAILY_BOUNDARY')
        return
    if term.get('recognition_rule') != NEXT_COMPLETION:
        return
    completed = term['actual_completion_date']
    later = [day for day in dates if day > completed]
    need(dates == sorted(set(dates)) and later
         and later[0] == term['added']['session'],
         'OWN_INPUT_ACTUAL_FROZEN_FIRST_SESSION_AFTER_COMPLETION')


def confirmed_preopen_stock_term(term):
    """Qualify a mandatory stock-only right without changing canonical arithmetic."""
    a, w, dw, proxy = term['added'], term['identity_witness'], term['delivered_identity_witness'], term['proxy']
    ratio = a['exchange_ratio']
    need(type(ratio) is str, 'OWN_INPUT_PREOPEN_STOCK_LITERAL_RATIO')
    value = float(ratio)
    need(term['recognition_rule'] == PREOPEN_STOCK and a['kind'] == 'CASH_PLUS_STOCK'
         and math.isfinite(value) and value > 0 and Fraction(str(value)) == Fraction(ratio)
         and type(a['cash_per_share']) is float and math.isfinite(a['cash_per_share']) and a['cash_per_share'] == 0.
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and a['entitlement_aggregation'] == 'HOLDER' and a['cash_in_lieu_price_per_delivered_share'] is None
         and a['reference'] == term['primary_source'] + ' | ' + term['description']
         and type(term['timing_source']) is str and bool(term['timing_source'])
         and (a['delivered_security_id'], a['delivered_ticker'], a['delivered_issuer_id'])
             == (dw['security_id'], dw['ticker'], dw['issuer_id'])
         and w['session'] < term['last_trading_session'] == term['native_session'] < term['actual_completion_date'] == a['session']
         and term['mandatory_common_share_completion_confirmed'] is True
         and term['preopen_completion_confirmed'] is True
         and dw['session'] == proxy['session'] == a['session']
         and dw['security_id'] == proxy['security_id'] == a['delivered_security_id']
         and dw['source_observation_sha256'] == proxy['source_observation_sha256']
         and dw['ticker'] == proxy['ticker']
         and proxy['convention'] == 'RETAINED_CHILD_RAW_OPEN_RESEARCH_PROXY'
         and proxy['actual_settlement_rate_observed'] is False,
         'OWN_INPUT_EXACT_CONFIRMED_PREOPEN_ZERO_CASH_STOCK_RIGHT')
    primary = term['primary_extraction']
    need(primary == dict(actual_completion_date=term['actual_completion_date'],
             cash_per_ordinary_common_share='0', exchange_ratio=ratio, mandatory_conversion=True,
             preopen_time_established=True, recognition_convention=PREOPEN_STOCK),
         'OWN_INPUT_EXACT_PRIMARY_PREOPEN_STOCK_ONLY_EXTRACTION')
    result = deepcopy(term)
    result['added']['exchange_ratio'] = value
    return result


def confirmed_prior_stock_term(term):
    """Qualify a zero-cash right completed before its frozen recognition session."""
    from datetime import date
    a, w, dw, proxy = term['added'], term['identity_witness'], term['delivered_identity_witness'], term['proxy']
    ratio = a['exchange_ratio']
    need(type(ratio) is str, 'OWN_INPUT_PRIOR_STOCK_LITERAL_RATIO')
    value = float(ratio)
    date.fromisoformat(term['actual_completion_date'])
    need(term['recognition_rule'] == PRIOR_STOCK and a['kind'] == 'CASH_PLUS_STOCK'
         and math.isfinite(value) and value > 0 and Fraction(str(value)) == Fraction(ratio)
         and type(a['cash_per_share']) is float and math.isfinite(a['cash_per_share']) and a['cash_per_share'] == 0.
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and a['entitlement_aggregation'] == 'HOLDER' and a['cash_in_lieu_price_per_delivered_share'] is None
         and a['reference'] == term['primary_source'] + ' | ' + term['description']
         and type(term['timing_source']) is str and bool(term['timing_source'])
         and (a['delivered_security_id'], a['delivered_ticker'], a['delivered_issuer_id'])
             == (dw['security_id'], dw['ticker'], dw['issuer_id'])
         and w['session'] < term['last_trading_session'] == term['native_session'] <= term['actual_completion_date'] < a['session']
         and term['mandatory_common_share_completion_confirmed'] is True
         and term['preopen_completion_confirmed'] is False
         and dw['session'] == proxy['session'] == a['session']
         and dw['security_id'] == proxy['security_id'] == a['delivered_security_id']
         and dw['source_observation_sha256'] == proxy['source_observation_sha256']
         and dw['ticker'] == proxy['ticker']
         and proxy['convention'] == 'RETAINED_CHILD_RAW_OPEN_RESEARCH_PROXY'
         and proxy['actual_settlement_rate_observed'] is False,
         'OWN_INPUT_EXACT_CONFIRMED_PRIOR_ZERO_CASH_STOCK_RIGHT')
    need(term['primary_extraction'] == dict(actual_completion_date=term['actual_completion_date'],
             cash_per_ordinary_common_share='0', exchange_ratio=ratio, mandatory_conversion=True,
             preopen_time_established=False, recognition_convention=PRIOR_STOCK),
         'OWN_INPUT_EXACT_PRIMARY_PRIOR_STOCK_ONLY_EXTRACTION')
    result = deepcopy(term)
    result['added']['exchange_ratio'] = value
    return result


def selected_stock_term(term):
    """Normalize only a literal ratio, preserving its exact rational value."""
    if term.get('recognition_rule') == PRIOR_STOCK:
        return confirmed_prior_stock_term(term)
    if term.get('recognition_rule') == PREOPEN_STOCK:
        return confirmed_preopen_stock_term(term)
    from datetime import date
    a, w, dw = term['added'], term['identity_witness'], term['delivered_identity_witness']
    ratio = a['exchange_ratio']
    value = float(ratio)
    need(a['kind'] == 'CASH_PLUS_STOCK' and type(ratio) is str
         and math.isfinite(value) and value > 0 and Fraction(str(value)) == Fraction(ratio)
         and type(a['cash_per_share']) is float and math.isfinite(a['cash_per_share']) and a['cash_per_share'] > 0
         and a['security_id'] == term['security_id'] == w['security_id'] and w['ticker'] == term['ticker']
         and a['entitlement_aggregation'] == 'HOLDER' and a['cash_in_lieu_price_per_delivered_share'] is None
         and a['reference'] == term['primary_source'] + ' | ' + term['description']
         and (a['delivered_security_id'], a['delivered_ticker'], a['delivered_issuer_id'])
             == (dw['security_id'], dw['ticker'], dw['issuer_id'])
         and w['session'] < term['last_trading_session'] == term['native_session']
         and term['native_session'] < term['actual_completion_date'] < a['session']
         and date.fromisoformat(term['actual_completion_date']).weekday() >= 5
         and term['recognition_rule'] == 'FIRST_FROZEN_SESSION_AFTER_CONFIRMED_NONTRADING_DAY_COMPLETION'
         and term['mandatory_common_share_completion_confirmed'] is True
         and dw['session'] == term['proxy']['session'] == a['session']
         and dw['source_observation_sha256'] == term['proxy']['source_observation_sha256']
         and dw['ticker'] == term['proxy']['ticker']
         and term['proxy']['convention'] == 'RETAINED_CHILD_RAW_OPEN_RESEARCH_PROXY'
         and term['proxy']['actual_settlement_rate_observed'] is False,
         'OWN_INPUT_EXACT_RETAINED_STOCK_RIGHT_AND_RATIO_NORMALIZATION')
    result = deepcopy(term)
    result['added']['exchange_ratio'] = value
    return result


def retained_primary(term):
    source = term.get('retained_primary_catalog')
    if source is None:
        return
    raw = (HERE / source['filename']).read_bytes()
    original, = [t for t in json.loads(raw)['terms']
                 if t.get('security_id', t['added']['security_id']) == term['security_id']]
    identity = ('security_id', 'ticker', 'issuer_id', 'listing_first_session', 'security_type_eligible')
    need(sha(raw) == source['sha256'] and digest(original) == source['term_sha256']
         and all(term[k] == v for k, v in original.items() if k != 'identity_witness')
         and ('identity_witness' not in original or
              all(term['identity_witness'][k] == original['identity_witness'][k] for k in identity)),
         'OWN_CASH_UNCHANGED_RETAINED_PRIMARY_TERM_AND_SOURCE_METADATA')


def catalog_terms(codec, tickers):
    if 'terms' not in codec.catalog:
        c = codec.catalog
        need(tickers == ('S2',) and c['schema'] == 'research.system-campaign-sprint-terminal-facts/1',
             'FUTURE_ONLY_DECLARED_SINGLE_CATALOG_NORMALIZATION')
        return [dict(ticker='S2', security_id=c['added']['security_id'], native_session=c['native_session'],
            native_term_sha256=c['native_term_sha256'], added=deepcopy(c['added']),
            identity_witness=deepcopy(c['source_identity_witness']),
            delivered_identity_witness=deepcopy(c['delivered_identity_witness']),
            last_trading_session=c['native_session'], primary_source=c['primary_source'],
            timing_source=c['acquirer_source'], description=c['added']['reference'])]
    terms = [deepcopy(t) for t in codec.catalog['terms'] if t['ticker'] in tickers]
    need(tuple(t['ticker'] for t in terms) == tickers, 'FUTURE_EXACT_DECLARED_CATALOG_SUBSET')
    if 'identity_witness' in codec.catalog:
        for term in terms:
            need('identity_witness' not in term and term['native_session'] < term['added']['session']
                 and codec.catalog['identity_witness']['security_id'] == term['security_id'],
                 'FUTURE_EXACT_CATALOG_LEVEL_WITNESS_NORMALIZATION')
            term.update(identity_witness=deepcopy(codec.catalog['identity_witness']),
                        last_trading_session=term['native_session'], timing_source=term['exchange_source'])
    return terms


def compose(plans):
    """Compose only validated literal source terms; preserve every original term."""
    import importlib
    sources, terms = [], []
    for module, cls, catalog, tickers in plans:
        original = importlib.import_module(module)
        codec = getattr(original, cls)(HERE / catalog)
        terms.extend(catalog_terms(codec, tickers))
        sources.append(dict(catalog_file=catalog, catalog_sha256=codec.catalog_sha,
            validator_file=Path(original.__file__).name, validator_sha256=codec.compiler_sha,
            selected_tickers=list(tickers)))
    need(len(sources) > 1 and len({v['catalog_file'] for v in sources}) == len(sources)
         and len({v['validator_file'] for v in sources}) == len(sources), 'FUTURE_UNIQUE_COMPOSITION_SOURCES')
    need(len({t['ticker'] for t in terms}) == len({t['security_id'] for t in terms}) == len(terms)
         and len({(t['native_session'], t['security_id']) for t in terms}) == len(terms)
         and len({(t['added']['session'], t['security_id']) for t in terms}) == len(terms),
         'FUTURE_DISJOINT_COMPOSITION_EVENTS')
    manifest = dict(schema=COMPOSITION, sources=sources)
    selection = SimpleNamespace(catalog=dict(terms=terms), catalog_sha=digest(manifest),
        compiler_sha=digest([{v['validator_file']: v['validator_sha256']} for v in sources]), composition=manifest)
    return selection, 'EXPLICIT_ORDERED_CATALOG_COMPOSITION', terms


def original_ordinary_selection(arm, cursor):
    """Select future terms from an unchanged original ordinary cash validator."""
    import importlib
    plans = ORIGINAL_ORDINARY_PHASES.get((arm, cursor), ORIGINAL_ORDINARY_SOURCES.get(arm))
    if plans is None:
        return None
    sources = []
    for module_name, class_name, catalog, expected_sha in plans:
        raw = (HERE / catalog).read_bytes()
        need(sha(raw) == expected_sha, 'FUTURE_ORIGINAL_ORDINARY_CATALOG_BYTES')
        module = importlib.import_module(module_name)
        codec = getattr(module, class_name)(HERE / catalog)
        cash = [t for t in codec.catalog['terms'] if t['added']['kind'] == 'CASH_MERGER']
        need(not any(t['native_session'] <= cursor < t['added']['session'] for t in cash),
             'FUTURE_ORIGINAL_ORDINARY_NO_CONSUMED_PENDING_NATIVE')
        source = dict(catalog_file=catalog, catalog_sha256=codec.catalog_sha,
                      validator_file=Path(module.__file__).name, validator_sha256=codec.compiler_sha)
        sources.append((codec, catalog, source, cash))
    need(all(cash for _, _, _, cash in sources)
         and all(max(t['added']['session'] for t in left[3]) < min(t['native_session'] for t in right[3])
                 for left, right in zip(sources, sources[1:])),
         'FUTURE_ORIGINAL_ORDINARY_ORDERED_DISJOINT_CASH_CATALOGS')
    if (arm, cursor) in ORIGINAL_ORDINARY_AGGREGATE_PHASES:
        return aggregate_original_ordinary(arm, cursor, sources)
    for codec, catalog, source, cash in sources:
        terms = []
        for original in cash:
            if original['native_session'] <= cursor or original['added']['session'] <= cursor:
                continue
            term = deepcopy(original)
            term['original_ordinary_source'] = dict(source, term_sha256=digest(original))
            term['timing_source'] = original['primary_source']
            terms.append(term)
        if terms:
            codec.ordinary_source = source
            return codec, catalog, terms
    return None


def supplemental_selection(arm, cursor):
    """Select pinned original terminal catalogs even when their dates interleave."""
    import importlib
    terms, sources = [], []
    for module_name, class_name, constructor, catalog, catalog_sha, validator_sha, tickers in SUPPLEMENTAL_PHASES.get((arm, cursor), ()):
        raw = (HERE / catalog).read_bytes()
        module = importlib.import_module(module_name)
        need(sha(raw) == catalog_sha and sha(Path(module.__file__).read_bytes()) == validator_sha,
             'FUTURE_SUPPLEMENT_EXACT_ORIGINAL_SOURCE_BYTES')
        need(constructor in ('PATH', 'JSON'), 'FUTURE_SUPPLEMENT_DECLARED_CONSTRUCTOR')
        codec = getattr(module, class_name)(HERE / catalog if constructor == 'PATH' else json.loads(raw))
        selected_terms = catalog_terms(codec, tickers)
        if (arm, cursor) in SUPPLEMENTAL_SAME_DAY_PHASES:
            need(selected_terms and all(t['added']['kind'] in ('CASH_MERGER', 'CASH_PLUS_STOCK')
                 and cursor < t['native_session'] <= t['added']['session']
                 and (t['native_session'] < t['added']['session'] or
                      (t['added']['kind'] == 'CASH_MERGER'
                       and t['recognition_rule'] == 'CONFIRMED_PREOPEN_COMPLETION'
                       and t['preopen_completion_confirmed'] is True)) for t in selected_terms),
                 'FUTURE_SUPPLEMENT_EXPLICIT_ORIGINAL_SAME_DAY_PREOPEN_CASH_ONLY')
        else:
            need(selected_terms and all(t['added']['kind'] in ('CASH_MERGER', 'CASH_PLUS_STOCK')
                 and cursor < t['native_session'] < t['added']['session'] for t in selected_terms),
                 'FUTURE_SUPPLEMENT_ONLY_UNCONSUMED_TERMS')
        source = dict(catalog_file=catalog, catalog_sha256=catalog_sha,
                      validator_file=Path(module.__file__).name, validator_sha256=validator_sha,
                      selected_tickers=list(tickers))
        if (arm, cursor) in SUPPLEMENTAL_SHARED_VALIDATOR_PHASES:
            need(not any(s['catalog_file'] == catalog for s in sources)
                 and all(s['validator_file'] != source['validator_file']
                         or s['validator_sha256'] == source['validator_sha256'] for s in sources),
                 'FUTURE_SUPPLEMENT_OPT_IN_UNIQUE_CATALOG_AND_IDENTICAL_SHARED_VALIDATOR')
        else:
            need(not any(s['catalog_file'] == catalog or s['validator_file'] == source['validator_file'] for s in sources),
                 'FUTURE_SUPPLEMENT_UNIQUE_SOURCE_COMPONENTS')
        sources.append(source)
        for term in selected_terms:
            term['original_ordinary_source'] = dict(source, term_sha256=digest(term))
            term.setdefault('timing_source', term['primary_source'])
        terms = merge_selected_terms(terms, selected_terms)
    return terms, sources


def merge_selected_terms(primary, extra):
    terms = deepcopy(primary) + deepcopy(extra)
    need(len({t['security_id'] for t in terms}) == len(terms)
         and len({(t['native_session'], t['security_id']) for t in terms}) == len(terms)
         and len({(t['added']['session'], t['security_id']) for t in terms}) == len(terms),
         'FUTURE_ORIGINAL_ORDINARY_DISJOINT_SELECTED_TERMS')
    return terms


ORIGINAL_CONTRACT_DELIVERY_PHASES = {('P05', '2021-03-31'): {'module': 'system_campaign_distribution_facts', 'class_name': 'DistributionFacts', 'catalog_file': 'system-campaign-distribution-facts.json', 'catalog_sha256': 'db0e6498224929c322c1a73a0e5b7942110e7a1c645db8f6b21bd329f22d41ae', 'validator_file': 'system_campaign_distribution_facts.py', 'validator_sha256': 'c83a3ed96b2334333fde7f8f2d05ef9e4c2b98d7a52c4be5e437a6b954aa88bb', 'selected_tickers': ('APHA',), 'parent_outer_sha256': '57fc54933459d897d290094c7cb3b9c1c5d1195ff2dd1eea182284941302070a', 'parent_root_admission_sha256': 'b1b4db73909f584bf7704cf33158eacc9ce1f8a8cbe212785d8f9b3404e6dede', 'source_capture': {'run_id': 41971859824, 'head': 'f304f01185feadb9ab9ecd2509d9f9a57b3f2ee6', 'artifact_id': 13390251892, 'payload_sha256': '90d3c08c6010986bfb852984645e262ad623b9ba4221510e8b8e8c1fcf49a667', 'scope_sha256': 'b3cec0ea35dd39cd8a6ea16e2e1366c01783d507ebd85d2514b5278d269a885d', 'independent_data_review_sha256': '7713d40d4c9a9234603be70d13cf07d037881837f66c2d911a20bc37465f2822', 'independent_qualification_sha256': 'e0f57b8f67e0c89207980ed17a3f09ef20fb72ee45ad9b4781167c67c7df8185'}}}
FUTURE_LITERAL_PHASES['P05', '2021-03-31'] = ('system_campaign_following_completions_facts', 'FollowingFacts', 'system-campaign-following-completions-terminal-facts.json', ('CATM', 'AZPN1', 'REGI', 'PLAN'))
ORIGINAL_CONTRACT_DELIVERY_PHASES['P06', '2021-03-31'] = {'module': 'system_campaign_distribution_facts', 'class_name': 'DistributionFacts', 'catalog_file': 'system-campaign-distribution-facts.json', 'catalog_sha256': 'db0e6498224929c322c1a73a0e5b7942110e7a1c645db8f6b21bd329f22d41ae', 'validator_file': 'system_campaign_distribution_facts.py', 'validator_sha256': 'c83a3ed96b2334333fde7f8f2d05ef9e4c2b98d7a52c4be5e437a6b954aa88bb', 'selected_tickers': ('APHA',), 'parent_outer_sha256': '41eb70aa3f3feab4190426a9b17e0ea3f20499607ccfa1e4e86d39c309355246', 'parent_root_admission_sha256': 'f8be3c331ac12f211c630078d128278c155eb99a98afaff81bc8219e435094aa', 'source_capture': {'run_id': 41978263810, 'head': 'a0a06b71157b91557bf30951ac4dc7a2aba243ca', 'artifact_id': 13392737266, 'payload_sha256': 'c6727b4380c713d4ad4b506893605d1058db20eec740782cfc1273688febc375', 'scope_sha256': '9433a201e6c3c63b2edaac2c7e3dc4cee42225e5a875fb153e37403abcd8cb9c', 'independent_data_review_sha256': '5aa84297a314aa70e6931f46fdef427b8e09302d5c13226242ab365a401ff1f5', 'independent_qualification_sha256': '3258f81d440e1e01530d2abd9141e9a25c872eb8841b9a0bdde71071f1f34990'}}


def contractual_delivery_addition(term, row):
    """Preserve a pinned original contractual zero; a quote cannot price it."""
    plan = ORIGINAL_CONTRACT_DELIVERY_PHASES[term['arm'], term['parent_cursor']]
    source = term['original_contract_source']
    raw = (HERE / plan['catalog_file']).read_bytes()
    need(sha(raw) == plan['catalog_sha256']
         and sha((HERE / plan['validator_file']).read_bytes()) == plan['validator_sha256'],
         'FUTURE_CONTRACT_EXACT_ORIGINAL_CATALOG_AND_VALIDATOR')
    originals = [t for t in json.loads(raw)['terms'] if t['ticker'] in plan['selected_tickers']
                 and digest(t) == source['term_sha256']]
    need(len(originals) == 1, 'FUTURE_CONTRACT_EXACT_ONE_ORIGINAL_LITERAL_TERM')
    original = originals[0]
    expected = dict(catalog_file=plan['catalog_file'], catalog_sha256=plan['catalog_sha256'],
        validator_file=plan['validator_file'], validator_sha256=plan['validator_sha256'],
        selected_tickers=list(plan['selected_tickers']), term_sha256=digest(original))
    need(source == term['original_ordinary_source'] == expected
         and term['source_capture'] == plan['source_capture']
         and term['parent_outer_sha256'] == plan['parent_outer_sha256']
         and term['parent_root_admission_sha256'] == plan['parent_root_admission_sha256']
         and term['added'] == original['added'] and term['proxy'] == original['proxy']
         and term['native_session'] == original['native_session']
         and term['native_term_sha256'] == original['native_term_sha256']
         and original['added']['kind'] in ('CONVERSION', 'CASH_PLUS_STOCK')
         and original['proxy']['convention'] == 'CONTRACTUAL_ZERO_FRACTIONAL_CONSIDERATION'
         and type(original['added']['cash_in_lieu_price_per_delivered_share']) is float
         and original['added']['cash_in_lieu_price_per_delivered_share'] == 0.0,
         'FUTURE_CONTRACT_EXACT_SOURCE_LITERAL_ZERO_NOT_RESEARCH_PROXY')
    need(ordinary_delivery_identity(term, row) == term['delivered_identity_witness'],
         'FUTURE_CONTRACT_EXACT_FROZEN_DELIVERED_IDENTITY')
    return deepcopy(original['added'])


def contractual_delivery_selection(cp, arm):
    """Select only explicit original contract facts from this exact own root."""
    import importlib
    from system_campaign_financial_partial import root_spec
    plan = ORIGINAL_CONTRACT_DELIVERY_PHASES.get((arm, cp['source_cursor']))
    if plan is None:
        return [], []
    raw = (HERE / plan['catalog_file']).read_bytes()
    module = importlib.import_module(plan['module'])
    need(sha(raw) == plan['catalog_sha256'] and Path(module.__file__).name == plan['validator_file']
         and sha(Path(module.__file__).read_bytes()) == plan['validator_sha256'],
         'FUTURE_CONTRACT_EXACT_PINNED_ORIGINAL_SOURCE_BYTES')
    codec = getattr(module, plan['class_name'])(HERE / plan['catalog_file'])
    candidates = catalog_terms(codec, plan['selected_tickers'])
    need(tuple(t['ticker'] for t in candidates) == plan['selected_tickers']
         and codec.catalog_sha == plan['catalog_sha256'] and codec.compiler_sha == plan['validator_sha256']
         and all(cp['source_cursor'] < t['native_session'] < t['added']['session']
                 and t['added']['kind'] in ('CONVERSION', 'CASH_PLUS_STOCK')
                 and t['proxy']['convention'] == 'CONTRACTUAL_ZERO_FRACTIONAL_CONSIDERATION'
                 and type(t['added']['cash_in_lieu_price_per_delivered_share']) is float
                 and t['added']['cash_in_lieu_price_per_delivered_share'] == 0.0 for t in candidates),
         'FUTURE_CONTRACT_ONLY_DECLARED_UNCONSUMED_ORIGINAL_ZERO_VALUES')
    source_capture = plan['source_capture']
    need(all(type(source_capture[k]) is str and len(source_capture[k]) == 64
             and all(c in '0123456789abcdef' for c in source_capture[k]) for k in
             ('payload_sha256', 'scope_sha256', 'independent_data_review_sha256', 'independent_qualification_sha256'))
         and type(source_capture['run_id']) is int and source_capture['run_id'] > 0
         and type(source_capture['artifact_id']) is int and source_capture['artifact_id'] > 0
         and type(source_capture['head']) is str and len(source_capture['head']) == 40,
         'FUTURE_CONTRACT_REQUIRES_CLOSED_SOURCE_DATA_AND_QUALIFICATION')
    scope = registered_scope(source_capture['scope_sha256'])
    parent = root_spec(arm, plan['parent_root_admission_sha256'])
    need(cp['sha256'] == plan['parent_outer_sha256'] == scope['parent_outer_sha256'] == parent['outer_sha256']
         and cp['source_cursor'] == scope['parent_cursor'] == parent['selected_session'],
         'FUTURE_CONTRACT_EXACT_OWN_SOURCE_AND_ADMITTED_PARENT')
    source = dict(catalog_file=plan['catalog_file'], catalog_sha256=codec.catalog_sha,
        validator_file=plan['validator_file'], validator_sha256=codec.compiler_sha,
        selected_tickers=list(plan['selected_tickers']))
    terms = []
    for original in candidates:
        declared, = [t for t in scope['terms'] if t['security_id'] == original['security_id']]
        child, = [t for t in scope['additional_rows'] if t['security_id'] == original['added']['delivered_security_id']
                    and t['session'] == original['added']['session']]
        positions = lambda sid: [dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
            for _, e in sorted(cp['run']['state']['wealth_core']['episodes'].items(), key=lambda pair: int(pair[0])) if e['security_id'] == sid]
        need(declared['native_session'] == original['native_session']
             and declared['native_term_sha256'] == original['native_term_sha256']
             and child['source_observation_sha256'] == original['proxy']['source_observation_sha256']
             and positions(original['security_id']) == declared['parent_positions']
             and positions(child['security_id']) == child['parent_positions']
             and not any(p['security_id'] in (original['security_id'], child['security_id']) for p in cp['run']['state']['pending']),
             'FUTURE_CONTRACT_EXACT_NATIVE_DELIVERY_AND_ACTUAL_PARENT_CHILD_ROLES')
        term = deepcopy(original)
        term.update(arm=arm, parent_cursor=cp['source_cursor'], parent_outer_sha256=cp['sha256'],
            parent_root_admission_sha256=plan['parent_root_admission_sha256'], source_capture=deepcopy(source_capture),
            original_ordinary_source=dict(source, term_sha256=digest(original)),
            original_contract_source=dict(source, term_sha256=digest(original)), timing_source=original['primary_source'])
        terms.append(term)
    return terms, [source]


def original_phase_delivery_selection(arm, cursor):
    """Aggregate explicit original delivery subsets without changing their facts."""
    import importlib
    plans = ORIGINAL_DELIVERY_PHASES[arm, cursor]
    need(plans, 'FUTURE_ORIGINAL_PHASE_NONEMPTY_DELIVERY_SOURCES')
    sources, terms, selected = [], [], []
    for module_name, class_name, catalog, expected_sha in plans:
        raw = (HERE / catalog).read_bytes()
        need(sha(raw) == expected_sha, 'FUTURE_ORIGINAL_DELIVERY_CATALOG_BYTES')
        module = importlib.import_module(module_name)
        codec = getattr(module, class_name)(HERE / catalog)
        declared = ORIGINAL_DELIVERY_SUBSETS.get((arm, cursor, catalog))
        if 'terms' in codec.catalog:
            candidates = [t for t in codec.catalog['terms'] if t['added']['kind'] in ('CASH_PLUS_STOCK', 'CONVERSION')]
        else:
            need(declared is not None, 'FUTURE_ORIGINAL_SINGLE_LAYOUT_REQUIRES_EXPLICIT_SUBSET')
            candidates = catalog_terms(codec, declared)
        if declared is not None:
            need(type(declared) is tuple and declared and len(set(declared)) == len(declared),
                 'FUTURE_ORIGINAL_PHASE_UNIQUE_DECLARED_DELIVERY_SUBSET')
            candidates = [t for t in candidates if t['ticker'] in declared]
            need(tuple(t['ticker'] for t in candidates) == declared,
                 'FUTURE_ORIGINAL_PHASE_EXACT_EXISTING_DELIVERY_SUBSET')
        need(candidates and all(cursor < t['native_session'] < t['added']['session']
             and t['added']['cash_in_lieu_price_per_delivered_share'] is None
             and ((t['added']['kind'] == 'CONVERSION' and t['added']['cash_per_share'] is None)
                  or t['added']['kind'] == 'CASH_PLUS_STOCK') for t in candidates),
             'FUTURE_ORIGINAL_PHASE_UNCONSUMED_PROXY_DELIVERIES_ONLY')
        source = dict(catalog_file=catalog, catalog_sha256=codec.catalog_sha,
                      validator_file=Path(module.__file__).name, validator_sha256=codec.compiler_sha)
        need(codec.catalog_sha == expected_sha and codec.compiler_sha == sha(Path(module.__file__).read_bytes()),
             'FUTURE_ORIGINAL_PHASE_EXACT_CATALOG_VALIDATOR_BINDING')
        need(not any(v['catalog_file'] == catalog or v['validator_file'] == source['validator_file'] for v in sources),
             'FUTURE_ORIGINAL_PHASE_UNIQUE_DELIVERY_SOURCE_COMPONENTS')
        if declared is not None:
            source['selected_tickers'] = list(declared)
        addition = []
        for original in candidates:
            term = deepcopy(original)
            term['original_ordinary_source'] = dict(source, term_sha256=digest(original))
            term['timing_source'] = original['primary_source']
            addition.append(term)
        terms = merge_selected_terms(terms, addition)
        sources.append(source)
        selected.append((codec, catalog))
    if len(selected) == 1:
        codec, catalog = selected[0]
        codec.ordinary_source = sources[0]
        return codec, catalog, terms
    manifest = dict(schema=COMPOSITION, sources=sources)
    codec = SimpleNamespace(catalog=dict(terms=deepcopy(terms)), catalog_sha=digest(manifest),
        compiler_sha=digest([{v['validator_file']: v['validator_sha256']} for v in sources]),
        composition=manifest, ordinary_sources=sources)
    return codec, 'EXPLICIT_ORDERED_ORIGINAL_DELIVERY_COMPOSITION', terms


def original_delivery_selection(arm, cursor):
    """Future delivery terms from unchanged literal validators; cash selection is separate."""
    import importlib
    if (arm, cursor) in ORIGINAL_DELIVERY_PHASES:
        return original_phase_delivery_selection(arm, cursor)
    for module_name, class_name, catalog, expected_sha in ORIGINAL_DELIVERY_SOURCES.get(arm, ()):
        raw = (HERE / catalog).read_bytes()
        need(sha(raw) == expected_sha, 'FUTURE_ORIGINAL_DELIVERY_CATALOG_BYTES')
        module = importlib.import_module(module_name)
        codec = getattr(module, class_name)(HERE / catalog)
        mixed = [t for t in codec.catalog['terms'] if t['added']['kind'] in ('CASH_PLUS_STOCK', 'CONVERSION')]
        need(not any(t['native_session'] <= cursor < t['added']['session'] for t in mixed),
             'FUTURE_ORIGINAL_DELIVERY_NO_CONSUMED_PENDING_NATIVE')
        source = dict(catalog_file=catalog, catalog_sha256=codec.catalog_sha,
                      validator_file=Path(module.__file__).name, validator_sha256=codec.compiler_sha)
        terms = []
        for original in mixed:
            if original['native_session'] <= cursor or original['added']['session'] <= cursor:
                continue
            term = deepcopy(original)
            term['original_ordinary_source'] = dict(source, term_sha256=digest(original))
            term['timing_source'] = original['primary_source']
            terms.append(term)
        if terms:
            codec.ordinary_source = source
            return codec, catalog, terms
    return None


def ordinary_delivery_identity(term, row):
    """Retain the exact original delivered row and its descriptive identity."""
    from datetime import date
    proxy, added = term['proxy'], term['added']
    need(row['session'] == proxy['session'] == added['session']
         and row['security_id'] == proxy['security_id'] == added['delivered_security_id']
         and digest(row) == proxy['source_observation_sha256']
         and row['ticker'] == added['delivered_ticker']
         and row['issuer_id'] == added['delivered_issuer_id']
         and row['security_type_eligible'] in ('0', '1')
         and date.fromisoformat(row['listing_first_session']) <= date.fromisoformat(row['session']),
         'FUTURE_ORIGINAL_DELIVERY_EXACT_FROZEN_IDENTITY_AND_PROXY')
    return dict({k: row[k] for k in ('session', 'security_id', 'ticker', 'issuer_id',
                                    'listing_first_session', 'security_type_eligible')},
                source_observation_sha256=digest(row))


def inherited_delivery_row(term):
    """Resolve a declared inherited proxy from original frozen input bytes."""
    hosted()
    from research.pooled_input_support import inputs
    proxy = term['proxy']
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        rows = [r for r in inputs._archive_rows(archive, 'observations-' + proxy['session'][:4] + '.csv.gz')
                if (r['session'], r['security_id']) == (proxy['session'], proxy['security_id'])]
    need(len(rows) == 1, 'FUTURE_INHERITED_DELIVERY_ONE_FROZEN_ROW')
    return rows[0]


def inherited_delivery_addition(term, row):
    ordinary_delivery_identity(term, row)
    value = float(row['raw_open'])
    need(term['added']['kind'] in ('CASH_PLUS_STOCK', 'CONVERSION')
         and term['added']['cash_in_lieu_price_per_delivered_share'] is None
         and math.isfinite(value) and value > 0, 'FUTURE_INHERITED_DELIVERY_EXACT_POSITIVE_RAW_OPEN')
    return dict(deepcopy(term['added']), cash_in_lieu_price_per_delivered_share=value)


def remaining_ordinary_terms(cp, terms, root):
    """Preserve source-bound forward repairs instead of suppressing them twice."""
    documents = []
    for entry in cp['repairs']:
        name = entry['filename']
        need(name == entry['sha256'] + '.json' and Path(name).name == name,
             'FUTURE_INHERITED_ORDINARY_SAFE_REPAIR_NAME')
        raw = (Path(root) / 'book/repairs' / name).read_bytes()
        need(sha(raw) == entry['sha256'], 'FUTURE_INHERITED_ORDINARY_EXACT_REPAIR_BYTES')
        doc = json.loads(raw)
        need(doc['predecessor_checkpoint_sha256'] == entry['predecessor_checkpoint_sha256'],
             'FUTURE_INHERITED_ORDINARY_EXACT_REPAIR_PREDECESSOR')
        if doc['schema'] != 'terminal-repair/1':
            from system_campaign_financial_branches import INPUT, validate_input
            need(doc['schema'] == INPUT and validate_input(Path(root), cp) == entry['sha256'],
                 'FUTURE_INHERITED_ORDINARY_EXACT_RETAINED_TYPED_INPUT')
            continue
        documents.append((entry, doc))
    remaining, inherited = [], []
    for term in terms:
        sid = term['security_id']
        suppress = [(e, v) for e, d in documents for v in d['suppress'] if v['security_id'] == sid]
        added = [(e, v) for e, d in documents for v in d['add'] if v['security_id'] == sid]
        if not suppress and not added:
            remaining.append(deepcopy(term))
            continue
        expected = dict(session=term['native_session'], security_id=sid, term_sha256=term['native_term_sha256'])
        comparison = term['added']
        delivery_row = None
        if (len(suppress) == len(added) == 1 and comparison['kind'] in ('CASH_PLUS_STOCK', 'CONVERSION')
                and comparison['cash_in_lieu_price_per_delivered_share'] is None):
            delivery_row = inherited_delivery_row(term)
            comparison = inherited_delivery_addition(term, delivery_row)
        economic = lambda v: {k: x for k, x in v.items() if k not in ('session', 'reference')}
        need(len(suppress) == len(added) == 1 and suppress[0][1] == expected
             and suppress[0][0] == added[0][0]
             and economic(added[0][1]) == economic(comparison)
             and added[0][1]['session'] > cp['source_cursor']
             and added[0][1]['session'] >= term['native_session'],
             'FUTURE_INHERITED_ORDINARY_ONE_EQUIVALENT_FORWARD_EVENT')
        record = dict(security_id=sid, ticker=term['ticker'], repair=deepcopy(added[0][0]),
            suppressed_native=deepcopy(suppress[0][1]), inherited_addition=deepcopy(added[0][1]),
            selected_catalog_addition=deepcopy(term['added']), original_ordinary_source=deepcopy(term['original_ordinary_source']),
            inherited_date_and_reference_preserved=True)
        if delivery_row is not None:
            record.update(inherited_delivery_source_row=deepcopy(delivery_row), hydrated_catalog_addition=comparison)
        inherited.append(record)
    return remaining, inherited


def ordinary_term_dates(term, dates):
    native, effective = term['native_session'], term['added']['session']
    need(dates == sorted(set(dates)) and native in dates and effective in dates
         and dates.index(native) > 0 and dates.index(effective) > 0,
         'FUTURE_ORIGINAL_ORDINARY_EXACT_FROZEN_DATES')
    term = deepcopy(term)
    term['ordinary_identity_session'] = dates[dates.index(native) - 1]
    term['last_trading_session'] = dates[dates.index(effective) - 1]
    return term


def ordinary_identity(term, row):
    from datetime import date
    need(row['security_id'] == term['security_id'] and row['ticker'] == term['ticker']
         and row['session'] == term['ordinary_identity_session']
         and date.fromisoformat(row['listing_first_session']) <= date.fromisoformat(row['session'])
         and row['security_type_eligible'] in ('0', '1') and type(row['issuer_id']) is str,
         'FUTURE_ORIGINAL_ORDINARY_UNMODIFIED_FROZEN_IDENTITY')
    witness = {k: row[k] for k in ('session', 'security_id', 'ticker', 'issuer_id',
                                  'listing_first_session', 'security_type_eligible')}
    return dict(witness, source_observation_sha256=digest(row))


def selected(arm, *, cursor=None):
    import importlib
    if (arm, cursor) in RETAINED_OWN_CASH_PHASES:
        return retained_own_cash_selection(arm, cursor)
    if (arm, cursor) in OWN_CASH_PHASES:
        return own_cash_selection(arm, cursor)
    ordinary = original_ordinary_selection(arm, cursor)
    if ordinary is not None:
        return ordinary
    delivery = original_delivery_selection(arm, cursor)
    if delivery is not None and (arm, cursor) not in ORIGINAL_DELIVERY_PHASES:
        return delivery
    if (arm, cursor) in ORIGINAL_DELIVERY_PHASES:
        need((arm, cursor) in FUTURE_LITERAL_PHASES, 'FUTURE_COMPOSED_DELIVERY_REQUIRES_DECLARED_PRIMARY')
    if arm == 'P07':
        need(cursor == '2019-12-31' or (arm, cursor) in SINGLE_PHASES or (arm, cursor) in FOLLOWING_PHASES
             or (arm, cursor) in FUTURE_LITERAL_PHASES or (arm, cursor) in CASH_PHASES,
             'FUTURE_EXACT_ADMITTED_MDCO_PHASE')
    if (arm, cursor) in COMBINED_PHASES:
        return compose(COMBINED_PHASES[arm, cursor])
    if (arm, cursor) in CASH_PHASES:
        from system_campaign_cash_calendar import CashCalendar
        catalog, tickers = CASH_PHASES[arm, cursor]
        raw = (HERE / catalog).read_bytes()
        codec = CashCalendar(json.loads(raw))
        codec.catalog_sha = sha(raw)
        codec.compiler_sha = sha(Path(importlib.import_module('system_campaign_cash_calendar').__file__).read_bytes())
    else:
        phases = {**SINGLE_PHASES, **FOLLOWING_PHASES, **FUTURE_LITERAL_PHASES}
        module, cls, catalog, tickers = phases[arm, cursor] if (arm, cursor) in phases else PLANS[arm]
        codec = getattr(importlib.import_module(module), cls)(HERE / catalog)
    terms = catalog_terms(codec, tickers)
    return codec, catalog, terms


def stage_selected_sources(spec, old, out):
    """Host-only bounded fetch of one pinned source; workers remain offline."""
    phase = spec['arm'], spec['selected_session']
    bound = ROOT_BOUND_ALIAS_SOURCE_PHASES.get(phase)
    if bound is not None:
        need((spec.get('root_admission_sha256'), spec.get('outer_sha256'), spec.get('measured_closes')) == bound,
             'FUTURE_ALIAS_SOURCE_EXACT_QUALIFIED_OWN_ROOT')
    if phase not in SINGLE_PHASES and phase not in FOLLOWING_PHASES and phase not in ADDITIONAL_SENSOR_ALIAS_PHASES:
        return
    import os
    from urllib.request import urlopen
    from system_campaign_sprint_facts import ALIAS_BYTES, ALIAS_SHA, ALIAS_URL, alias_rows
    need(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
         and os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'FUTURE_PUBLIC_SOURCE_HOSTED_ORCHESTRATOR_ONLY')
    folder = out / 'provider-source'
    folder.mkdir()
    target = folder / 'SHARADAR_ACTIONS.zip'
    retained = old / 'provider-source/SHARADAR_ACTIONS.zip'
    need(phase not in FOLLOWING_PHASES or retained.is_file(), 'FUTURE_CONSUMED_ALIAS_SOURCE_MUST_BE_RETAINED_NOT_REFETCHED')
    if retained.is_file():
        raw = retained.read_bytes()
        mode = 'EXACT_RETAINED_ORIGINAL'
    else:
        with urlopen(ALIAS_URL, timeout=60) as response:
            need(response.status == 200 and response.headers.get('Content-Encoding', 'identity') == 'identity',
                 'FUTURE_PINNED_PUBLIC_SOURCE_RESPONSE')
            raw = response.read(ALIAS_BYTES + 1)
        mode = 'EXACT_FROZEN_PUBLIC_OBJECT_FETCHED_ONCE'
    need(len(raw) == ALIAS_BYTES and sha(raw) == ALIAS_SHA, 'FUTURE_ORIGINAL_PROVIDER_BYTES_BEFORE_PARSE')
    target.write_bytes(raw)
    catalog = json.loads((HERE / SINGLE_PHASES['P07', '2020-02-28'][2]).read_bytes())
    rows = alias_rows(target, catalog['provider_alias_source']['selected_row_sha256'])
    save(out / 'provider-alias-proof.json', dict(source_sha256=ALIAS_SHA, source_bytes=len(raw),
        selected_rows=rows, selected_security_ids=[catalog['added']['security_id']], acquisition=mode,
        descriptive_fields_used_only_for_action_identity=True, strategy_metadata_upgraded=False))


def pending_completion(cp, term):
    """Only separately source-bound pending natives may be completed after consumption."""
    if term.get('arm') == 'P00' and term['added']['kind'] == 'CASH_PLUS_STOCK':
        return pending_source_completion(cp, term)
    sid = term['security_id']
    w = cp['run']['state']['wealth_core']
    held = [(k, e) for k, e in w['episodes'].items() if e['security_id'] == sid]
    pending = w.get('terminal_pending_terms', {}).get(sid, {})
    need(sid == '510659411298086546' and term['ticker'] == 'MNTA'
         and cp['source_cursor'] == term['native_session'] == '2020-09-30'
         and term['added']['session'] == '2020-10-01' and term['added']['cash_per_share'] == 52.5
         and w['terminal_pending_sessions'].get(sid) == 0 and pending.get('stale_at_event') == 0
         and digest(pending.get('terms')) == term['native_term_sha256']
         and len(held) == 1 and held[0][0] == '5' and held[0][1]['slot_id'] == 5
         and held[0][1]['current_shares'] == 101 and held[0][1]['exit_pending'] is False
         and w['slots']['5']['occupied_by'] == sid and sid not in w.get('unresolved_terminals', {})
         and w['terminal_carry_audit'][sid] == dict(carry_price=52.49, carry_session='2020-09-30',
             grace_prints=[dict(price=52.48, session='2020-09-30')], grace_split_multiplier=1.,
             grace_splits=[], last_trustworthy_print_session='2020-09-29', shares_at_carry=101),
         'FUTURE_EXACT_ADMITTED_HELD_MNTA_PENDING_NATIVE')


def pending_source_completion(cp, term):
    source = term['source_capture']
    scope = registered_scope(source['scope_sha256'])
    declared, = scope['terms']
    sid = term['security_id']; w = cp['run']['state']['wealth_core']
    held = [dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
            for _, e in sorted(w['episodes'].items(), key=lambda item: int(item[0])) if e['security_id'] == sid]
    pending = w.get('terminal_pending_terms', {}).get(sid, {})
    need((term['arm'], term['parent_cursor']) == ('P00', '2018-08-31')
         and cp['sha256'] == term['parent_outer_sha256'] == scope['parent_outer_sha256']
         and cp['source_cursor'] == scope['parent_cursor'] == term['native_session']
         and (source['run_id'], source['head'], source['artifact_id']) == OWN_CASH_SOURCE_CLOCKS['P00', '2018-08-31']
         and held == term['parent_positions'] == declared['parent_positions'] and held
         and w['terminal_pending_sessions'].get(sid) == declared['pending_at_parent']['pending_sessions'] == 0
         and pending.get('stale_at_event') == declared['pending_at_parent']['stale_at_event'] == 0
         and digest(pending.get('terms')) == term['native_term_sha256'] == declared['native_term_sha256']
         and sid not in w.get('unresolved_terminals', {})
         and all(w['slots'][str(e['slot_id'])]['occupied_by'] == sid and e['exit_pending'] is False
                 for e in w['episodes'].values() if e['security_id'] == sid)
         and not any(e['security_id'] == term['added']['delivered_security_id'] for e in w['episodes'].values())
         and term['added']['session'] > cp['source_cursor'],
         'FUTURE_EXACT_SOURCE_BOUND_OWN_PENDING_STOCK_COMPLETION')


def suppressions(cp, terms):
    result = []
    for t in terms:
        need(t['added']['session'] > cp['source_cursor'], 'FUTURE_COMPLETE_TERMS_UNCONSUMED')
        if t['native_session'] <= cp['source_cursor']:
            pending_completion(cp, t)
        else:
            result.append(dict(session=t['native_session'], security_id=t['security_id'],
                               term_sha256=t['native_term_sha256']))
    return result


def hydrate(cp, arm, *, source_root=None):
    hosted()
    from research.pooled_input_support import inputs
    from system_campaign_2021_completions_facts import require_witness, CIL
    codec, catalog, terms = selected(arm, cursor=cp['source_cursor'])
    aliases = None
    alias_catalog = None
    if (arm, cp['source_cursor']) in SINGLE_PHASES or (arm, cp['source_cursor']) in FOLLOWING_PHASES:
        from system_campaign_sprint_facts import alias_rows
        need(source_root is not None, 'FUTURE_EXPLICIT_OWN_PROVIDER_SOURCE_ROOT')
        alias_catalog = json.loads((HERE / SINGLE_PHASES['P07', '2020-02-28'][2]).read_bytes())
        aliases = alias_rows(Path(source_root) / 'provider-source/SHARADAR_ACTIONS.zip',
                            alias_catalog['provider_alias_source']['selected_row_sha256'])
    if hasattr(codec, 'parent_outer_sha256'):
        need(cp['sha256'] == codec.parent_outer_sha256, 'OWN_CASH_EXACT_CURRENT_PARENT_OUTER')
        held = [[dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
                 for _, e in sorted(cp['run']['state']['wealth_core']['episodes'].items(), key=lambda item: int(item[0]))
                 if e['security_id'] == t['security_id']] for t in terms]
        need(held == [codec.parent_positions], 'OWN_CASH_CURRENT_PARENT_POSITION_SCOPE')
    ordinary_components = []
    inherited_ordinary = []
    ordinary = original_ordinary_selection(arm, cp['source_cursor'])
    if ordinary is not None:
        original_codec, original_catalog, original_terms = ordinary
        need(source_root is not None, 'FUTURE_ORIGINAL_ORDINARY_EXPLICIT_REPAIR_ROOT')
        original_terms, inherited_ordinary = remaining_ordinary_terms(cp, original_terms, source_root)
        if catalog != original_catalog:
            terms = merge_selected_terms(terms, original_terms)
        else:
            terms = original_terms
        original_sources = original_codec.ordinary_sources if hasattr(original_codec, 'ordinary_sources') else [original_codec.ordinary_source]
        for source in original_sources:
            if source not in ordinary_components:
                ordinary_components.append(deepcopy(source))
    delivery = original_delivery_selection(arm, cp['source_cursor'])
    if delivery is not None:
        delivery_codec, delivery_catalog, delivery_terms = delivery
        need(source_root is not None, 'FUTURE_ORIGINAL_DELIVERY_EXPLICIT_REPAIR_ROOT')
        delivery_terms, inherited = remaining_ordinary_terms(cp, delivery_terms, source_root)
        inherited_ordinary.extend(inherited)
        terms = (merge_selected_terms(terms, delivery_terms)
                 if catalog != delivery_catalog or ordinary is not None else delivery_terms)
        delivery_sources = (delivery_codec.ordinary_sources if hasattr(delivery_codec, 'ordinary_sources')
                            else [delivery_codec.ordinary_source])
        for source in delivery_sources:
            if source not in ordinary_components:
                ordinary_components.append(deepcopy(source))
    supplement, components = supplemental_selection(arm, cp['source_cursor'])
    if supplement:
        need(source_root is not None, 'FUTURE_SUPPLEMENT_EXPLICIT_REPAIR_ROOT')
        supplement, inherited = remaining_ordinary_terms(cp, supplement, source_root)
        inherited_ordinary.extend(inherited)
        terms = merge_selected_terms(terms, supplement)
        for source in components:
            if source not in ordinary_components:
                ordinary_components.append(deepcopy(source))
    own_terms, own_sources = qualified_own_batch_selection(cp, arm)
    if own_terms:
        need(source_root is not None, 'FUTURE_OWN_BATCH_EXPLICIT_REPAIR_ROOT')
        own_terms, inherited = remaining_ordinary_terms(cp, own_terms, source_root)
        inherited_ordinary.extend(inherited)
        terms = merge_selected_terms(terms, own_terms)
        for source in own_sources:
            if source not in ordinary_components:
                ordinary_components.append(deepcopy(source))
    contracts, contract_sources = contractual_delivery_selection(cp, arm)
    if contracts:
        terms = merge_selected_terms(terms, contracts)
        for source in contract_sources:
            need(source not in ordinary_components, 'FUTURE_CONTRACT_UNIQUE_SOURCE_COMPONENT')
            ordinary_components.append(deepcopy(source))
    suppressions(cp, terms)
    actions = inputs.load_actions(Path('/frozen/bundle'))
    if ordinary_components or any(t.get('recognition_rule') in (NEXT_COMPLETION, SOURCE_CLOSE, RESEARCH_UNHELD_CASH, RESEARCH_CASH, RESEARCH_MIXED, RESEARCH_TENDER, RESEARCH_SOURCE_EXIT, PREOPEN_STOCK, PRIOR_STOCK) for t in terms):
        from research.pooled_input_support.bundle import axis
        dates = axis()
        for t in terms:
            completion_session(t, dates)
            if t.get('recognition_rule') == SOURCE_CLOSE:
                need(t['added']['session'] in dates, 'OWN_INPUT_CLOSING_SOURCE_DATE_ON_ACTUAL_AXIS')
        terms = [ordinary_term_dates(t, dates)
                 if 'original_ordinary_source' in t and 'identity_witness' not in t else t for t in terms]
    wanted = {}
    ordinary_rows = {}
    delivery_rows = {}
    for t in terms:
        native, = [v for v in actions.terminal.get(t['native_session'], ()) if v.security_id == t['security_id']]
        need(digest(asdict(native)) == t['native_term_sha256'] and not native.completeness(0)[0],
             'FUTURE_EXACT_INCOMPLETE_FROZEN_NATIVE')
        other = [v for v in actions.terminal.get(t['added']['session'], ()) if v.security_id == t['security_id']]
        need(other == [native] if t['native_session'] == t['added']['session'] else not other,
             'FUTURE_NO_CONFLICTING_EFFECTIVE_TERM')
        if 'original_ordinary_source' in t and 'identity_witness' not in t:
            key = t['ordinary_identity_session'], t['security_id']
            need(key not in wanted, 'FUTURE_UNIQUE_DECLARED_WITNESS')
            wanted[key] = None
            ordinary_rows[key] = t
            if t['added']['kind'] in ('CASH_PLUS_STOCK', 'CONVERSION'):
                proxy = t['proxy']
                key = proxy['session'], proxy['security_id']
                need(key not in wanted, 'FUTURE_UNIQUE_DECLARED_DELIVERY_WITNESS')
                wanted[key] = None
                delivery_rows[key] = t
            continue
        for w in (t['identity_witness'], *([t['delivered_identity_witness']] if 'delivered_identity_witness' in t else [])):
            key = w['session'], w['security_id']
            need(key not in wanted, 'FUTURE_UNIQUE_DECLARED_WITNESS')
            wanted[key] = w
    seen = {}
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for year in sorted({day[:4] for day, _ in wanted}):
            for row in inputs._archive_rows(archive, 'observations-' + year + '.csv.gz'):
                key = row['session'], row['security_id']
                if key not in wanted:
                    continue
                need(key not in seen, 'FUTURE_UNIQUE_ACTUAL_WITNESS')
                if key in ordinary_rows:
                    term = ordinary_rows[key]
                    term['identity_witness'] = ordinary_identity(term, row)
                    wanted[key] = term['identity_witness']
                if key in delivery_rows:
                    term = delivery_rows[key]
                    term['delivered_identity_witness'] = ordinary_delivery_identity(term, row)
                    wanted[key] = term['delivered_identity_witness']
                require_witness(row, wanted[key])
                seen[key] = row
    need(set(seen) == set(wanted), 'FUTURE_ALL_SELECTED_NATIVE_AND_DELIVERY_WITNESSES')
    for term in terms:
        if term.get('recognition_rule') == RESEARCH_SOURCE_EXIT:
            witness = term['identity_witness']
            source_exit_quote(term, seen[witness['session'], witness['security_id']])
    delivered = {}
    for t in terms:
        if 'delivered_identity_witness' not in t:
            continue
        w = t['delivered_identity_witness']
        row = seen[w['session'], w['security_id']]
        if 'original_contract_source' in t:
            t['added'] = contractual_delivery_addition(t, row)
        else:
            price = float(row['raw_open'])
            need(math.isfinite(price) and price > 0, 'FUTURE_POSITIVE_DECLARED_RAW_OPEN_CIL_PROXY')
            t['added']['cash_in_lieu_price_per_delivered_share'] = price
        delivered[t['security_id']] = row
    material = dict(schema=REFERENCE, arm=arm, catalog=catalog, catalog_sha256=codec.catalog_sha,
        original_validator_sha256=codec.compiler_sha, selector_sha256=sha(Path(__file__).read_bytes()),
        parent_outer_sha256=cp['sha256'], terms=terms,
        cil_convention=('PER_TERM_DECLARED_ORIGINAL_CONTRACT_OR_RESEARCH_PROXY'
                        if contracts else codec.catalog.get('cil_convention', CIL)) if delivered else None,
        native_and_delivery_witnesses_verified=len(seen),
        consumed_native_preserved=[t['security_id'] for t in terms if t['native_session'] <= cp['source_cursor']],
        financial_source_changed=False, provider_metadata_upgraded=False)
    if hasattr(codec, 'composition'):
        material['composition'] = deepcopy(codec.composition)
    if ordinary_components:
        material['ordinary_components'] = ordinary_components
        material['inherited_ordinary_terms'] = inherited_ordinary
    if hasattr(codec, 'validator_description'):
        material['original_validator_description'] = codec.validator_description
    if aliases is not None:
        material['original_alias_source'] = deepcopy(alias_catalog['provider_alias_source'])
        material['verified_alias_rows_sha256'] = digest(aliases)
    return material, delivered, actions


def document(cp, material, hydrated_sha):
    if 'composition' in material:
        manifest = material['composition']
        need(manifest['schema'] == COMPOSITION and digest(manifest) == material['catalog_sha256']
             and digest([{v['validator_file']: v['validator_sha256']} for v in manifest['sources']])
                 == material['original_validator_sha256'], 'FUTURE_EXACT_COMPOSITION_EVIDENCE_DIGESTS')
        evidence = [dict(reference=REFERENCE + '/composition',
                        description='Ordered manifest of independently validated original source catalogs.',
                        sha256=digest(manifest))]
        for source in manifest['sources']:
            evidence.extend(dict(reference=REFERENCE + '/' + source[file], description=description, sha256=source[value])
                for file, value, description in (
                    ('catalog_file', 'catalog_sha256', 'Unchanged literal source catalog.'),
                    ('validator_file', 'validator_sha256', 'Unchanged original literal validator.')))
    else:
        evidence = [dict(reference=REFERENCE + '/' + name, description=description, sha256=value)
            for name, description, value in (
                ('catalog', 'Unchanged literal ordinary completion catalog.', material['catalog_sha256']),
                ('validator', material.get('original_validator_description',
                    'Original literal catalog validator; original compiler guard remains intact.'), material['original_validator_sha256']))]
    for source in material.get('ordinary_components', []):
        evidence.extend(dict(reference=REFERENCE + '/' + source[file], description=description, sha256=source[value])
            for file, value, description in (
                ('catalog_file', 'catalog_sha256', 'Unchanged original ordinary cash catalog.'),
                ('validator_file', 'validator_sha256', 'Unchanged original ordinary cash validator.')))
    evidence.extend(dict(reference=REFERENCE + '/' + name, description=description, sha256=value)
        for name, description, value in (
            ('selector', 'Own-parent future-only selected ordinary input.', material['selector_sha256']),
            ('hydrated', 'Actual frozen native and complete identity/delivery witnesses.', hydrated_sha)))
    for t in material['terms']:
        evidence.extend((dict(reference=t['primary_source'], description=t['description'], sha256=None),
            dict(reference=t['timing_source'], description=('Original native-calendar-day unheld composite source clock; no preopen or held completion claim.' if t.get('recognition_rule') == RESEARCH_UNHELD_COMPOSITE else 'Actual mandatory completion; preserve native trading history.'), sha256=None)))
        if t.get('recognition_rule') == RESEARCH_UNHELD_COMPOSITE:
            reference = t['retained_original_composite_input']
            evidence.extend(dict(reference=REFERENCE + '/original-composite/' + reference[k],sha256=reference[h],description='Unchanged original composite legal input or pure input compiler; original book authority excluded.') for k,h in (('input_file','input_sha256'),('compiler_file','compiler_sha256')))
        if 'source_capture' in t:
            retained = t.get('retained_qualified_source')
            source_arm = retained['source_arm'] if retained is not None else t['arm']
            evidence.extend(dict(reference=REFERENCE + '/source-capture/' + source_arm + '/' + name,
                description=('Retained original factual source only; no originating book authority. ' if retained is not None else '')
                    + description, sha256=t['source_capture'][key]) for name, key, description in (
                    ('payload', 'payload_sha256', 'Authenticated frozen source/native payload from the exact own admitted parent.'),
                    ('independent-data-review', 'independent_data_review_sha256', 'Separate DATA review of the complete row/native and admitted parent role.')))
            if retained is not None:
                evidence.append(dict(reference=REFERENCE + '/retained-qualified-source',
                    description='Exact original factual term and closed source generation; state,returns and continuation authority are excluded.',
                    sha256=digest(retained)))
    return dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
        source_evidence=evidence, suppress=suppressions(cp, material['terms']),
        add=[deepcopy(t['added']) for t in material['terms']])


def qualify(cp, material, delivered, actions, loaded, path, out):
    from research.pooled_input_support.adapter import Packet
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.repair import load_repair
    from research.bounded_20y.run import vendor
    from sentinel.controller import terminal_returns
    from system_campaign_sprint_facts import published_packet, qualify_packet_schema
    from system_campaign_2021_completions_facts import notional, require_witness
    qualify_packet_schema(Packet, cp['base']['sources']['research/pooled_input_support/adapter.py'])
    checks = 0
    for t in material['terms']:
        sid = t['security_id']
        bar = vendor(delivered[sid]) if sid in delivered else None
        prior_session = (t['identity_witness']['session'] if t.get('recognition_rule') in (RESEARCH_TENDER, RESEARCH_SOURCE_EXIT)
                         else t['last_trading_session'])
        prior = SimpleNamespace(median5={'selected': [sid]}, feed={'series': {sid: {
            'signal_basis_anchor': (prior_session, 1., 1.)}}}, last_processed_session=prior_session)
        for day in sorted({t['native_session'], t['added']['session']}):
            original = Packet(day, (bar,) if bar and day == t['added']['session'] else (), {}, {}, 1., {},
                              tuple(actions.terminal.get(day, ())), ())
            before = asdict(original)
            fixed = backtest.apply_repair(original, loaded)
            expected = deepcopy(before)
            expected['terminal'] = asdict(fixed)['terminal']
            need(asdict(original) == before and asdict(fixed) == expected,
                 'FUTURE_ONLY_TERMINAL_PACKET_FIELD_CHANGED')
            matches = [v for v in fixed.terminal if v.security_id == sid]
            if day == t['added']['session']:
                need(len(matches) == 1 and asdict(matches[0]) == t['added'] and matches[0].completeness(1)[0],
                     'FUTURE_EXACT_COMPLETE_ORDINARY_TERM')
                values = terminal_returns.values(prior=prior, published=published_packet(fixed))
                need(values[sid] == float(notional(t['added'], bar)), 'FUTURE_EXACT_CANONICAL_CONTROLLER_NOTIONAL')
                if bar:
                    try:
                        terminal_returns.values(prior=prior, published=SimpleNamespace(session=day, bars=(), terminal_events=fixed.terminal))
                    except ValueError as error:
                        need('lacks delivered close' in str(error), 'FUTURE_MISSING_DELIVERY_REFUSAL_REASON')
                    else:
                        raise ValueError('REFUSED_FUTURE_MISSING_DELIVERY_QUOTE_ACCEPTED')
                    try:
                        require_witness({**delivered[sid], 'issuer_id': 'WRONG'}, t['delivered_identity_witness'])
                    except ValueError:
                        pass
                    else:
                        raise ValueError('REFUSED_FUTURE_WRONG_DELIVERY_IDENTITY_ACCEPTED')
            elif day <= cp['source_cursor']:
                need(fixed == original and len(matches) == 1, 'FUTURE_CONSUMED_NATIVE_PACKET_UNCHANGED')
            else:
                need(not matches, 'FUTURE_LAST_NATIVE_TRADING_SESSION_PRESERVED')
            # A same-day native replacement requires this falsifier too.
            if day == t['native_session'] and day > cp['source_cursor']:
                bad = json.loads(path.read_bytes())
                row, = [r for r in bad['suppress'] if r['security_id'] == sid]
                row['term_sha256'] = '0' * 64
                target = out / ('wrong-native-' + t['ticker'] + '.json')
                save(target, bad)
                wrong = load_repair(target, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
                try:
                    backtest.apply_repair(original, wrong)
                except ValueError as error:
                    need(str(error).startswith('suppressed original terminal differs:'), 'FUTURE_NATIVE_PREIMAGE_REFUSAL_REASON')
                else:
                    raise ValueError('REFUSED_FUTURE_WRONG_NATIVE_ACCEPTED')
            checks += 1
        # The original canonical incomplete-term guard must still refuse.
        native = Packet(t['native_session'], (), {}, {}, 1., {}, tuple(actions.terminal.get(t['native_session'], ())), ())
        day = t['identity_witness']['session']
        native_prior = SimpleNamespace(median5={'selected': [sid]}, feed={'series': {sid: {
            'signal_basis_anchor': (day, 1., 1.)}}}, last_processed_session=day)
        try:
            terminal_returns.values(prior=native_prior, published=published_packet(native))
        except ValueError as error:
            need('incomplete leadership cash terminal' in str(error), 'FUTURE_ORIGINAL_INCOMPLETE_GUARD_REASON')
        else:
            raise ValueError('REFUSED_FUTURE_ORIGINAL_INCOMPLETE_GUARD_MISSING')
    for cursor, predecessor in ((cp['source_cursor'], '0' * 64),
                                (loaded.earliest_affected_session, cp['run']['checkpoint_sha256'])):
        try:
            load_repair(path, resume_session=cursor, predecessor_checkpoint_sha256=predecessor)
        except ValueError:
            pass
        else:
            raise ValueError('REFUSED_FUTURE_ORDINARY_PARSER_FALSIFIER_ACCEPTED')
    save(out / 'future-input-qualification.json', dict(passed=True, packet_checks=checks,
        only_terminal_field_changed=True, complete_terms_and_canonical_notional_verified=True,
        original_incomplete_guard_retained=True, wrong_predecessor_and_consumed_date_refused=True,
        wrong_native_and_delivery_witness_refused=True, financial_sessions_advanced=0))


def prepare(cp, out, arm):
    from system_campaign_financial_compound_dispatch import selected
    compound = selected(cp, arm)
    if compound is not None:
        return compound.prepare(cp, out, arm)
    material, delivered, actions = hydrate(cp, arm, source_root=out)
    hydrated = out / hydration_name(cp)
    save(hydrated, material)
    path = out / OVERLAY
    from system_campaign_financial_projection import prepare_overlay
    save(path, prepare_overlay(cp, out, arm, document(cp, material, sha(hydrated.read_bytes()))))
    scopes = source_scopes(cp, material, sha(path.read_bytes()), sha(hydrated.read_bytes()))
    if scopes:
        save(out / SOURCE_SCOPES, scopes)
    from research.pooled_vacancy_funding.repair import load_repair
    loaded = load_repair(path, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    qualify(cp, material, delivered, actions, loaded, path, out)
    return path, loaded


def review_input(cp, evidence, arm):
    from system_campaign_financial_compound_dispatch import selected
    compound = selected(cp, arm)
    if compound is not None:
        return compound.review(cp, evidence, arm)
    material, _, _ = hydrate(cp, arm, source_root=evidence)
    hydrated = evidence / hydration_name(cp)
    from system_campaign_financial_projection import review_overlay
    need(json.loads(hydrated.read_bytes()) == material
         and json.loads((evidence / OVERLAY).read_bytes()) == review_overlay(
             cp, evidence, arm, document(cp, material, sha(hydrated.read_bytes()))),
         'FUTURE_INDEPENDENT_RECONSTRUCTION_OF_COMPLETE_SELECTED_INPUT')
    scopes = source_scopes(cp, material, sha((evidence / OVERLAY).read_bytes()), sha(hydrated.read_bytes()))
    if scopes:
        need(digest(json.loads((evidence / SOURCE_SCOPES).read_bytes())) == digest(scopes),
             'FUTURE_INDEPENDENT_EXACT_SOURCE_ONLY_SCOPE')
    return min(r['session'] for field in ('suppress', 'add') for r in json.loads((evidence / OVERLAY).read_bytes())[field])


def hydration_name(cp):
    value = cp['sha256']
    need(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
         'FUTURE_HYDRATION_EXACT_PARENT_HASH')
    return HYDRATED.removesuffix('.json') + '-' + value + '.json'


def source_scopes(cp, material, overlay_sha, hydrated_sha):
    from system_campaign_financial_partial import root_spec
    expected = [t for t in selected(material['arm'], cursor=cp['source_cursor'])[2]
                if t.get('recognition_rule') in (SOURCE_CLOSE, RESEARCH_UNHELD_CASH, RESEARCH_SOURCE_EXIT, RESEARCH_UNHELD_COMPOSITE)]
    actual = [t for t in material['terms'] if t.get('recognition_rule') in (SOURCE_CLOSE, RESEARCH_UNHELD_CASH, RESEARCH_SOURCE_EXIT, RESEARCH_UNHELD_COMPOSITE)]
    need(digest(actual) == digest(expected), 'FUTURE_SOURCE_ONLY_SCOPE_CANNOT_BE_OMITTED_OR_RECLASSIFIED')
    result = []
    for term in actual:
        composite = term['recognition_rule'] == RESEARCH_UNHELD_COMPOSITE
        source_exit = composite or term['recognition_rule'] == RESEARCH_SOURCE_EXIT
        if composite:
            research_original_unheld_composite_term(term)
        elif term['recognition_rule'] == RESEARCH_UNHELD_CASH:
            research_unheld_cash_term(term)
        else:
            (research_source_exit_term if source_exit else source_cash_term)(term)
        parent = root_spec(term['arm'], term['parent_root_admission_sha256'])
        need(cp['sha256'] == term['parent_outer_sha256'] == parent['outer_sha256']
             and material['parent_outer_sha256'] == cp['sha256']
             and material['arm'] == term['arm'] and cp['source_cursor'] == term['parent_cursor']
             and digest(term) == digest(selected(term['arm'], cursor=term['parent_cursor'])[2][0]),
             'FUTURE_SOURCE_ONLY_EXACT_OWN_ADMITTED_PARENT_AND_LITERAL')
        scope_class = OriginalUnheldCompositeSourceScope if composite else NeverHeldSourceExitScope if source_exit else SourceOnlyScope
        extra = dict(source_ticker=term['ticker'], require_never_held=True) if source_exit else {}
        if composite:
            reference = term['retained_original_composite_input']
            extra.update(original_input_schema=reference['schema'],original_input_sha256=reference['input_sha256'],original_compiler_sha256=reference['compiler_sha256'])
            need(term['security_id'] in cp['run']['state']['median5']['selected'], 'COMPOSITE_SCOPE_CURRENT_PARENT_SELECTED_DISCLOSED')
        scope = scope_class.model_validate(dict(schema='research.original-unheld-composite-source-scope/1' if composite else 'research.never-held-source-exit-scope/1' if source_exit
                                               else 'research.unowned-closing-source-scope/1',
            arm=term['arm'], parent_outer_sha256=cp['sha256'],
            parent_root_admission_sha256=term['parent_root_admission_sha256'],
            hydrated_sha256=hydrated_sha, overlay_sha256=overlay_sha,
            terminal_sha256=digest(term['added']), session=term['added']['session'],
            security_id=term['security_id'], source_valuation_phase='CLOSE',
            portfolio_completion_authorized=False, require_unowned_and_unordered=True, **extra))
        serialized = scope.model_dump(by_alias=True)
        if source_exit:
            state = cp['run']['state']
            require_source_scope(state['wealth_core'], state['pending'], state['ledger'], serialized)
        result.append(serialized)
    return result


def require_source_absent(wealth, pending, ledger, sid):
    need(not any(e['security_id'] == sid for e in wealth['episodes'].values())
         and not any(s.get('occupied_by') == sid or s.get('reserved_for') == sid
                     for s in wealth['slots'].values())
         and not any((p['security_id'] if isinstance(p, dict) else p.security_id) == sid for p in pending)
         and not any(sid in wealth.get(key, {}) for key in
                     ('terminal_pending_terms', 'terminal_pending_sessions', 'unresolved_terminals', 'terminal_carry_audit'))
         and not any(r['security_id'] == sid for r in ledger['receivables']),
         'FUTURE_SOURCE_ONLY_ACTUAL_UNOWNED_UNORDERED_NO_CLAIMS')


def mentions_source(value, identities):
    if isinstance(value, dict):
        return any(mentions_source(k, identities) or mentions_source(v, identities) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(mentions_source(v, identities) for v in value)
    return isinstance(value, str) and value in identities


def require_source_scope(wealth, pending, ledger, scope):
    require_source_absent(wealth, pending, ledger, scope['security_id'])
    if scope.get('require_never_held') is True:
        need(not mentions_source(ledger['events'], (scope['security_id'], scope['source_ticker'])),
             'FUTURE_SOURCE_EXIT_NO_HISTORICAL_OWNERSHIP')
    if scope.get('schema') == 'research.original-unheld-composite-source-scope/1':
        require_original_composite_scope(wealth,pending,ledger,scope)


def actual_source_call(frame, kernel_code, prior, published):
    return (frame.f_code is kernel_code and frame.f_locals.get('env') is prior
            and frame.f_locals.get('published') is published)


def actual_source_phase(record, result, scopes):
    for scope in scopes:
        if scope['session'] != record['session']:
            continue
        sid = scope['security_id']
        cash = [v for v in record['cash'] if v['security_id'] == sid and v['actual_context_call'] is True]
        source = [v for v in record['source'] if v['security_id'] == sid and v['actual_context_call'] is True]
        need(record['source_prior_absent'] is True and len(cash) == len(source) == 1
             and cash[0]['source_only_noop'] is True
             and cash[0]['postcondition'] == dict(actual_held=False, quantity=0, nominal_cash=0.),
             'FUTURE_SOURCE_ONLY_ONE_ACTUAL_NOOP_AND_SOURCE_DELEGATION')
        require_source_scope(result.state.wealth_core, result.state.pending, result.state.ledger, scope)


def cash_postcondition(before, after, ledger_before, ledger_after, terms, result):
    sid, price = terms['security_id'], terms['cash_per_share']
    held = [(k, v) for k, v in sorted(before['episodes'].items(), key=lambda x: int(x[0])) if v['security_id'] == sid]
    if not held:
        need(result['reason'] == 'NOT_HELD' and before == after and ledger_before == ledger_after,
             'FUTURE_UNHELD_CASH_EXACT_NOOP')
        return dict(actual_held=False, quantity=0, nominal_cash=0.)
    running = before['cash']
    events = ledger_after['events'][len(ledger_before['events']):]
    need(result['applied'] is True and ledger_after['events'][:len(ledger_before['events'])] == ledger_before['events']
         and len(events) == len(held), 'FUTURE_EXACT_NUMBER_AND_PREFIX_OF_CASH_POSTS')
    for (slot, episode), event in zip(held, events):
        q = episode['current_shares']
        proceeds = q * price
        need(event['event_type'] == 'CASH_MERGER' and event['security_id'] == sid
             and event['price'] == price and event['shares_delta'] == -q and event['cash_delta'] == proceeds
             and event['detail']['shares'] == q and event['detail']['reference'] == terms['reference']
             and event['fees'] == 0. and event['cash_before'] == running and event['cash_after'] == running + proceeds
             and after['slots'][str(slot)]['occupied_by'] is None, 'FUTURE_EXACT_CONTRACTUAL_CASH_OPERATION_ORDER')
        running += proceeds
    need(after['cash'] == running
         and {k: v for k, v in before['episodes'].items() if v['security_id'] != sid} == after['episodes']
         and ledger_before.get('receivables', []) == ledger_after.get('receivables', [])
         and sid not in after.get('terminal_pending_sessions', {}) and sid not in after.get('terminal_pending_terms', {}),
         'FUTURE_CASH_SETTLED_SOURCE_REMOVED_OTHER_EPISODES_RECEIVABLES_UNCHANGED')
    return dict(actual_held=True, quantity=sum(e['current_shares'] for _, e in held),
                nominal_cash=sum(e['current_shares'] * price for _, e in held))


def actual_terminal_call(frame, step_code, state, ledger, session):
    return (frame.f_code is step_code and frame.f_locals.get('state') is state
            and frame.f_locals.get('ledger') is ledger and frame.f_locals.get('session') == session)


def cash_before_v(record, result, sid, quantity, nominal_cash):
    actual = [r for r in record['cash'] if r['actual_context_call'] and r['security_id'] == sid]
    need(len(actual) == 1 and actual[0]['postcondition'] == dict(
             actual_held=True, quantity=quantity, nominal_cash=nominal_cash)
         and record['engine_calls'] > 0 and record['order'].index('CASH:' + sid) < record['order'].index('ENGINE')
         and not any(s == sid for _, s in record['risk'])
         and not any(p['security_id'] == sid for p in result.state.pending),
         'FUTURE_EXACT_CASH_REMOVAL_BEFORE_UNCHANGED_V_LOOP')


def actual_cash_phase(record, result, arm, selected):
    for term in selected:
        if term['session'] != record['session'] or term['kind'] != 'CASH_MERGER':
            continue
        actual = [v for v in record['cash'] if v['security_id'] == term['security_id']
                  and v['actual_context_call'] is True]
        need(len(actual) == 1, 'FUTURE_ONE_SELECTED_CASH_CALL_IN_ACTUAL_CANONICAL_STEP')
        proof = actual[0]['postcondition']
        if arm == 'P10' and proof['actual_held']:
            cash_before_v(record, result, term['security_id'], proof['quantity'], proof['nominal_cash'])


def actual_stock_phase(record, selected):
    for term in selected:
        if term['session'] != record['session'] or term['kind'] != 'CASH_PLUS_STOCK':
            continue
        actual = [v for v in record['stock'] if v['security_id'] == term['security_id']
                  and v['actual_context_call'] is True]
        need(len(actual) == 1 and (actual[0]['applied'] is True or (
             actual[0]['applied'] is False and actual[0].get('unheld_noop') is True
             and actual[0].get('postcondition') == dict(actual_held=False, quantity=0, nominal_cash=0.))),
             'FUTURE_ONE_SELECTED_APPLIED_STOCK_CALL_IN_ACTUAL_CANONICAL_STEP')


def unheld_stock_postcondition(before, after, ledger_before, ledger_after, pending, terms, result, phase):
    sid = terms['security_id']
    require_source_absent(before, pending, ledger_before, sid)
    require_source_absent(after, pending, ledger_after, sid)
    need(phase == 'OPEN' and result.get('applied') is False and result.get('reason') == 'NOT_HELD'
         and before == after and ledger_before == ledger_after,
         'FUTURE_UNHELD_STOCK_EXACT_CANONICAL_NOOP')
    return dict(actual_held=False, quantity=0, nominal_cash=0.)


def risk_diagnostic_value(value):
    """Record primitive call data only; never call a financial serialization API."""
    if is_dataclass(value) and not isinstance(value, type):
        return risk_diagnostic_value(asdict(value))
    if isinstance(value, BaseModel):
        return risk_diagnostic_value(vars(value))
    if isinstance(value, dict):
        return {str(k): risk_diagnostic_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [risk_diagnostic_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return dict(nonfinite_float=str(value))
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return dict(python_type=type(value).__name__)


class ActualEvents:
    """Delegate unchanged canonical calls; check postconditions before journal commit."""
    def __init__(self, out, arm, *, cp=None):
        self.out, self.arm = out, arm
        self.terms = {(t['session'], t['security_id']): t for t in json.loads((out / OVERLAY).read_bytes())['add']}
        self.scopes = []
        if cp is not None:
            material_path = out / hydration_name(cp)
            material = json.loads(material_path.read_bytes())
            need(material['arm'] == arm, 'FUTURE_ACTUAL_OWN_MATERIAL_ARM')
            self.scopes = source_scopes(cp, material, sha((out / OVERLAY).read_bytes()), sha(material_path.read_bytes()))
            if self.scopes:
                need(digest(json.loads((out / SOURCE_SCOPES).read_bytes())) == digest(self.scopes)
                     and all(self.terms.get((s['session'], s['security_id'])) is not None
                             and digest(self.terms[s['session'], s['security_id']]) == s['terminal_sha256']
                             for s in self.scopes), 'FUTURE_ACTUAL_EXACT_BOUND_SOURCE_ONLY_SCOPE')
        else:
            # Empty synthetic observers need no canonical parent. Any real input does.
            need(not self.terms, 'FUTURE_ACTUAL_INPUT_REQUIRES_EXPLICIT_OWN_PARENT')
        self.saved, self.current = [], None

    def patch(self, owner, name, replacement):
        old = getattr(owner, name)
        self.saved.append((owner, name, old))
        setattr(owner, name, replacement)
        return old

    def __enter__(self):
        hosted()
        from research.pooled_vacancy_funding import runtime
        from stock_strategy_shared.wealth_core import terminal, adapter
        # actual_parent already verified the entire own canonical source map.
        self.step_code = adapter.step_session.__code__
        self.advance_original = self.patch(runtime, 'advance', self.advance)
        self.terminal_original = self.patch(terminal, 'apply_terminal', self.terminal)
        if self.scopes:
            from sentinel.core import kernel
            from sentinel.controller import terminal_returns
            self.kernel_code = kernel.advance_session.__code__
            self.source_original = self.patch(terminal_returns, 'values', self.source_values)
        if self.arm == 'P10':
            from stock_strategy_shared.wealth_core import capital_risk
            self.decide_original = self.patch(adapter, 'decide', self.decide)
            self.risk_original = self.patch(capital_risk, 'volatility_stop', self.risk)
        elif self.arm == 'P11':
            from stock_strategy_shared.wealth_core import capital_risk
            self.risk_original = self.patch(capital_risk, 'volatility_stop', self.risk_refusal)
        return self

    def __exit__(self, *args):
        for owner, name, old in reversed(self.saved):
            setattr(owner, name, old)

    def risk_refusal(self, episode, *args, **kwargs):
        try:
            return self.risk_original(episode, *args, **kwargs)
        except ValueError as error:
            try:
                save(self.out / 'risk-refusal.json', dict(
                    schema='research.original-risk-call-refusal-diagnostic/1',
                    session=kwargs.get('session'), error=str(error),
                    episode=risk_diagnostic_value(episode), bars=risk_diagnostic_value(kwargs.get('bars')),
                    configuration=risk_diagnostic_value(kwargs.get('cfg')),
                    function_source_sha256=sha(Path(self.risk_original.__code__.co_filename).read_bytes()),
                    financial_source_changed=False, decision_overridden=False,
                    financial_session_committed=False, financial_authority=False))
            except Exception:
                # Observation cannot replace or suppress the original refusal.
                pass
            raise

    def terminal(self, state, terms, **kwargs):
        key = terms.session, terms.security_id
        if self.current is None or key not in self.terms or terms.kind not in ('CASH_MERGER', 'CASH_PLUS_STOCK'):
            return self.terminal_original(state, terms, **kwargs)
        before, ledger = deepcopy(state.to_dict()), deepcopy(kwargs['ledger'].to_dict())
        caller = inspect.currentframe().f_back
        actual = actual_terminal_call(caller, self.step_code, state, kwargs['ledger'], terms.session)
        need(asdict(terms) == self.terms[key], 'FUTURE_ACTUAL_TERMS_EXACT_SELECTED_CONTRACT')
        scope = next((s for s in self.scopes if (s['session'], s['security_id']) == key), None)
        scoped = scope is not None
        if scoped:
            need(actual and self.current['source_prior_absent'] is True,
                 'FUTURE_SOURCE_ONLY_ACTUAL_ADAPTER_CALL_REQUIRED')
            require_source_scope(before, caller.f_locals['pending'], ledger, scope)
        result = self.terminal_original(state, terms, **kwargs)
        if terms.kind == 'CASH_PLUS_STOCK':
            after, ledger_after = state.to_dict(), kwargs['ledger'].to_dict()
            if not any(e['security_id'] == terms.security_id for e in before['episodes'].values()):
                need(actual, 'FUTURE_UNHELD_STOCK_ACTUAL_CANONICAL_CALL')
                proof = unheld_stock_postcondition(before, after, ledger, ledger_after,
                    caller.f_locals['pending'], asdict(terms), result, kwargs.get('phase', 'OPEN'))
                self.current['stock'].append(dict(session=terms.session, security_id=terms.security_id,
                    actual_context_call=actual, applied=False, unheld_noop=True, postcondition=proof,
                    result=deepcopy(result), before_state_sha256=digest(before), after_state_sha256=digest(after),
                    before_ledger_sha256=digest(ledger), after_ledger_sha256=digest(ledger_after)))
                return result
            need(kwargs.get('phase', 'OPEN') == 'OPEN' and result.get('applied') is True
                 and ledger_after['events'][:len(ledger['events'])] == ledger['events']
                 and not any(e['security_id'] == terms.security_id for e in after['episodes'].values())
                 and terms.security_id not in after.get('terminal_pending_terms', {})
                 and terms.security_id not in after.get('terminal_pending_sessions', {}),
                 'FUTURE_ACTUAL_SELECTED_STOCK_APPLIED_SOURCE_CLEARED')
            self.current['stock'].append(dict(session=terms.session, security_id=terms.security_id,
                actual_context_call=actual, applied=True, result=deepcopy(result),
                before_state_sha256=digest(before), after_state_sha256=digest(after),
                before_ledger_sha256=digest(ledger), after_ledger_sha256=digest(ledger_after)))
            return result
        proof = cash_postcondition(before, state.to_dict(), ledger, kwargs['ledger'].to_dict(), asdict(terms), result)
        need(kwargs.get('phase', 'OPEN') == 'OPEN', 'FUTURE_ACTUAL_CASH_OPEN_PHASE')
        if scoped:
            need(result.get('applied') is False and result.get('reason') == 'NOT_HELD'
                 and before == state.to_dict() and ledger == kwargs['ledger'].to_dict(),
                 'FUTURE_SOURCE_ONLY_CANONICAL_TERMINAL_EXACT_NOOP')
        self.current['cash'].append(dict(session=terms.session, security_id=terms.security_id,
            actual_context_call=actual, postcondition=proof, source_only_noop=scoped))
        if actual:
            self.current['order'].append('CASH:' + terms.security_id)
        return result

    def source_values(self, *, prior, published):
        scopes = [s for s in self.scopes if s['session'] == published.session]
        if not scopes:
            return self.source_original(prior=prior, published=published)
        need(self.current is not None and self.current['session'] == published.session
             and self.current['source_prior_absent'] is True
             and actual_source_call(inspect.currentframe().f_back, self.kernel_code, prior, published),
             'FUTURE_SOURCE_ONLY_ACTUAL_KERNEL_CALL_REQUIRED')
        before = deepcopy((prior.wealth_core, prior.pending, prior.ledger))
        for scope in scopes:
            require_source_scope(*before, scope)
        result = self.source_original(prior=prior, published=published)
        need(before == (prior.wealth_core, prior.pending, prior.ledger),
             'FUTURE_SOURCE_ONLY_ORIGINAL_RETURN_FUNCTION_READONLY')
        for scope in scopes:
            sid = scope['security_id']
            need(sid not in prior.median5['selected'] or sid in result,
                 'FUTURE_SOURCE_ONLY_SELECTED_RETURN_SUPPLIED_BY_ORIGINAL')
            self.current['source'].append(dict(security_id=sid, actual_context_call=True,
                original_function_delegated=True, source_value_returned=sid in result,
                portfolio_completion_authorized=False, scope_sha256=digest(scope)))
        return result

    def decide(self, **kwargs):
        if self.current is None:
            return self.decide_original(**kwargs)
        eligible = [(int(k), v['security_id']) for k, v in sorted(kwargs['state'].to_dict()['episodes'].items(), key=lambda x: int(x[0])) if not v['exit_pending']]
        offset = len(self.current['risk'])
        self.current['order'].append('ENGINE')
        result = self.decide_original(**kwargs)
        need(self.current['risk'][offset:] == eligible, 'FUTURE_ALL_SURVIVING_EPISODES_TRAVERSE_ORIGINAL_V_GUARD')
        self.current['engine_calls'] += 1
        return result

    def risk(self, ep, *, bars, session, cfg):
        try:
            result = self.risk_original(ep, bars=bars, session=session, cfg=cfg)
        except BaseException as error:
            if self.current is not None:
                self.current['failed_risk_call'] = dict(slot_id=ep.slot_id, security_id=ep.security_id,
                                                       session=session, error=str(error))
            raise
        if self.current is not None:
            from sentinel.feed.calendar import previous_sessions
            bar = next((b for b in bars if b.security_id == ep.security_id), None)
            need(cfg.economic_profile == 'wealth-core-capital-risk-v-v1' and bar is not None
                 and list(bar.signal_sessions or ()) == previous_sessions(session, 21) and len(bar.closes) >= 21,
                 'FUTURE_ORIGINAL_V21_CAUSAL_AXIS')
            self.current['risk'].append((ep.slot_id, ep.security_id))
        return result

    def advance(self, run, publication):
        need(self.current is None, 'FUTURE_SINGLE_ACTUAL_ADVANCE')
        record = self.current = dict(session=publication.session, cash=[], stock=[], risk=[], order=[], engine_calls=0,
                                     source=[], source_prior_absent=False)
        try:
            for scope in self.scopes:
                if scope['session'] == publication.session:
                    require_source_scope(run.state.wealth_core, run.state.pending, run.state.ledger, scope)
                    record['source_prior_absent'] = True
            result = self.advance_original(run, publication)
            actual_cash_phase(record, result, self.arm, self.terms.values())
            actual_stock_phase(record, self.terms.values())
            actual_source_phase(record, result, self.scopes)
            if self.arm == 'P10':
                if publication.session == '2020-10-01':
                    cash_before_v(record, result, '510659411298086546', 101, 5302.5)
                elif publication.session == '2022-02-23':
                    cash_before_v(record, result, '576374012507208201', 69, 5468.25)
            if record['cash'] or publication.session in {d for d, _ in self.terms}:
                save(self.out / ('actual-future-event-' + publication.session + '.json'), dict(record, passed=True, financial_source_changed=False))
            return result
        except BaseException as error:
            save(self.out / 'actual-future-event-refusal.json', dict(record, passed=False, error=str(error), financial_source_changed=False))
            raise
        finally:
            self.current = None


def aggregate_original_ordinary(arm, cursor, sources):
    terms, records = [], []
    for codec, catalog, source, cash in sources:
        declared = ORIGINAL_ORDINARY_SUBSETS[arm, cursor, catalog]
        need(type(declared) is tuple and declared and len(set(declared)) == len(declared),
             'FUTURE_ORIGINAL_CASH_UNIQUE_EXPLICIT_BATCH_SUBSET')
        selected_terms = [deepcopy(t) for t in cash if t['ticker'] in declared]
        need(tuple(t['ticker'] for t in selected_terms) == declared
             and all(cursor < t['native_session'] <= t['added']['session'] for t in selected_terms),
             'FUTURE_ORIGINAL_CASH_EXACT_UNCONSUMED_BATCH_SUBSET')
        source = dict(source, selected_tickers=list(declared))
        need(not any(r['catalog_file'] == catalog or r['validator_file'] == source['validator_file'] for r in records),
             'FUTURE_ORIGINAL_CASH_UNIQUE_AGGREGATE_SOURCES')
        for term in selected_terms:
            term['original_ordinary_source'] = dict(source, term_sha256=digest(term))
            term['timing_source'] = term['primary_source']
        terms = merge_selected_terms(terms, selected_terms)
        records.append(source)
    manifest = dict(schema=COMPOSITION, sources=records)
    codec = SimpleNamespace(catalog=dict(terms=deepcopy(terms)), catalog_sha=digest(manifest),
        compiler_sha=digest([{r['validator_file']: r['validator_sha256']} for r in records]),
        ordinary_sources=records, composition=manifest)
    return codec, 'EXPLICIT_ORDERED_ORIGINAL_CASH_COMPOSITION', terms


def qualified_own_batch_selection(cp, arm):
    from system_campaign_financial_uncertainty import own_initial_for_parent, OWN_POLICY_SHA, OWN_POLICY_CATALOG
    selected = own_initial_for_parent(cp, arm)
    if selected is None:
        return [], []
    phase, payload = selected
    raw = (HERE / OWN_CASH_CATALOG).read_bytes()
    catalog = json.loads(raw)
    records = phase['ordinary_model_terms']
    need(records and len({r['term']['security_id'] for r in records}) == len(records),
         'FUTURE_OWN_BATCH_UNIQUE_QUALIFIED_MODEL_TERMS')
    source = dict(catalog_file=OWN_CASH_CATALOG, catalog_sha256=sha(raw),
        validator_file=Path(__file__).name, validator_sha256=sha(Path(__file__).read_bytes()),
        qualified_input_catalog=OWN_POLICY_CATALOG, qualified_input_sha256=OWN_POLICY_SHA,
        selected_tickers=[r['term']['ticker'] for r in records],
        original_generation_term_pins=[dict(generation_sha256=r['original_generation_sha256'],
            generation_length=r['original_generation_length'], term_sha256=r['original_term_sha256']) for r in records])
    terms = []
    for plan in records:
        prefix = dict(deepcopy(catalog), terms=deepcopy(catalog['terms'][:plan['original_generation_length']]))
        need(sha((json.dumps(prefix, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()) == plan['original_generation_sha256'],
             'FUTURE_OWN_BATCH_EXACT_ORIGINAL_CATALOG_GENERATION')
        original, = [t for t in prefix['terms'] if t['arm'] == plan['original_arm'] and t['parent_cursor'] == plan['original_cursor']
                     and digest(t) == plan['original_term_sha256']]
        term = deepcopy(plan['term'])
        permitted = {'arm', 'parent_cursor', 'parent_outer_sha256', 'parent_root_admission_sha256',
                     'parent_positions', 'source_capture', 'description', 'added'}
        need(term.keys() == original.keys()
             and all(term[k] == v for k, v in original.items() if k not in permitted)
             and {k: v for k, v in term['added'].items() if k != 'reference'}
                 == {k: v for k, v in original['added'].items() if k != 'reference'}
             and term['arm'] == arm and term['parent_outer_sha256'] == cp['sha256']
             and term['parent_cursor'] == cp['source_cursor']
             and term['parent_root_admission_sha256'] == phase['root_admission_sha256'],
             'FUTURE_OWN_BATCH_ONLY_EXACT_OWN_SOURCE_REBINDING_NO_ECONOMIC_CHANGE')
        native, = [t for t in payload['terms'] if t['native_term']['security_id'] == term['security_id']]
        expected_capture = dict(phase['source_clock'], payload_sha256=phase['source_payload_sha256'],
            scope_sha256=phase['source_scope_sha256'], independent_data_review_sha256=phase['source_review_sha256'],
            independent_qualification_sha256=phase['source_qualification_sha256'])
        need(term['identity_witness'] == native['identity_witness'] and term['native'] == native['native_term']
             and term['native_term_sha256'] == digest(native['native_term'])
             and term['parent_positions'] == native['parent_positions']
             and term['source_capture'] == expected_capture,
             'FUTURE_OWN_BATCH_EXACT_FRESH_NATIVE_IDENTITY_ROLE_AND_DATA_CLOCK')
        if 'delivered_identity_witness' in term:
            child, = [t for t in payload['additional_rows'] if t['identity_witness'] == term['delivered_identity_witness']]
            need(child['identity_witness']['source_observation_sha256'] == term['proxy']['source_observation_sha256'],
                 'FUTURE_OWN_BATCH_EXACT_DELIVERED_RAW_ROW_PROXY')
        if term['recognition_rule'] == RESEARCH_MIXED:
            term = research_mixed_term(term)
        elif term['recognition_rule'] == RESEARCH_CASH:
            research_cash_term(term)
        else:
            term = selected_stock_term(term)
        term['original_ordinary_source'] = dict(source, term_sha256=plan['original_term_sha256'])
        terms.append(term)
    return terms, [source]
