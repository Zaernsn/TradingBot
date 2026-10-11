"""JSON-safe, integrity-checked virtual replay state. Never stores live orders."""
from datetime import date, datetime
from app.ml.evaluation import digest


class CheckpointInvalid(ValueError):
    """Frozen replay inputs or persisted state no longer match."""


def encode(value):
    if isinstance(value, datetime):
        return {'__datetime__': value.isoformat()}
    if isinstance(value, date):
        return {'__date__': value.isoformat()}
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    return value


def decode(value):
    if isinstance(value, dict):
        if set(value) == {'__datetime__'}:
            return datetime.fromisoformat(value['__datetime__'])
        if set(value) == {'__date__'}:
            return date.fromisoformat(value['__date__'])
        return {key: decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode(item) for item in value]
    return value


def seal(configuration, prefix, state):
    payload = {'schema': 1, 'configuration': configuration, 'prefix': prefix,
               'state': encode(state)}
    return {**payload, 'sha256': digest(payload)}


def restore(checkpoint, configuration):
    try:
        payload = {key: checkpoint[key] for key in ('schema', 'configuration', 'prefix', 'state')}
        if payload['schema'] != 1 or payload['configuration'] != configuration:
            raise CheckpointInvalid('Replay configuration changed')
        if checkpoint.get('sha256') != digest(payload):
            raise CheckpointInvalid('Replay checkpoint integrity check failed')
        return decode(payload['state'])
    except (KeyError, TypeError, ValueError) as exc:
        raise CheckpointInvalid(str(exc)) from exc
