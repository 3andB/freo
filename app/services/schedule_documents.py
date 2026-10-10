"""Merge edits to the single saved schedule without losing unrelated changes."""
import copy


class ScheduleConflict(ValueError):
    pass


def merge_value(base, proposed, current):
    if proposed == base:
        return copy.deepcopy(current)
    if current == base or proposed == current:
        return copy.deepcopy(proposed)
    raise ScheduleConflict('This selection was also changed elsewhere. Review the latest selection before replacing it.')


def merge_items(base, proposed, current):
    def index(rows):
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError('Invalid schedule document')
        result = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] in result:
                raise ValueError('Invalid schedule item')
            result[row['id']] = row
        return result
    before, wanted, latest = map(index, (base, proposed, current))
    merged = copy.deepcopy(latest)
    for identifier in dict.fromkeys([*before, *wanted]):
        old, new, saved = before.get(identifier), wanted.get(identifier), latest.get(identifier)
        if new == old:
            continue
        if saved != old and saved != new:
            raise ScheduleConflict('An item you edited was also changed elsewhere. Review the latest schedule before replacing it.')
        if new is None:
            merged.pop(identifier, None)
        else:
            merged[identifier] = copy.deepcopy(new)
    return list(merged.values())
