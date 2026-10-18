"""A speech-ready factual payload for a future ElevenLabs adapter; no cloud calls."""
from copy import deepcopy


def speech_payload(decision):
    """Bind spoken text to the exact saved decision, never an unversioned plan."""
    return {'decision_id': decision['decision_id'], 'world_version': decision['world_version'],
            'branch_id': decision['branch_id'], 'model_only': True,
            'text': (f"This model assigns routes for {decision['assigned_group_equivalents']} group equivalents; "
                     f"{decision['unassigned_group_equivalents']} remain unassigned in this planning wave. " +
                     ' '.join(group['explanation'] for group in decision['groups'])),
            'facts': deepcopy(decision), 'voice_status': 'not_connected'}
