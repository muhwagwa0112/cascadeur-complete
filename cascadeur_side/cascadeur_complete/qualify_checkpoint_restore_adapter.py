"""Exact native restore qualification with retained-tab later-idle readback.

Immutable restore evidence is retained immediately. Registration waits for a
later source-idle callback to verify the source and its owned restored tab.
The restored tab remains open. No crash cause or general rig claim is made.
"""
import hashlib
import json
import os
import uuid
from pathlib import Path

_PENDING = {}
_BY_SOURCE = {}
_RUN_ACTIVE = False
_MAX_SCENES = 128


def command_name():
    return "Cascadeur Complete.Qualify checkpoint restore adapter"


def command_description():
    return "Observe exact native restore and later-idle readback; retain the restored tab"


def _same_inventory(actual, expected):
    return (len(actual) == len(expected)
            and all(any(item is wanted for item in actual) for wanted in expected))


def _inventory(manager):
    values = list(manager.scenes())
    if len(values) > _MAX_SCENES or len({id(value) for value in values}) != len(values):
        raise ValueError('RECOVERY_QUALIFICATION_INVENTORY_UNOBSERVED')
    return values


def qualification_status(qualification_id):
    """Read an in-process JSON snapshot; never inspect or act on native scenes."""
    record = _PENDING.get(qualification_id)
    if record is None:
        raise ValueError('RECOVERY_QUALIFICATION_UNKNOWN_ID')
    return json.loads(json.dumps(record['public'], allow_nan=False))


def _detach_later(record):
    # EventManager.run iterates dict.values() directly. Do not mutate that
    # dictionary from a subscription callback, including terminal failure.
    if record.get('detach_queued') or record.get('subscription') is None:
        return
    record['detach_queued'] = True
    def detach():
        subscription = record.get('subscription')
        if subscription is not None:
            try:
                record['idle_manager'].unsubscribe(subscription)
            except KeyError:
                pass  # Already removed externally; terminal state remains.
            except Exception as error:
                record['public']['subscription_cleanup_error'] = str(error)[:256]
                return
            record['subscription'] = None
    try:
        record['idle_manager'].execute_when_idle(detach)
    except Exception as error:
        # This observer is terminal and therefore inert even if detaching
        # fails. Do not relabel an already registered adapter as a failure.
        record['public']['subscription_cleanup_error'] = str(error)[:256]


def _fail(record, error):
    public = record['public']
    public.update(status='failed', failed_phase=public['phase'], phase='failed',
                  error_code=str(error).split(':', 1)[0][:128], error_detail=str(error)[:1000])
    # Preserve files and every remaining tab; never redispatch a failed
    # observation or manufacture a successful readback after an exception.
    _detach_later(record)


def _original(record, manager, *, target_present):
    """Check live inventory identity before dereferencing stored wrappers."""
    from . import guarded_runtime as guards
    from .native_adapters import _WORKSPACES
    from .native_scene_reader import read_scene
    actual = _inventory(manager)
    expected = record['inventory'] + ([record['target']] if target_present else [])
    if not _same_inventory(actual, expected):
        raise ValueError('RECOVERY_QUALIFICATION_INVENTORY_CHANGED')
    source = record['source']
    if not any(item is source for item in actual):
        raise ValueError('RECOVERY_QUALIFICATION_SOURCE_REMOVED')
    guards.assert_loaded_package()
    public = record['public']
    if (guards.RUNTIME_EPOCH != public['runtime_epoch']
            or guards.LOADED_FINGERPRINT != public['fingerprint']
            or manager.current_scene() is not source
            or dict(guards.scene_instance(source)) != record['source_identity']
            or str(source.get_path_name()) != record['source_path']
            or _WORKSPACES.get(public['scene_instance_id']) != record['manifest']
            or read_scene(source) != record['projection']):
        raise ValueError('RECOVERY_QUALIFICATION_SOURCE_CHANGED')


def _observe(qualification_id, idle_scene):
    import csc
    from . import guarded_runtime as guards
    from .native_scene_reader import read_scene
    from .native_checkpoint_restore import NativeCheckpointRestoreAdapter
    record = _PENDING[qualification_id]
    public = record['public']
    if (_RUN_ACTIVE or record['busy'] or public['status'] != 'pending'
            or guards.write_observation()[0] == 'started'):
        return
    manager = csc.app.get_application().get_scene_manager()
    saved_local = dict(vars(guards._LOCAL))
    record['busy'] = True
    try:
        # Ignore other scenes without invoking methods on their wrappers.
        inventory = _inventory(manager)
        if not any(item is record['source'] for item in inventory):
            raise ValueError('RECOVERY_QUALIFICATION_SOURCE_REMOVED')
        expected = record['inventory'] + [record['target']]
        if not _same_inventory(inventory, expected):
            raise ValueError('RECOVERY_QUALIFICATION_INVENTORY_CHANGED')
        if manager.current_scene() is not record['source']:
            raise ValueError('RECOVERY_QUALIFICATION_SOURCE_CHANGED')
        if idle_scene is not record['source_domain']:
            return
        phase = public['phase']
        if phase == 'awaiting_verification':
            _original(record, manager, target_present=True)
            target = record['target']
            if (dict(guards.scene_instance(target)) != record['target_identity']
                    or str(target.get_path_name()) != record['target_path']
                    or guards.digest(read_scene(target)) != record['observation']['restored_projection_digest']):
                raise ValueError('RECOVERY_QUALIFICATION_TARGET_CHANGED')
            public['phase'] = 'registering'
            evidence, path = record['evidence'], record['path']
            with path.open('xb') as stream:
                stream.write(evidence)
                stream.flush()
                os.fsync(stream.fileno())
            public['evidence_written'] = True
            adapter = NativeCheckpointRestoreAdapter(evidence, path)
            guards.register_adapter('safety.rollback', adapter)
            public.update(status='complete', phase='complete', cleanup='retained_owned_restore_tab',
                          evidence_sha256=adapter.verification['evidence_sha256'])
            _detach_later(record)
            try:
                record['source_domain'].success('Qualified exact native restore after later-idle readback; owned restored tab retained; failed-request recovery requires separate attestation and permit')
            except Exception as error:
                public['notification_error'] = str(error)[:256]
    except Exception as error:
        _fail(record, error)
    finally:
        record['busy'] = False
        vars(guards._LOCAL).clear()
        vars(guards._LOCAL).update(saved_local)


def _subscribe_later(record):
    def subscribe():
        if record['public']['status'] != 'pending':
            return
        if _RUN_ACTIVE:
            record['idle_manager'].execute_when_idle(subscribe)
            return
        try:
            record['subscription'] = record['idle_manager'].subscribe(
                lambda idle_scene: _observe(record['public']['qualification_id'], idle_scene))
        except Exception as error:
            _fail(record, error)
    # Also safe when run is invoked by a persistent idle subscription.
    record['idle_manager'].execute_when_idle(subscribe)


def run(scene):
    global _RUN_ACTIVE
    from . import guarded_runtime as guards
    if _RUN_ACTIVE:
        raise ValueError('RECOVERY_QUALIFICATION_REENTRANT')
    if guards.write_observation()[0] == 'started':
        raise ValueError('RECOVERY_QUALIFICATION_WRITE_IN_PROGRESS')
    _RUN_ACTIVE = True
    try:
        return _run(scene)
    finally:
        _RUN_ACTIVE = False


def _run(scene):
    import csc
    from events import scene_idle_manager
    from . import runtime as rt, guarded_runtime as guards
    from .native_adapters import _WORKSPACES
    from .native_scene_reader import read_scene
    from .native_checkpoint_restore import qualify_restore, _CHECKPOINTS
    guards.assert_loaded_package()
    manager = csc.app.get_application().get_scene_manager()
    inventory = _inventory(manager)
    active = manager.current_scene()
    if active is None or not any(item is active for item in inventory):
        raise ValueError('RECOVERY_QUALIFICATION_SOURCE_UNAVAILABLE')
    identity = dict(guards.scene_instance(active))
    manifest = _WORKSPACES.get(identity['scene_instance_id'])
    anchor = _CHECKPOINTS.get(guards.digest(manifest)) if manifest else None
    if anchor is None:
        raise ValueError('RECOVERY_CHECKPOINT_ANCHOR_UNAVAILABLE: active owned checkpoint required')
    before, source_path = read_scene(active), str(active.get_path_name())
    key = (guards.RUNTIME_EPOCH, guards.LOADED_FINGERPRINT, identity['scene_instance_id'])
    prior = _BY_SOURCE.get(key)
    if prior is not None:
        record = _PENDING[prior]
        if (record['source'] is not active or record['source_identity'] != identity
                or record['manifest'] != manifest or record['projection'] != before
                or record['source_path'] != source_path):
            raise ValueError('RECOVERY_QUALIFICATION_SOURCE_CHANGED: prior observation cannot certify a different checkpoint or content')
        return qualification_status(prior)
    qualification_id = str(uuid.uuid4())
    path = Path(manifest['path']).parent / ('restore-qualification-' + qualification_id + '.json')
    public = {'qualification_id': qualification_id, 'operation': 'safety.rollback', 'status': 'pending',
              'phase': 'restoring', 'runtime_epoch': guards.RUNTIME_EPOCH, 'fingerprint': guards.LOADED_FINGERPRINT,
              'scene_instance_id': identity['scene_instance_id'], 'snapshot_manifest_digest': guards.digest(manifest),
              'source_projection_digest': guards.digest(before), 'evidence_path': str(path), 'evidence_written': False,
              'cleanup': 'retained_owned_restore_tab',
              'conditional_failed_request_recovery': 'requires_partial_write_attestation_and_signed_permit'}
    record = {'public': public, 'source': active, 'source_domain': rt._domain_scene(active),
              'source_identity': identity, 'source_path': source_path, 'inventory': inventory,
              'manifest': json.loads(json.dumps(manifest)), 'projection': before, 'path': path,
              'target': None, 'busy': False, 'subscription': None, 'idle_manager': scene_idle_manager}
    _PENDING[qualification_id], _BY_SOURCE[key] = record, qualification_id
    saved_local = dict(vars(guards._LOCAL))
    try:
        guards.begin_request({'operations': []})
        def unchanged():
            _original(record, manager, target_present=False)
        guards.set_write_guard(unchanged)
        evidence = qualify_restore(active, manifest, run_id=anchor['run_id'])
        observation = json.loads(evidence)
        record.update(evidence=evidence, observation=observation)
        public['evidence_sha256'] = hashlib.sha256(evidence).hexdigest()
        after = _inventory(manager)
        new = [item for item in after if not any(item is original for original in inventory)]
        if len(new) != 1 or not _same_inventory(after, inventory + new):
            raise ValueError('RECOVERY_QUALIFICATION_INVENTORY_CHANGED')
        target = new[0]
        record.update(target=target, target_identity=dict(guards.scene_instance(target)),
                      target_path=str(target.get_path_name()))
        if record['target_identity'] != observation['scene_after']:
            raise ValueError('RECOVERY_QUALIFICATION_TARGET_CHANGED')
        _original(record, manager, target_present=True)
        public.update(phase='awaiting_verification',
                      target_scene_instance_id=record['target_identity']['scene_instance_id'],
                      target_path=record['target_path'])
        _subscribe_later(record)
    except Exception as error:
        _fail(record, error)
    finally:
        vars(guards._LOCAL).clear()
        vars(guards._LOCAL).update(saved_local)
    return qualification_status(qualification_id)
