/* Pure schedule edits. Display fragments never replace canonical definitions. */
((scope) => {
'use strict';
const copy = value => structuredClone(value);
const dayNumber = day => Date.parse(day + 'T12:00:00Z') / 86400000;
const shift = (day, n) => new Date((dayNumber(day) + n) * 86400000).toISOString().slice(0, 10);
const identity = () => crypto.randomUUID();

function equal(a, b) {
    if (a === b) return true;
    if (!a || !b || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false;
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && equal(a[key], b[key]));
}

function mergeItems(base, proposed, current, force = false) {
    const before = new Map(base.map(row => [row.id, row])), wanted = new Map(proposed.map(row => [row.id, row]));
    const merged = new Map(current.map(row => [row.id, copy(row)]));
    for (const id of new Set([...before.keys(), ...wanted.keys()])) {
        const old = before.get(id), value = wanted.get(id), saved = merged.get(id);
        if (equal(old, value)) continue;
        if (!force && !equal(saved, old) && !equal(saved, value)) throw Error('An item you edited was also changed elsewhere.');
        if (value === undefined) merged.delete(id); else merged.set(id, copy(value));
    }
    return [...merged.values()];
}

function matches(rule, day) {
    if (day < rule.anchor || rule.starts_on && day < rule.starts_on || rule.until && day > rule.until || rule.exceptions?.includes(day)) return false;
    const days = Math.round(dayNumber(day) - dayNumber(rule.anchor)), interval = rule.interval || 1;
    const date = new Date(day + 'T12:00:00Z'), anchor = new Date(rule.anchor + 'T12:00:00Z');
    const weekday = d => (d.getUTCDay() + 6) % 7;
    if (rule.frequency === 'once') return day === rule.anchor;
    if (rule.frequency === 'dates') return rule.dates?.includes(day);
    if (rule.frequency === 'daily') return days % interval === 0;
    if (rule.frequency === 'weekly') return Math.floor((days + weekday(anchor)) / 7) % interval === 0 && rule.weekdays.includes(weekday(date));
    const months = (date.getUTCFullYear() - anchor.getUTCFullYear()) * 12 + date.getUTCMonth() - anchor.getUTCMonth();
    if (months % interval) return false;
    if (rule.nth) {
        const last = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
        return weekday(date) === rule.weekday && (rule.nth === -1 ? date.getUTCDate() + 7 > last : Math.floor((date.getUTCDate() - 1) / 7) + 1 === rule.nth);
    }
    return date.getUTCDate() === (rule.month_day || anchor.getUTCDate());
}

function occurrences(document, day) {
    const result = [];
    for (const entry of document) for (const origin of [shift(day, -1), day]) {
        if (!matches(entry.rule, origin)) continue;
        const offset = origin === day ? 0 : -86400, start = entry.start + offset, end = entry.end + offset;
        if (end > 0 && start < 86400) result.push({...copy(entry), start: Math.max(0, start), end: Math.min(86400, end), origin});
    }
    return result.sort((a, b) => a.start - b.start || a.id.localeCompare(b.id));
}

const recurring = item => !['once', 'dates'].includes(item.rule.frequency);
function coverage(document, day) {
    const rows = occurrences(document, day), overrides = rows.filter(row => !recurring(row));
    return rows.flatMap(row => {
        if (!recurring(row)) return [row];
        let pieces = [row];
        for (const override of overrides) pieces = pieces.flatMap(piece => {
            if (override.start >= piece.end || override.end <= piece.start) return [piece];
            const remaining = [];
            if (piece.start < override.start) remaining.push({...piece, end: override.start});
            if (piece.end > override.end) remaining.push({...piece, start: override.end});
            return remaining;
        });
        return pieces;
    }).sort((a, b) => a.start - b.start || a.id.localeCompare(b.id));
}

function movedRule(rule, origin, day, scope) {
    const result = copy(rule), delta = Math.round(dayNumber(day) - dayNumber(origin));
    if (!delta || scope === 'occurrence') return result;
    result.anchor = shift(rule.anchor, delta);
    if (result.starts_on) result.starts_on = shift(result.starts_on, delta);
    if (result.until) result.until = shift(result.until, delta);
    result.exceptions = (result.exceptions || []).map(date => shift(date, delta));
    if (result.dates) result.dates = result.dates.map(date => shift(date, delta));
    result.weekdays = (result.weekdays || []).map(n => ((n + delta) % 7 + 7) % 7);
    const d = new Date(day + 'T12:00:00Z');
    result.weekday = (d.getUTCDay() + 6) % 7;
    result.month_day = d.getUTCDate();
    if (result.nth > 0) result.nth = Math.floor((d.getUTCDate() - 1) / 7) + 1;
    return result;
}

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

const api = {interval, split, edit, remove, matches, occurrences, coverage, recurring, movedRule, equal, mergeItems};
if (typeof module !== 'undefined') module.exports = api;
else scope.FreoScheduleEditor = api;
})(globalThis);
