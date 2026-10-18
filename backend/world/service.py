"""Authoritative, thread-safe WorldService for Person 3's API gateway.

Inputs/outputs are JSON dictionaries; no dependency on P3's Pydantic module.
"""
from copy import deepcopy
from pathlib import Path
import re
from threading import RLock

from backend.planning.ghost_bridge import best_suggestion, eligible_interventions
from backend.planning.population_routes import plan_population_routes
from backend.simulation.reachability import measure
from backend.simulation.routing import route_minutes
from backend.world.game import evaluate
from backend.world.rules import SOURCES, RuleError, initial_state, reduce_action, require
from backend.world.geometry import scenario_geometry
from backend.world.scenarios import DEFAULT_BUNDLE, load_bundle, validate_bundle
from backend.world.session_store import SessionStore, SessionError, SessionConflict, fingerprint


BRANCH_NAME = re.compile(r'^[A-Za-z0-9_.:-]{1,40}$')


class WorldService:
    def __init__(self, bundle=None, bundle_path=None):
        self._bundle = deepcopy(bundle) if bundle is not None else load_bundle()
        self._bundle_path = Path(bundle_path) if bundle_path else (DEFAULT_BUNDLE if bundle is None else None)
        if 'routing_policy' in self._bundle:
            validate_bundle(self._bundle)
        self._state = initial_state(self._bundle)
        self._version = 0
        self._seen = set()
        self._events = []
        self._history = {'snap-0': deepcopy(self._state)}
        self._branches = {'main': deepcopy(self._state)}
        # Immutable named bookmarks for the UI's Save A / Baseline / Save B / Compare.
        self._saved = {}
        self._lock = RLock()
        self._store = None

    @classmethod
    def from_bundle(cls, path):
        return cls(load_bundle(path), path)

    @classmethod
    def open_session(cls, session_path, bundle_path=None):
        """Resume a compatible checkpoint or create a new durable session.

        Corrupt/incompatible sessions raise SessionError; never silently reset.
        """
        service = cls(load_bundle(bundle_path), bundle_path or DEFAULT_BUNDLE)
        store = SessionStore(session_path)
        payload = store.read()
        if payload is None:
            store.save(service._checkpoint([], service.snapshot()))
        else:
            try:
                if payload['format_version'] != 1 or payload['bundle_fingerprint'] != fingerprint(service._bundle):
                    raise SessionError('session_bundle_or_format_mismatch')
                if not isinstance(payload['events'], list):
                    raise SessionError('invalid_session_events')
                for event in payload['events']:
                    result = service.apply(event['action'])
                    if not result['accepted']:
                        raise SessionError('session_replay_rejected')
                if service.event_log() != payload['events'] or service.snapshot() != payload['snapshot']:
                    raise SessionError('session_replay_mismatch')
            except (KeyError, TypeError, ValueError) as error:
                raise SessionError('invalid_session_payload') from error
        service._store = store
        return service

    def _checkpoint(self, events, snapshot):
        return {'format_version': 1, 'bundle_fingerprint': fingerprint(self._bundle),
                'events': events, 'snapshot': snapshot}

    def _snapshot(self, state=None, version=None):
        state = self._state if state is None else state
        version = self._version if version is None else version
        measured = measure(self._bundle, state)
        snapshot = {'schema_version': 2, 'world_version': version,
                'snapshot_id': 'snap-' + str(version),
                'scenario_id': self._bundle['scenario_id'],
                **{k: deepcopy(state[k]) for k in ('phase', 'simulation_stage', 'branch_id',
                   'token_inventory', 'budget_remaining_model', 'narration_event')},
                'tokens': deepcopy(sorted(state['tokens'].values(), key=lambda t: t['id'])),
                **measured,
                # Game score/objectives are a pure function of this state (no event accumulation).
                'game': evaluate(self._bundle, state, measured),
                # Shown only after someone asks (suggest action); cleared by a bridge or reset.
                'ghost_suggestion': (best_suggestion(self._bundle, state, state['ghost_goal'])
                                     if state.get('ghost_goal') else None),
                'provenance_label': self._bundle['provenance_label'],
                'data_mode': self._bundle['data_mode']}
        if 'routing_policy' in self._bundle:
            decision = plan_population_routes(self._bundle, snapshot)
            decision.update(world_version=version, branch_id=state['branch_id'],
                            scenario_id=self._bundle['scenario_id'], simulation_stage=state['simulation_stage'],
                            bundle_fingerprint=fingerprint(self._bundle))
            decision['decision_id'] = 'routing-' + fingerprint(decision)[:24]
            snapshot['routing_decision'] = decision
        return snapshot

    def snapshot(self):
        with self._lock:
            return deepcopy(self._snapshot())

    def scenario(self):
        return deepcopy(self._bundle)

    def scenario_geometry(self):
        """Static board geometry for GET /scenario; road ids equal snapshot edge ids."""
        data = None
        if self._bundle_path is not None:
            root = Path(self._bundle_path)
            data = root / 'data' if (root / 'data').is_dir() else root
        return scenario_geometry(self._bundle, data)

    def suggest(self, goal='needs_served'):
        with self._lock:
            return deepcopy(best_suggestion(self._bundle, self._state, goal))

    def get_eligible_interventions(self):
        with self._lock:
            return deepcopy(eligible_interventions(self._bundle, self._state))

    def get_route_status(self, source_id, destination_id):
        with self._lock:
            return route_minutes(measure(self._bundle, self._state)['edges'], source_id, destination_id,
                                 [n['id'] for n in self._bundle['roads']['nodes']])

    def compare(self, branches):
        with self._lock:
            if not isinstance(branches, (list, tuple)) or len(branches) < 2:
                raise ValueError('at_least_two_branches_required')
            if any(not isinstance(b, str) or (b not in self._saved and b not in self._branches) for b in branches):
                raise ValueError('unknown_branch')
            # A saved bookmark wins over a live branch head with the same name.
            states = {b: self._saved.get(b, self._branches.get(b)) for b in branches}
            records = [{'id': b, 'saved': b in self._saved,
                        'placed': sorted(t['type'] for t in states[b]['tokens'].values()),
                        'metrics': measure(self._bundle, states[b])['metrics'],
                        'game': evaluate(self._bundle, states[b])} for b in branches]
            base = records[0]['metrics']
            return {'branches': records, 'delta_from_first': {r['id']: {k: v - base[k]
                    for k, v in r['metrics'].items()} for r in records[1:]},
                    'metric_provenance': 'educational scenario assumptions'}

    def has_branch(self, name):
        with self._lock:
            return name in self._saved or name in self._branches

    def event_log(self):
        with self._lock:
            return deepcopy(self._events)

    def decision_log(self):
        """Versioned factual routing records; only accepted actions are recorded."""
        with self._lock:
            return deepcopy([event['routing_decision'] for event in self._events if 'routing_decision' in event])

    def frozen_copy(self):
        """Detached version-consistent view for narration; no persistence attached."""
        with self._lock:
            clone = WorldService(self._bundle, self._bundle_path)
            clone._state = deepcopy(self._state)
            clone._version = self._version
            clone._branches = deepcopy(self._branches)
            clone._saved = deepcopy(self._saved)
            clone._history = deepcopy(self._history)
            clone._seen = set(self._seen)
            clone._events = deepcopy(self._events)
            return clone

    def apply(self, action):
        with self._lock:
            if hasattr(action, 'model_dump'):
                action = action.model_dump(mode='json', exclude_none=True)
            action = deepcopy(action)
            try:
                require(isinstance(action, dict), 'invalid_action')
                require(isinstance(action.get('action_id'), str) and bool(action['action_id']), 'missing_action_id')
                require(action['action_id'] not in self._seen, 'duplicate')
                require(type(action.get('expected_world_version')) is int and
                        action['expected_world_version'] == self._version, 'stale_version')
                require(isinstance(action.get('source'), str) and action['source'] in SOURCES, 'invalid_source')
                require(isinstance(action.get('type'), str), 'unsupported_action')
                kind = action['type']
                saved = None
                suggestion = None
                if kind == 'suggest':
                    goal = action.get('goal') or 'needs_served'
                    try:
                        suggestion = self.suggest(goal)
                    except ValueError as error:
                        raise RuleError(str(error)) from error
                    require(suggestion is not None, 'no_suggestion')
                    # Displaying a ghost is a logged, versioned event so every screen agrees.
                    next_state = deepcopy(self._state)
                    next_state['ghost_goal'] = goal
                    next_state['narration_event'] = {'event_type': 'bridge_suggested', 'model_only': True}
                elif kind == 'compare':
                    try:
                        comparison = self.compare(action.get('branches'))
                    except ValueError as error:
                        raise RuleError(str(error)) from error
                    return {'accepted': True, 'reason': None, 'world_version': self._version,
                            'snapshot': self.snapshot(), 'comparison': comparison}
                elif kind == 'save_branch':
                    name = action.get('branch_id')
                    require(isinstance(name, str) and bool(BRANCH_NAME.match(name)), 'invalid_branch_id')
                    next_state = deepcopy(self._state)
                    next_state['narration_event'] = {'event_type': 'branch_saved', 'model_only': True}
                    saved = name
                elif kind == 'load_branch':
                    name = action.get('branch_id')
                    require(isinstance(name, str) and name in self._saved, 'unknown_branch')
                    next_state = deepcopy(self._saved[name])
                    next_state['branch_id'] = name
                    next_state['ghost_goal'] = None  # Clear ghost on branch load
                    next_state['narration_event'] = {'event_type': 'branch_loaded', 'model_only': True}
                elif kind == 'branch':
                    name = action.get('branch_id')
                    require(isinstance(name, str) and bool(name), 'invalid_branch_id')
                    require(name not in self._branches, 'branch_exists')
                    snapshot_id = action.get('from_snapshot_id', 'snap-' + str(self._version))
                    require(isinstance(snapshot_id, str) and snapshot_id in self._history, 'unknown_snapshot')
                    next_state = deepcopy(self._history[snapshot_id])
                    next_state['branch_id'] = name
                else:
                    next_state = reduce_action(self._bundle, self._state, action)
            except RuleError as error:
                return {'accepted': False, 'reason': str(error), 'world_version': self._version,
                        'snapshot': self.snapshot()}
            before = measure(self._bundle, self._state)['metrics']
            version = self._version + 1
            snapshot = deepcopy(self._snapshot(next_state, version))
            event = {'timestamp': action.get('timestamp_utc'),
                'branch_id': next_state['branch_id'], 'before_version': self._version,
                'after_version': version, 'action': action, 'metrics_before': before,
                'metrics_after': snapshot['metrics']}
            if 'routing_decision' in snapshot:
                event['routing_decision'] = deepcopy(snapshot['routing_decision'])
            if self._store is not None:
                try:
                    self._store.save(self._checkpoint(self._events + [event], snapshot))
                except SessionError as error:
                    reason = 'session_conflict' if isinstance(error, SessionConflict) else 'persistence_unavailable'
                    return {'accepted': False, 'reason': reason, 'world_version': self._version,
                            'snapshot': self.snapshot()}
                except (TypeError, ValueError):
                    return {'accepted': False, 'reason': 'invalid_action', 'world_version': self._version,
                            'snapshot': self.snapshot()}
            # Acknowledgement occurs only after the durable transaction succeeds.
            self._state = next_state
            self._version = version
            self._seen.add(action['action_id'])
            self._branches[next_state['branch_id']] = deepcopy(next_state)
            self._history['snap-' + str(self._version)] = deepcopy(next_state)
            self._events.append(deepcopy(event))
            if saved is not None:
                self._saved[saved] = deepcopy(next_state)
            result = {'accepted': True, 'reason': None, 'world_version': self._version, 'snapshot': snapshot}
            if suggestion is not None:
                result['suggestion'] = suggestion
            return result

    def _apply_internal(self, kind, **fields):
        with self._lock:
            return self.apply({'action_id': f'{kind}-{self._version}', 'type': kind, 'source': 'manual',
                               'expected_world_version': self._version, **fields})

    def request_suggestion(self, goal='needs_served'):
        """Compute the best ghost bridge and show it in subsequent snapshots."""
        return self._apply_internal('suggest', goal=goal)

    def save_branch(self, name):
        """Bookmark the current state under ``name`` (overwrites an earlier bookmark)."""
        return self._apply_internal('save_branch', branch_id=name)

    def load_branch(self, name):
        """Continue from a saved bookmark; the bookmark itself stays unchanged."""
        return self._apply_internal('load_branch', branch_id=name)
