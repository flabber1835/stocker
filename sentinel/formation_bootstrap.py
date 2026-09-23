"""Broker-free formation under the existing writer and publication locks."""
import hmac

from sentinel import backup_runtime_authority, formed_origin, observation_storage
from sentinel.core.formation import Formation, FormationPlan
from sentinel.core.formation_inputs import FormationInputs
from sentinel.feed import progress, publication
from sentinel.feed.rolling_contract import canonical_json, digest

SCHEMA = 'sentinel.formation-progress/1'


def _signature(checkpoint, context):
    return publication._receipt_hmac({'purpose': SCHEMA, 'context': context, 'checkpoint': checkpoint['sha256']})


def _name(context):
    return 'formation-progress:v1:' + context['observation_id']


def _context(context, plan, pub, binding):
    return dict(observation_id=context['observation_id'], runtime_sha256=digest(context['runtime']),
                runtime_configuration_sha256=digest({k: v for k, v in context['runtime'].items()
                    if k != 'validated_data_publication_sha256'}),
                plan_sha256=digest(plan.model_dump(by_alias=True)), publication_sha256=digest(pub.to_dict()),
                snapshot_id=binding['snapshot_id'])


def read(conn, name, context, plan):
    row = conn.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()
    if not row:
        return None
    value = row[1]
    if not isinstance(value, dict) or set(value) != {'schema', 'context', 'checkpoint', 'hmac_sha256'}:
        raise ValueError('FORMATION_PROGRESS_SHAPE_CHANGED')
    checkpoint = observation_storage.decode(value['checkpoint'])
    if (value['schema'] != SCHEMA or value['context'] != context
            or not hmac.compare_digest(str(value['hmac_sha256']), _signature(checkpoint, context))):
        raise ValueError('FORMATION_PROGRESS_AUTHENTICATION_OR_CONTEXT_CHANGED')
    formed = Formation.resume(checkpoint, plan=plan)
    if str(row[0]) != (formed.state.last_processed_session or formed.axis[251]):
        raise ValueError('FORMATION_PROGRESS_SESSION_CHANGED')
    return formed


def retire_previous_generation(conn, name, context, plan):
    """Verify before retaining one obsolete, never-admitted attempt."""
    row = conn.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()
    if not row or row[1].get('context') == context:
        return
    old = row[1]
    checkpoint = observation_storage.decode(old['checkpoint'])
    old_plan = FormationPlan.model_validate(checkpoint['plan'])
    read(conn, name, old['context'], old_plan)
    if (old['context']['observation_id'] != context['observation_id']
            or old['context']['runtime_configuration_sha256'] != context['runtime_configuration_sha256']
            or old_plan.capital != plan.capital or old_plan.strategy != plan.strategy
            or old_plan.metadata_policy != plan.metadata_policy or old_plan.end > plan.end):
        raise ValueError('FORMATION_PROGRESS_CONFIGURATION_CHANGED')
    backup_runtime_authority.require(conn, operation='retain superseded formation attempt')
    previous = name.replace('formation-progress:', 'formation-previous:', 1)
    conn.execute('INSERT INTO sentinel_processed_sessions (cursor_name,session,state) VALUES (%s,%s,%s::jsonb) '
                 'ON CONFLICT (cursor_name) DO UPDATE SET session=EXCLUDED.session,state=EXCLUDED.state',
                 (previous, row[0], canonical_json(old)))
    conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,))
    conn.commit()


def write(conn, name, formed, context):
    checkpoint = formed.checkpoint()
    value = dict(schema=SCHEMA, context=context,
        checkpoint=observation_storage.encode(checkpoint, 'state'),
        hmac_sha256=_signature(checkpoint, context))
    backup_runtime_authority.require(conn, operation='historical formation checkpoint')
    conn.execute('INSERT INTO sentinel_processed_sessions (cursor_name,session,state) VALUES (%s,%s,%s::jsonb) '
                 'ON CONFLICT (cursor_name) DO UPDATE SET session=EXCLUDED.session,state=EXCLUDED.state',
                 (name, formed.state.last_processed_session or formed.axis[251], canonical_json(value)))
    conn.commit()


def prepare(conn, *, pub, binding, context, check_current):
    """No historical observation, execution plan, fill or command is created."""
    source = FormationInputs(conn, binding, pub)
    plan = source.plan(capital=context['starting_cash'], strategy=context['strategy'])
    bound = _context(context, plan, pub, binding)
    name = _name(context)
    check_current()
    retire_previous_generation(conn, name, bound, plan)
    formed = read(conn, name, bound, plan)
    if formed is None:
        formed = Formation(plan, source.warmup(), data_version=pub.version)
        check_current()
        write(conn, name, formed, bound)
        progress.emit('historical_formation', 'started', sessions=0, required_sessions=126)
    while not formed.complete:
        check_current()
        formed.advance(source.session(formed.axis[252 + formed.count], formed.state))
        # Persist every transition. Repetition after an uncertain acknowledgement
        # loads the exact committed cursor and cannot apply a session twice.
        check_current()
        write(conn, name, formed, bound)
        if formed.count % 10 == 0 or formed.complete:
            progress.emit('historical_formation', 'completed' if formed.complete else 'working',
                          sessions=formed.count, required_sessions=126, session=formed.state.last_processed_session)
    check_current()
    return formed.state, formed_origin.build(formed, context=context, pub=pub, binding=binding), source.session(pub.window_end, formed.state)
