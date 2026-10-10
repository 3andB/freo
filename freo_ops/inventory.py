"""Customer file selection shared by the release builder and source installer.

Keep this module standard-library-only: provisioning runs before venv setup.
"""
from pathlib import PurePosixPath

DIRECTORIES = ('app', 'freo_ops', 'migrations', 'deploy', 'scripts', 'docs')
FILES = ('wsgi.py', 'requirements.txt', 'requirements-live-mic.txt', '.env.example',
         'README.md', 'SECURITY.md', 'CHANGELOG.md', 'LICENSE', 'V1_UPGRADE_NOTES.md')
SCRIPTS = {
    'accept-install.py', 'admin-maintenance.py', 'hosting-guard.py', 'hosting-recording.py', 'hosting-admin.py', 'hosting-admin-launcher.py', 'install-hosting.py', 'studio-api-key.py',
    'build-icecast-2.5.sh', 'recording-storage.py', 'install.sh', 'provision.sh', 'install-python.sh', 'install-statistics.sh',
    'configure-icecast-repository.sh', 'media-web-access.sh', 'render-radio-config.py',
    'validate-admin-login.py', 'validate-install.sh', 'validate-station-instance.py',
}
OPERATOR_DOCS = {
    'v1-rc1-installation.md', 'v1-rc2-installation.md', 'freo-studio-hosting-integration.md', 'studio-release-api.md',
    'installation.md', '0.3.2-rc.2-installation.md', 'recovery-and-upgrades.md', 'security.md', 'license-agreement.md',
    'audio-import-and-processing.md', 'appearance.md', 'automation.md', 'channel-management.md',
    'clocks.md', 'copyright-and-dmca.md', 'custom-domains.md', 'dj-booth-cue.md',
    'event-blocks.md', 'icecast-upgrade.md', 'imaging.md', 'live-assist.md', 'live-mic.md',
    'master-broadcast.md', 'media-library.md', 'operations-navigation.md',
    'player-and-listener-experience.md', 'playlists.md', 'programming-ui.md',
    'public-radio-directories.md', 'radio-engine.md', 'rotations.md', 'scheduling.md',
    'sound-room.md', 'station-location-reporting.md', 'station-settings-and-review.md',
    'station-website.md', 'stations.md', 'statistics.md', 'timed-events.md', 'traffic.md',
    'ui.md', 'version-awareness-client.md', 'public-api-v1.md',
}


def customer_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        return False
    if any(part in ('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'tests', '.github') for part in path.parts):
        return False
    if path.name.endswith(('.pyc', '.bak', '.previous', '.log')):
        return False
    if (path.name.startswith('.env') and name != '.env.example') or path.suffix in ('.key', '.pem', '.dump', '.db', '.sqlite', '.gpg'):
        return False
    if path.parts[0] == 'scripts':
        return len(path.parts) == 2 and path.name in SCRIPTS
    if path.parts[0] == 'docs':
        return len(path.parts) == 2 and path.name in OPERATOR_DOCS
    return name in FILES or path.parts[0] in ('app', 'freo_ops', 'migrations', 'deploy')
