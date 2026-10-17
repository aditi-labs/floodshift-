"""Authoritative, thread-safe WorldService for Person 3's API gateway.

Inputs/outputs are JSON dictionaries; no dependency on P3's Pydantic module.
"""
from copy import deepcopy
from threading import RLock

from backend.planning.ghost_bridge import best_suggestion, eligible_interventions
from backend.simulation.reachability import measure
from backend.simulation.routing import route_minutes
from backend.world.rules import SOURCES, RuleError, initial_state, reduce_action, require
from backend.world.scenarios import load_bundle


class WorldService:
    def __init__(self, bundle=None):
        self._bundle = deepcopy(bundle) if bundle is not None else load_bundle()
        self._state = initial_state(self._bundle)
        self._version = 0
        self._seen = set()
        self._events = []
        self._history = {'snap-0': deepcopy(self._state)}
        self._branches = {'main': deepcopy(self._state)}
        self._lock = RLock()

    @classmethod
    def from_bundle(cls, path):
        return cls(load_bundle(path))

    def _snapshot(self):
        return {'schema_version': 2, 'world_version': self._version,
                'snapshot_id': 'snap-' + str(self._version),
                'scenario_id': self._bundle['scenario_id'],
                **{k: deepcopy(self._state[k]) for k in ('phase', 'simulation_stage', 'branch_id',
                   'token_inventory', 'budget_remaining_model', 'narration_event')},
                'tokens': deepcopy(sorted(self._state['tokens'].values(), key=lambda t: t['id'])),
                **measure(self._bundle, self._state),
                'ghost_suggestion': best_suggestion(self._bundle, self._state),
                'provenance_label': self._bundle['provenance_label'],
                'data_mode': self._bundle['data_mode']}

    def snapshot(self):
        with self._lock:
            return deepcopy(self._snapshot())

    def scenario(self):
        return deepcopy(self._bundle)

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
            if any(not isinstance(b, str) or b not in self._branches for b in branches):
                raise ValueError('unknown_branch')
            records = [{'id': b, 'metrics': measure(self._bundle, self._branches[b])['metrics']} for b in branches]
            base = records[0]['metrics']
            return {'branches': records, 'delta_from_first': {r['id']: {k: v - base[k]
                    for k, v in r['metrics'].items()} for r in records[1:]},
                    'metric_provenance': 'educational scenario assumptions'}

    def event_log(self):
        with self._lock:
            return deepcopy(self._events)

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
                if kind == 'suggest':
                    goal = action.get('goal', 'needs_served')
                    try:
                        suggestion = self.suggest(goal)
                    except ValueError as error:
                        raise RuleError(str(error)) from error
                    return {'accepted': True, 'reason': None, 'world_version': self._version,
                            'snapshot': self.snapshot(), 'suggestion': suggestion}
                if kind == 'compare':
                    try:
                        comparison = self.compare(action.get('branches'))
                    except ValueError as error:
                        raise RuleError(str(error)) from error
                    return {'accepted': True, 'reason': None, 'world_version': self._version,
                            'snapshot': self.snapshot(), 'comparison': comparison}
                if kind == 'branch':
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
            self._state = next_state
            self._version += 1
            self._seen.add(action['action_id'])
            self._branches[next_state['branch_id']] = deepcopy(next_state)
            self._history['snap-' + str(self._version)] = deepcopy(next_state)
            snapshot = self.snapshot()
            self._events.append({'timestamp': action.get('timestamp_utc'),
                'branch_id': next_state['branch_id'], 'before_version': self._version - 1,
                'after_version': self._version, 'action': action, 'metrics_before': before,
                'metrics_after': snapshot['metrics']})
            return {'accepted': True, 'reason': None, 'world_version': self._version, 'snapshot': snapshot}
