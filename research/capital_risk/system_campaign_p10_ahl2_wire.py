"""Pure bounded single-member gzip and strict declared JSON object reader."""
import json
import zlib

from system_campaign_p10_ahl2_contract import need


def inflate(raw, *, compressed_limit=128*1024**2, expanded_limit=512*1024**2):
    need(type(raw) is bytes and raw[:2] == b'\x1f\x8b' and len(raw) <= compressed_limit,
         'P10_DECLARED_GZIP_HEADER_AND_COMPRESSED_BOUND')
    need(type(expanded_limit) is int and expanded_limit > 0, 'P10_POSITIVE_EXPLICIT_EXPANSION_BOUND')
    decoder = zlib.decompressobj(31)
    try:
        data = decoder.decompress(raw, expanded_limit + 1)
    except zlib.error as error:
        raise ValueError('P10_GZIP_CRC_OR_FORMAT_REFUSAL') from error
    need(len(data) <= expanded_limit and not decoder.unconsumed_tail, 'P10_GZIP_EXPANDED_BOUND')
    need(decoder.eof and not decoder.unused_data, 'P10_SINGLE_COMPLETE_GZIP_MEMBER_NO_TRAILING_BYTES')
    return data


def object_bytes(raw, *, gzip_declared=False, expanded_limit=512*1024**2):
    if gzip_declared:
        raw = inflate(raw, expanded_limit=expanded_limit)
    else:
        need(type(raw) is bytes and raw[:2] != b'\x1f\x8b' and len(raw) <= expanded_limit,
             'P10_PLAIN_JSON_KIND_AND_BOUND_NO_AUTODETECT')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            need(key not in value, 'P10_DUPLICATE_JSON_KEY')
            value[key] = item
        return value
    def nonfinite(_):
        raise ValueError('P10_NONFINITE_JSON_VALUE')
    value = json.loads(raw.decode('utf8'), object_pairs_hook=unique, parse_constant=nonfinite)
    need(type(value) is dict, 'P10_JSON_OBJECT_ROOT_REQUIRED')
    return value
