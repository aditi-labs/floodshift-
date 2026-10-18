"""Explicit read-only tool surface for P3's future Gemini endpoint."""
from copy import deepcopy


class WorldTools:
    def __init__(self, service):
        self._service = service

    def get_scenario_summary(self):
        snapshot = self._service.snapshot()
        return {key: snapshot[key] for key in ('scenario_id', 'phase', 'world_version',
                'branch_id', 'simulation_stage', 'metrics', 'provenance_label', 'data_mode')}

    def get_route_status(self, source_id, destination_id):
        return self._service.get_route_status(source_id, destination_id)

    def get_resource_inventory(self):
        snapshot = self._service.snapshot()
        return {key: snapshot[key] for key in ('token_inventory', 'budget_remaining_model')}

    def get_eligible_interventions(self):
        return self._service.get_eligible_interventions()

    def compare_branches(self, branch_a, branch_b):
        return self._service.compare([branch_a, branch_b])

    def get_service_access(self):
        snapshot = self._service.snapshot()
        return {key: snapshot[key] for key in ('facilities', 'population_demand', 'routes')}

    def get_unmet_needs(self):
        return {k: v for k, v in self._service.snapshot()['metrics'].items() if k.startswith('unmet_')}

    def call(self, name, arguments=None):
        allowed = {'get_scenario_summary', 'get_route_status', 'get_resource_inventory',
                   'get_eligible_interventions', 'compare_branches', 'get_service_access', 'get_unmet_needs', 'get_population_routing'}
        if name not in allowed:
            raise ValueError('unknown_read_only_tool')
        return deepcopy(getattr(self, name)(**(arguments or {})))

    def get_population_routing(self):
        return self._service.snapshot().get('routing_decision')
