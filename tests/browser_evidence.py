"""Persist browser logs as they are drained, including before a test fails."""
import json


def drain_browser_console(stack):
    entries = stack.driver.get_log('browser')
    if entries:
        with (stack.evidence/'browser-console.jsonl').open('a') as output:
            for entry in entries:
                output.write(json.dumps(entry)+'\n')
    return [entry for entry in entries if entry['level'] == 'SEVERE'
            and entry.get('source') == 'javascript']
