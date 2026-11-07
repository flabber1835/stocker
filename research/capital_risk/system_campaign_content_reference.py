"""Explicit research parent-content retention; never duplicate an opaque ZIP."""
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator

from full_system_benchmark import need, save
from system_campaign_facts import digest
from system_campaign_uncertainty_input import Digest
from seal import sha256_file

PATH = 'lineage/parent-content-reference.json'
SCHEMA = 'research.system-campaign-parent-content-reference/1'
LIMIT = 512 * 1024**2
Commit = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{40}$')]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)

    @field_validator('*', mode='before')
    @classmethod
    def exact_boolean_literals(cls, value, info):
        if info.field_name.endswith(('_verified', '_included', '_claimed', '_contacted')):
            need(type(value) is bool, 'CONTENT_REFERENCE_EXACT_BOOLEAN_CLAIMS')
        return value


class ArchiveAttestation(StrictRecord):
    schema_id: Literal['research.private-parent-content-archive/1'] = Field(alias='schema')
    run_id: StrictInt = Field(gt=0)
    head: Commit
    artifact_id: StrictInt = Field(gt=0)
    selected_outer_sha256: Digest
    complete_member_index_sha256: Digest
    independent_review_sha256: Digest
    inventory_members: StrictInt = Field(gt=0, lt=5000)
    all_cipher_gcm_inventory_verified: Literal[True]
    all_unique_content_and_older_opaque_evidence_verified: Literal[True]
    raw_outer_transport_zip_copy_claimed: Literal[False]


class ParentReference(StrictRecord):
    schema_id: Literal['research.system-campaign-parent-content-reference/1'] = Field(alias='schema')
    arm: Literal['P02']
    run_id: StrictInt = Field(gt=0)
    head: Commit
    artifact_id: StrictInt = Field(gt=0)
    zip_bytes: StrictInt = Field(gt=0, lt=2 * 1024**3)
    zip_sha256: Digest
    receipt_sha256: Digest
    encrypted_asset_sha256: Digest
    manifest_sha256: Digest
    selected_outer_sha256: Digest
    selected_inner_sha256: Digest
    selected_state_sha256: Digest
    selected_input_sha256: Digest
    selected_file_sha256: Digest
    source_binding_sha256: Digest
    hosted_review_sha256: Digest
    interval_review_sha256: Digest
    parent_spec_sha256: Digest
    complete_journals_sha256: Digest
    complete_repairs_sha256: Digest
    base_sha256: Digest
    archive: ArchiveAttestation
    duplicate_parent_transport_bytes_included: Literal[False]
    new_physical_parent_zip_copy_claimed: Literal[False]
    production_contacted: Literal[False]


def reference(spec):
    """Pure exact metadata; the supplied private attestation was independently made."""
    need(spec['arm'] == 'P02' and spec['stage'] == 'campaign-factual-suffix'
         and spec['receipt_schema'] == 'research.system-p02-uncertainty-suffix-receipt/1'
         and not spec.get('unadvanced_qualification_failure') and not spec.get('review_refusal'),
         'CONTENT_REFERENCE_ONLY_NORMAL_REVIEWED_OWN_P02_PARENT')
    stops = spec['inspections']
    need(set(stops) == {'economic-worker-inspect.json', 'independent-review-stop/worker-inspect.json'}
         and type(stops['economic-worker-inspect.json']['exit_code']) is int
         and stops['economic-worker-inspect.json']['exit_code'] in (0, 1, 2)
         and type(stops['independent-review-stop/worker-inspect.json']['exit_code']) is int
         and stops['independent-review-stop/worker-inspect.json']['exit_code'] == 0,
         'CONTENT_REFERENCE_KNOWN_WORKER_AND_SUCCESSFUL_REVIEW')
    attestation = ArchiveAttestation.model_validate(spec['private_content_archive'])
    need((attestation.run_id, attestation.head, attestation.artifact_id, attestation.selected_outer_sha256)
         == (spec['run_id'], spec['head'], spec['artifact_id'], spec['outer_sha256']),
         'CONTENT_REFERENCE_EXACT_PRIVATE_ARCHIVE_AND_SELECTED_PARENT')
    value = ParentReference.model_validate(dict(schema=SCHEMA, arm='P02',
        run_id=spec['run_id'], head=spec['head'], artifact_id=spec['artifact_id'],
        zip_bytes=spec['zip_bytes'], zip_sha256=spec['zip_sha256'], receipt_sha256=spec['receipt_sha256'],
        encrypted_asset_sha256=spec['encrypted_output']['sha256'],
        manifest_sha256=spec['encrypted_output']['manifest_sha256'],
        selected_outer_sha256=spec['outer_sha256'], selected_inner_sha256=spec['inner_sha256'],
        selected_state_sha256=spec['state_sha256'], selected_input_sha256=spec['input_sha256'],
        selected_file_sha256=spec['selected_file']['sha256'], source_binding_sha256=spec['source_binding_sha256'],
        hosted_review_sha256=spec['review_sha256'], interval_review_sha256=spec['interval_review_sha256'],
        parent_spec_sha256=digest(spec), complete_journals_sha256=digest(spec['journals']),
        complete_repairs_sha256=digest(spec['repairs']), base_sha256=digest(spec['base']),
        archive=attestation, duplicate_parent_transport_bytes_included=False,
        new_physical_parent_zip_copy_claimed=False, production_contacted=False))
    return value.model_dump(by_alias=True)


def preserve(old, out, spec):
    """After actual parent admission, write a reference; alter no old evidence."""
    from probe import check_context
    check_context(os.environ)
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    need(os.name == 'posix' and str(temp) == '/home/runner/work/_temp'
         and old.resolve().is_relative_to(temp) and out.resolve().parent == temp
         and out.name.startswith('p02-'), 'CONTENT_REFERENCE_EXACT_PRIVATE_HOSTED_OUTPUT')
    value = reference(spec)
    source = old.parent / 'predecessor.zip'
    need(source.is_file() and source.stat().st_size == spec['zip_bytes']
         and sha256_file(source) == spec['zip_sha256'], 'CONTENT_REFERENCE_ACTUAL_AUTHENTICATED_SOURCE_ZIP')
    need(not (out / 'lineage/verified-ancestor.zip').exists() and not (out / PATH).exists(),
         'CONTENT_REFERENCE_NO_OVERWRITE_OR_AMBIGUOUS_STORAGE_MODE')
    target = out / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    save(target, value)
    return value


def admit(spec, root, key, *, max_zip_bytes=LIMIT):
    """Original small normal admission, plus the declared exact reference bytes."""
    import system_campaign_factual_admit as original
    original.check_context(original.os.environ)
    need(sha256_file(Path(original.__file__))
         == '63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4',
         'CONTENT_REFERENCE_EXACT_UNCHANGED_ORIGINAL_NORMAL_ADMISSION')
    reference(spec)
    need(type(max_zip_bytes) is int and max_zip_bytes == LIMIT
         and type(spec['zip_bytes']) is int and 0 < spec['zip_bytes'] < LIMIT,
         'CONTENT_REFERENCE_EXPLICIT_SMALL_P02_ARCHIVE_BOUND')
    expected = ParentReference.model_validate(spec['retained_parent_content_reference']).model_dump(by_alias=True)
    entry = spec['retained_parent_content_reference_file']
    need(set(entry) == {'path', 'bytes', 'sha256'} and entry['path'] == PATH
         and type(entry['bytes']) is int and 0 < entry['bytes'] < 1024**2,
         'CONTENT_REFERENCE_EXACT_DECLARED_PARENT_REFERENCE_MEMBER')
    # The unchanged original verifies AES-GCM before plaintext parsing, every
    # inventory member, actual stopped fences, source/CP/input and all prefixes.
    admitted = original.admit(spec, root, key, max_zip_bytes=LIMIT)
    raw = (admitted / PATH).read_bytes()
    need(len(raw) == entry['bytes'] and hashlib.sha256(raw).hexdigest() == entry['sha256']
         and ParentReference.model_validate(json.loads(raw)).model_dump(by_alias=True) == expected,
         'CONTENT_REFERENCE_ACTUAL_AUTHENTICATED_PARENT_REFERENCE_BYTES')
    return admitted
