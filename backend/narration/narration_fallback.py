"""Truthful offline narration derived from one consistent world snapshot."""


def narrate(snapshot, suggestion=None):
    """``suggestion`` overrides the displayed ghost so answers can cite the planner."""
    if snapshot['phase'] == 'ready':
        return 'Place START on the control pad to begin the educational simulation.'
    metrics = snapshot['metrics']
    text = (f"This model has {metrics['unmet_food_model']} unmet food units, "
            f"{metrics['unmet_medical_model']} unmet medical units, and "
            f"{metrics['unmet_refuge_model']} unmet refuge units.")
    suggestion = suggestion or snapshot.get('ghost_suggestion')
    if suggestion:
        text += f" A temporary bridge at {suggestion['site_id']} could serve {suggestion.get('gain_model', 0)} additional need units."
    return text + ' These are illustrative outcomes, not real rescue results.'
