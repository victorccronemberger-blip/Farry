"""Publish signed artifacts to Farry; credentials remain in Git's credential manager."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

REPOSITORY = 'victorccronemberger-blip/Farry'


def request(path, *, method='GET', data=None, content_type='application/json', length=None, missing_ok=False):
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        result = subprocess.run(['git', 'credential', 'fill'],
            input='protocol=https\nhost=github.com\n\n', text=True, capture_output=True, check=True)
        token = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line).get('password')
    if not token:
        raise RuntimeError('GitHub authentication unavailable')
    url = path if path.startswith('https://uploads.github.com/') else 'https://api.github.com' + path
    headers = {
        'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
        'Content-Type': content_type, 'User-Agent': 'Farry-Publisher', 'X-GitHub-Api-Version': '2022-11-28'}
    if length is not None:
        headers['Content-Length'] = str(length)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if missing_ok and method == 'GET' and exc.code == 404:
            return None
        raise RuntimeError(f'GitHub HTTP {exc.code}') from None


def check_remote_version(version, *, existing_draft=False):
    latest = request('/repos/' + REPOSITORY + '/releases/latest', missing_ok=True)
    if latest:
        import re
        tag = latest.get('tag_name', '')
        if not re.fullmatch(r'v(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})', tag):
            raise RuntimeError('Latest published version is invalid; publication refused')
        if tuple(map(int, version.split('.'))) <= tuple(map(int, tag[1:].split('.'))):
            raise RuntimeError('New version must be greater than the latest published version')
    release = request('/repos/' + REPOSITORY + '/releases/tags/v' + version, missing_ok=True)
    if release and not (existing_draft and release.get('draft')):
        raise RuntimeError('Version already exists; published artifacts must never be replaced')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--version')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--publish-existing', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--check', action='store_true', help='Validate local artifacts and remote version without publishing')
    parser.add_argument('--artifact-directory', type=Path)
    parser.add_argument('--target-commit', help='Approved and pushed source commit for a new release tag')
    args = parser.parse_args()
    if args.inspect:
        user = request('/user')
        repo = request('/repos/' + REPOSITORY)
        print(json.dumps({'login': user['login'], 'id': user['id'], 'private': repo['private'],
                          'can_push': repo.get('permissions', {}).get('push', False)}))
        return
    if args.status:
        releases = request('/repos/' + REPOSITORY + '/releases?per_page=10')
        runs = request('/repos/' + REPOSITORY + '/actions/runs?per_page=4')
        print(json.dumps({'releases': [{'id': r['id'], 'tag': r['tag_name'], 'draft': r['draft'],
            'assets': [{'name': a['name'], 'state': a['state'], 'size': a['size']} for a in r['assets']]}
            for r in releases], 'checks': [{'commit': r['head_sha'][:8], 'status': r['status'],
            'conclusion': r['conclusion']} for r in runs['workflow_runs']]}))
        return
    if not args.version:
        parser.error('--version required')
    import re
    if not re.fullmatch(r'(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})', args.version):
        parser.error('invalid version')
    root = Path(__file__).resolve().parent.parent
    directory = args.artifact_directory.resolve() if args.artifact_directory else root / 'dist'
    paths = [directory / name for name in ('Farry-windows-x64.zip', 'FarrySetup.exe', 'release.json', 'release.json.sig')]
    if not all(path.is_file() for path in paths):
        raise RuntimeError('Build and sign all four artifacts before creating a release')
    subprocess.run(['node', str(root / 'tools' / 'check-release.mjs'), args.version, str(directory)], check=True)
    check_remote_version(args.version, existing_draft=args.publish_existing)
    if args.check:
        print('Preflight passed. No release was created or published.')
        return
    if args.publish_existing:
        import hashlib
        matches = [r for r in request('/repos/' + REPOSITORY + '/releases?per_page=100')
                   if r['tag_name'] == 'v' + args.version and r['draft']]
        if len(matches) != 1:
            raise RuntimeError('Expected exactly one matching draft release')
        release = matches[0]
        for path in paths:
            assets = [a for a in release['assets'] if a['name'] == path.name and a['state'] == 'uploaded']
            with path.open('rb') as source:
                digest = 'sha256:' + hashlib.file_digest(source, 'sha256').hexdigest()
            if len(assets) != 1 or assets[0].get('digest') != digest or assets[0]['size'] != path.stat().st_size:
                raise RuntimeError('Remote artifact not verified: ' + path.name)
        request('/repos/' + REPOSITORY + '/releases/' + str(release['id']), method='PATCH',
                data=json.dumps({'draft': False, 'tag_name': 'v' + args.version,
                                 **({'target_commitish': args.target_commit} if args.target_commit else {})}).encode())
        print('Published:', release['html_url'])
        return
    # A draft stays invisible to clients until all uploads succeed.
    result = request('/repos/' + REPOSITORY + '/releases', method='POST', data=json.dumps({
        'tag_name': 'v' + args.version, 'name': 'Farry ' + args.version, 'draft': True,
        **({'target_commitish': args.target_commit} if args.target_commit else {}),
        'body': 'Distribuição Windows pelo Farry: instalador por usuário, desinstalação registrada e assinatura interna. Aplicativo-base e origem documentados no manifesto assinado. Dados locais preservados.'}).encode())
    for path in paths:
        with path.open('rb') as source:
            # urllib accepts a readable file and streams it with an explicit length.
            request(result['upload_url'].split('{')[0] + '?name=' + path.name,
                    method='POST', data=source, content_type='application/octet-stream', length=path.stat().st_size)
        print('Uploaded:', path.name)
    if args.publish:
        request('/repos/' + REPOSITORY + '/releases/' + str(result['id']), method='PATCH',
                data=json.dumps({'draft': False, 'tag_name': 'v' + args.version,
                                 **({'target_commitish': args.target_commit} if args.target_commit else {})}).encode())
    print(result['html_url'])


if __name__ == '__main__':
    main()
