"""Immutable original provider source attachment; no root or financial authority."""
import io,json,zipfile
from pathlib import Path
from system_campaign_facts import digest,sha
from full_system_benchmark import need
import system_campaign_wwe_facts as facts
HERE=Path(__file__).parent
ASSET='P06-WWE-original-provider-SHARADAR_ACTIONS.zip'
ASSET_SHA='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02'
ASSET_BYTES=9855560
PROTOCOL='P06-WWE-source-asset-protocol.json'
PROTOCOL_SHA='0d1ad5b5cf3284d1441938019454d62bcd80feae7d698f7bddce22a51d38e4e8'
FIELD='selected_p06_WWE_immutable_source_assets'
def protocol():
    raw=(HERE/PROTOCOL).read_bytes();need(sha(raw)==PROTOCOL_SHA,'P06_WWE_EXACT_IMMUTABLE_SOURCE_ASSET_PROTOCOL')
    value=json.loads(raw)
    need(value['schema']=='research.P06-WWE-immutable-source-asset-protocol/1'
        and (value['asset_file'],value['asset_bytes'],value['asset_sha256'])==(ASSET,ASSET_BYTES,ASSET_SHA)
        and value['source_role']=='ORIGINAL_PROVIDER_ACTION_PREIMAGES_ONLY'
        and value['target_relative_path']=='provider-source/SHARADAR_ACTIONS.zip'
        and all(value[k] is False for k in ('provider_metadata_upgraded','canonical_financial_source_changed','financial_authority',
            'input_adopted','original_parent_archive_mutated','hosted_source_supply_network_required','root_or_checkpoint_source')),
        'P06_WWE_SOURCE_ASSET_IS_NOT_INPUT_ROOT_OR_METADATA_AUTHORITY')
    return value
def declaration():
    value=protocol()
    return dict(schema='research.P06-WWE-immutable-source-asset-declaration/1',asset_file=ASSET,asset_bytes=ASSET_BYTES,
        asset_sha256=ASSET_SHA,protocol_file=PROTOCOL,protocol_sha256=PROTOCOL_SHA,
        original_git_object=value['original_git_object'],source_only=True,financial_authority=False,root_or_checkpoint_source=False)
def request_binding(request):
    need(request.get(FIELD)=={'P06':declaration()} and request['sources'].get(ASSET)==ASSET_SHA
        and request['sources'].get(PROTOCOL)==PROTOCOL_SHA,'P06_WWE_ONLY_EXPLICIT_PINNED_SOURCE_ASSET_REQUEST')
    return True
def read_asset(driver,request):
    request_binding(request);driver=Path(driver);value=protocol()
    for name,pin in value['exact_original_WWE_sources'].items():
        need(sha((driver/name).read_bytes())==pin,'P06_WWE_ALL_ORIGINAL_FACT_COMPILER_GATE_REVIEW_REGISTRY_BYTES:'+name)
    raw=(driver/ASSET).read_bytes()
    need(len(raw)==ASSET_BYTES and sha(raw)==ASSET_SHA,'P06_WWE_ORIGINAL_SOURCE_BYTES_BEFORE_ZIP_PARSE')
    rows=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            import csv
            with archive.open(name) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream,encoding='utf8',newline='')):
                    if row['date']==facts.NATIVE and 'WWE' in (row['ticker'],row['contraticker']):rows.append(row)
    catalog=facts.validate(json.loads((driver/facts.CATALOG).read_bytes()));term,=catalog['terms']
    facts.stock.require_provider_rows(rows,term)
    need(rows==value['original_provider_rows'],'P06_WWE_ALL_THREE_ORIGINAL_PROVIDER_ROWS_IN_ORIGINAL_ORDER')
    return raw,dict(schema='research.P06-WWE-original-source-asset-review/1',passed=True,source_bytes=len(raw),
        source_sha256=sha(raw),provider_rows=rows,provider_rows_sha256=digest(rows),
        original_parent_archive_mutated=False,canonical_financial_source_changed=False,financial_authority=False,
        input_adopted=False,network_used=False)
def stage_source(driver,out,request):
    """Host only, source-only owned output; old book is not a writable argument."""
    from full_system_core import hosted
    hosted();driver,out=Path(driver),Path(out)
    need(driver.is_dir() and out.is_dir() and not driver.is_symlink() and not out.is_symlink()
        and driver.absolute()==driver.resolve() and out.absolute()==out.resolve()
        and driver.resolve()!=out.resolve() and driver.resolve() not in out.resolve().parents
        and out.resolve() not in driver.resolve().parents,'P06_WWE_DISJOINT_REAL_DRIVER_AND_OWNED_SOURCE_OUTPUT')
    raw,review=read_asset(driver,request)
    folder=out/'provider-source';need(not folder.exists(),'P06_WWE_FRESH_OWNED_PROVIDER_SOURCE_DIRECTORY')
    folder.mkdir();target=folder/'SHARADAR_ACTIONS.zip'
    with target.open('xb') as stream:stream.write(raw)
    need(target.read_bytes()==raw,'P06_WWE_STAGED_SOURCE_EQUALS_IMMUTABLE_ORIGINAL_BYTES')
    return target,review
def source_names():return (Path(__file__).name,ASSET,PROTOCOL,*protocol()['exact_original_WWE_sources'])
