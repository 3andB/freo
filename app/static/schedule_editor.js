/* Pure schedule edits. Display fragments never replace canonical definitions. */
((scope) => {
'use strict';
const copy = value => structuredClone(value);
const dayNumber = day => Date.parse(day + 'T12:00:00Z') / 86400000;
const shift = (day, n) => new Date((dayNumber(day) + n) * 86400000).toISOString().slice(0, 10);
const identity = () => crypto.randomUUID();

function interval(section, start, end, move = false) {
    const result = {...copy(section), start, end};
    if (section.inserts) {
        const delta = move ? start - section.start : 0;
        result.inserts = section.inserts.map(i => ({...copy(i), at: i.at + delta}))
            .filter(i => start <= i.at && i.at < end);
    }
    return result;
}

function split(section, at, newId = identity) {
    if (at <= section.start || at >= section.end) throw Error('Choose a split inside the section.');
    return [interval(section, section.start, at), {...interval(section, at, section.end), id: newId()}];
}

function scoped(list, value, {composing = false, scope = 'series', origin, day}, newId) {
    const prior = list.find(r => r.id === value.id);
    if (composing || !prior || prior.rule.frequency === 'once' || scope === 'series') return;
    value.id = newId();
    if (scope === 'occurrence') {
        prior.rule.exceptions = [...new Set([...(prior.rule.exceptions || []), origin])];
        value.rule = {...value.rule, frequency: 'once', anchor: day, starts_on: null, until: null, exceptions: []};
    } else {
        // Keep the phase anchor: "following" is a lower bound, not a new cycle.
        prior.rule.until = shift(origin, -1);
        value.rule.starts_on = day;
        if (day !== origin) value.rule.anchor = day;
        if (prior.rule.until < (prior.rule.starts_on || prior.rule.anchor)) list.splice(list.indexOf(prior), 1);
    }
}

function edit(original, input, options = {}, newId = identity) {
    const list = copy(original), value = copy(input);
    delete value.origin;
    scoped(list, value, options, newId);
    const conflicts = [];
    for (const other of [...list]) {
        if (other.id === value.id) continue;
        const once = !options.composing && other.rule.frequency === 'once' && value.rule.frequency === 'once';
        if (!options.composing && !once) continue;
        const offset = once ? (dayNumber(other.rule.anchor) - dayNumber(value.rule.anchor)) * 86400 : 0;
        const start = other.start + offset, end = other.end + offset;
        if (start >= value.end || end <= value.start) continue;
        conflicts.push(other);
        list.splice(list.indexOf(other), 1);
        const pieces = [];
        if (start < value.start) pieces.push(interval(other, other.start, value.start - offset));
        if (end > value.end) pieces.push(interval(other, value.end - offset, other.end));
        for (const piece of pieces) {
            piece.id = newId();
            if (once && piece.start >= 86400) {
                piece.rule.anchor = shift(piece.rule.anchor, 1);
                piece.start -= 86400; piece.end -= 86400;
            }
            list.push(piece);
        }
    }
    const index = list.findIndex(r => r.id === value.id);
    if (index < 0) list.push(value); else list[index] = value;
    return {items: list, conflicts, value};
}

function remove(original, id, {composing = false, scope = 'series', origin} = {}) {
    const list = copy(original), item = list.find(r => r.id === id);
    if (!item) return list;
    if (!composing && item.rule.frequency !== 'once' && scope === 'occurrence') {
        item.rule.exceptions = [...new Set([...(item.rule.exceptions || []), origin])];
    } else if (!composing && item.rule.frequency !== 'once' && scope === 'following') {
        item.rule.until = shift(origin, -1);
        if (item.rule.until < (item.rule.starts_on || item.rule.anchor)) list.splice(list.indexOf(item), 1);
    } else list.splice(list.indexOf(item), 1);
    return list;
}

const api = {interval, split, edit, remove};
if (typeof module !== 'undefined') module.exports = api;
else scope.FreoScheduleEditor = api;
})(globalThis);
