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
COMBINED_PHASES['P07', '2020-03-31'] = (FOLLOWING_PHASES['P07', '2020-03-31'], PLANS['P10'])
SOURCE_WITNESS_SCHEMA = 'research.own-parent-frozen-source-witnesses/1'
SOURCE_WITNESS_PENDING_SCHEMA = 'research.own-parent-frozen-source-witnesses/2'
SOURCE_WITNESS_DISCOVERY_SCHEMA = 'research.own-parent-frozen-source-witnesses/3'
SOURCE_WITNESS_ROW_QUERY_SCHEMA = 'research.own-parent-frozen-source-witnesses/4'
SOURCE_WITNESS_DATE_QUERY_SCHEMA = 'research.own-parent-frozen-source-witnesses/5'
SOURCE_WITNESS_FILE = 'source-witnesses.json'
OWN_CASH_CATALOG = 'system-campaign-selected-own-cash-terminal-facts.json'
OWN_CASH_SHA = 'c2b91afd1a521e14ce0f154b9c43317e6adac4f4a6fc6aca0c1ba42c4ee8889b'
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
NEXT_COMPLETION = 'FIRST_FROZEN_SESSION_AFTER_CONFIRMED_COMPLETION_DATE'
SOURCE_CLOSE = 'CONFIRMED_COMPLETION_CLOSE_UNOWNED_SOURCE_ONLY'
RESEARCH_CASH = 'RESEARCH_COMPLETION_DATE_OPEN_AVAILABILITY'
RESEARCH_MIXED = 'RESEARCH_DAILY_MIXED_CONSIDERATION_OPEN_AVAILABILITY'
RESEARCH_TENDER = 'RESEARCH_ASSUMED_TENDER_PARTICIPATION'
RESEARCH_SOURCE_EXIT = 'UNHELD_SOURCE_EXIT_AT_LAST_RETAINED_RAW_CLOSE_NOT_STATUTORY_CASH'
PREOPEN_STOCK = 'CONFIRMED_PREOPEN_STOCK_ONLY_COMPLETION'
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
SUPPLEMENTAL_PHASES['P11', '2023-06-30'] = (
    ('system_campaign_cash_calendar', 'CashCalendar', 'JSON',
     'system-campaign-h2-2023-cash-calendar-terminal-facts.json',
     '8b461ae3218c30c3aad95721379544261814404d72e908920e1c81e9c0775086',
     '183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f',
     ('DICE','ARNC','FRG','FORG','CFMS','QUOT','RADI')),
)


class ResearchCashAssumption(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.daily-economic-cash-assumption/1'] = Field(alias='schema')
    published_cash_per_share: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+$')]
    recognition_session: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    opening_availability_assumed: Literal[True]
    actual_settlement_claimed: Literal[False]
    settlement_fees: Literal['IGNORED_FOR_RESEARCH']


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
_distribution_scope_raw = (HERE / 'system-campaign-compound-source-witness-scopes.json').read_bytes()
need(sha(_distribution_scope_raw) == '558d3b70ec1ed24ad349ebc1d126f05b40fcb47acb44d690b982c4b382f21925',
     'SOURCE_DISTRIBUTION_EXACT_REGISTERED_SCOPE_CATALOG')
DISTRIBUTION_WITNESS_SCOPES = json.loads(_distribution_scope_raw)['scopes']
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
ACTIVE_WITNESS_SCOPES['P06'] = digest(EXTRA_WITNESS_SCOPES[('P06', '2020-02-28')])
ACTIVE_WITNESS_SCOPES['P11'] = digest(DISTRIBUTION_WITNESS_SCOPES['P11'])
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
        if term['recognition_rule'] == RESEARCH_MIXED:
            research_mixed_term(term)
        elif term['recognition_rule'] == RESEARCH_SOURCE_EXIT:
            research_source_exit_term(term)
        elif term['recognition_rule'] == RESEARCH_TENDER:
            research_tender_term(term)
        elif term['recognition_rule'] == RESEARCH_CASH:
            research_cash_term(term)
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
        declared, = scope['terms']
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
        codec.validator_description = 'Published cash consideration with explicit research opening availability on the completion calendar date; actual settlement and preopen completion are not claimed.'
    elif chosen['recognition_rule'] == NEXT_COMPLETION:
        codec.compiler_sha = sha(Path(__file__).read_bytes())
        codec.validator_description = 'Shared source-bound mandatory cash right with explicit first-session-after-confirmed-completion timing convention.'
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


def research_cash_term(term):
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


def research_mixed_term(term):
    assumption = term['research_assumption']
    model_class = (ResearchExactCashMixedAssumption
                   if assumption.get('schema') == 'research.daily-mixed-consideration-assumption/2'
                   else ResearchMixedAssumption)
    model = model_class.model_validate(assumption)
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
         and a['session'] == model.recognition_session == term['actual_completion_date']
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
        need(dates == sorted(set(dates)) and term['native_session'] in dates
             and dates.index(term['native_session']) + 1 < len(dates)
             and dates[dates.index(term['native_session']) + 1] == term['added']['session'] == term['actual_completion_date'],
             'OWN_INPUT_RESEARCH_MIXED_NEXT_FROZEN_DAILY_BOUNDARY')
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


def selected_stock_term(term):
    """Normalize only a literal ratio, preserving its exact rational value."""
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
        need(selected_terms and all(t['added']['kind'] in ('CASH_MERGER', 'CASH_PLUS_STOCK')
             and cursor < t['native_session'] < t['added']['session'] for t in selected_terms),
             'FUTURE_SUPPLEMENT_ONLY_UNCONSUMED_TERMS')
        source = dict(catalog_file=catalog, catalog_sha256=catalog_sha,
                      validator_file=Path(module.__file__).name, validator_sha256=validator_sha,
                      selected_tickers=list(tickers))
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


def original_delivery_selection(arm, cursor):
    """Future mixed terms from unchanged literal validators; cash selection is separate."""
    import importlib
    for module_name, class_name, catalog, expected_sha in ORIGINAL_DELIVERY_SOURCES.get(arm, ()):
        raw = (HERE / catalog).read_bytes()
        need(sha(raw) == expected_sha, 'FUTURE_ORIGINAL_DELIVERY_CATALOG_BYTES')
        module = importlib.import_module(module_name)
        codec = getattr(module, class_name)(HERE / catalog)
        mixed = [t for t in codec.catalog['terms'] if t['added']['kind'] == 'CASH_PLUS_STOCK']
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
    need(term['added']['kind'] == 'CASH_PLUS_STOCK'
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
        if (len(suppress) == len(added) == 1 and comparison['kind'] == 'CASH_PLUS_STOCK'
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
    if delivery is not None:
        return delivery
    if arm == 'P07':
        need(cursor == '2019-12-31' or (arm, cursor) in SINGLE_PHASES or (arm, cursor) in FOLLOWING_PHASES
             or (arm, cursor) in FUTURE_LITERAL_PHASES,
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
        module, cls, catalog, tickers = {**SINGLE_PHASES, **FOLLOWING_PHASES, **FUTURE_LITERAL_PHASES}.get((arm, cursor), PLANS[arm])
        codec = getattr(importlib.import_module(module), cls)(HERE / catalog)
    terms = catalog_terms(codec, tickers)
    return codec, catalog, terms


def stage_selected_sources(spec, old, out):
    """Host-only bounded fetch of one pinned source; workers remain offline."""
    phase = spec['arm'], spec['selected_session']
    if phase not in SINGLE_PHASES and phase not in FOLLOWING_PHASES:
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
        ordinary_components.append(deepcopy(original_codec.ordinary_source))
    delivery = original_delivery_selection(arm, cp['source_cursor'])
    if delivery is not None:
        delivery_codec, delivery_catalog, delivery_terms = delivery
        need(source_root is not None, 'FUTURE_ORIGINAL_DELIVERY_EXPLICIT_REPAIR_ROOT')
        delivery_terms, inherited = remaining_ordinary_terms(cp, delivery_terms, source_root)
        inherited_ordinary.extend(inherited)
        terms = (merge_selected_terms(terms, delivery_terms)
                 if catalog != delivery_catalog or ordinary is not None else delivery_terms)
        if delivery_codec.ordinary_source not in ordinary_components:
            ordinary_components.append(deepcopy(delivery_codec.ordinary_source))
    supplement, components = supplemental_selection(arm, cp['source_cursor'])
    if supplement:
        need(source_root is not None, 'FUTURE_SUPPLEMENT_EXPLICIT_REPAIR_ROOT')
        supplement, inherited = remaining_ordinary_terms(cp, supplement, source_root)
        inherited_ordinary.extend(inherited)
        terms = merge_selected_terms(terms, supplement)
        for source in components:
            if source not in ordinary_components:
                ordinary_components.append(deepcopy(source))
    suppressions(cp, terms)
    actions = inputs.load_actions(Path('/frozen/bundle'))
    if ordinary_components or any(t.get('recognition_rule') in (NEXT_COMPLETION, SOURCE_CLOSE, RESEARCH_CASH, RESEARCH_MIXED, RESEARCH_TENDER, RESEARCH_SOURCE_EXIT, PREOPEN_STOCK) for t in terms):
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
            if t['added']['kind'] == 'CASH_PLUS_STOCK':
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
        price = float(row['raw_open'])
        need(math.isfinite(price) and price > 0, 'FUTURE_POSITIVE_DECLARED_RAW_OPEN_CIL_PROXY')
        t['added']['cash_in_lieu_price_per_delivered_share'] = price
        delivered[t['security_id']] = row
    material = dict(schema=REFERENCE, arm=arm, catalog=catalog, catalog_sha256=codec.catalog_sha,
        original_validator_sha256=codec.compiler_sha, selector_sha256=sha(Path(__file__).read_bytes()),
        parent_outer_sha256=cp['sha256'], terms=terms,
        cil_convention=codec.catalog.get('cil_convention', CIL) if delivered else None,
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
            dict(reference=t['timing_source'], description='Actual mandatory completion; preserve native trading history.', sha256=None)))
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
                if t.get('recognition_rule') in (SOURCE_CLOSE, RESEARCH_SOURCE_EXIT)]
    actual = [t for t in material['terms'] if t.get('recognition_rule') in (SOURCE_CLOSE, RESEARCH_SOURCE_EXIT)]
    need(digest(actual) == digest(expected), 'FUTURE_SOURCE_ONLY_SCOPE_CANNOT_BE_OMITTED_OR_RECLASSIFIED')
    result = []
    for term in actual:
        source_exit = term['recognition_rule'] == RESEARCH_SOURCE_EXIT
        (research_source_exit_term if source_exit else source_cash_term)(term)
        parent = root_spec(term['arm'], term['parent_root_admission_sha256'])
        need(cp['sha256'] == term['parent_outer_sha256'] == parent['outer_sha256']
             and material['parent_outer_sha256'] == cp['sha256']
             and material['arm'] == term['arm'] and cp['source_cursor'] == term['parent_cursor']
             and digest(term) == digest(selected(term['arm'], cursor=term['parent_cursor'])[2][0]),
             'FUTURE_SOURCE_ONLY_EXACT_OWN_ADMITTED_PARENT_AND_LITERAL')
        scope_class = NeverHeldSourceExitScope if source_exit else SourceOnlyScope
        extra = dict(source_ticker=term['ticker'], require_never_held=True) if source_exit else {}
        scope = scope_class.model_validate(dict(schema='research.never-held-source-exit-scope/1' if source_exit
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
