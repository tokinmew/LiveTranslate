"""Publish a cumulative app-code release into a LiveTranslate feed directory."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=True, separators=(',', ':')) + '\n').encode('ascii')


def version(value):
    if not re.fullmatch(r'(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}', value):
        raise ValueError('Use a three-part release version.')
    parts = tuple(map(int, value.split('.')))
    if max(parts) > 65534:
        raise ValueError('Version component exceeds Windows limits.')
    return parts


@contextmanager
def feed_lock(directory):
    with (directory / '.publish.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def commit(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        tmp = Path(output.name)
        try:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            output.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def publish(app, release, directory):
    v = version(release)
    app = app.resolve(strict=True)
    code = sorted([*app.glob('backend/*.py'), *app.glob('ui/*.cs')])
    code += [app / p for p in ('README.md', 'START-HERE.txt', 'VALIDATION.md')]
    if not 1 <= len(code) <= 160:
        raise ValueError('Unexpected number of source files.')
    for required in ('ui/Program.cs','ui/Updates.cs','ui/UpdateStartup.cs','backend/app_updates.py',
                     'backend/update_install.py','backend/worker.py','backend/speech_memory.py'):
        if app / required not in code:
            raise ValueError('Incomplete cumulative release: ' + required)
    program = (app / 'ui/Program.cs').read_text('utf-8-sig')
    for field in ('AssemblyVersion', 'AssemblyFileVersion'):
        if not re.search(r'\b' + field + r'\("' + re.escape(release) + r'\.0"\)', program):
            raise ValueError('Dashboard assembly version does not match ' + release)
    records = []
    for path in code:
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('Unexpected source symlink: ' + str(path))
        value = path.read_text('utf-8-sig')
        data = value.encode('utf-8')
        if len(data) > 1024*1024 or b'\0' in data:
            raise ValueError('Invalid source: ' + str(path))
        if path.suffix == '.py':
            compile(value, str(path), 'exec', dont_inherit=True)
        records.append(dict(path=path.relative_to(app).as_posix(), text=value, sha256=digest(data)))
    payload = encode(dict(version=release, files=records))
    if len(payload) > 8*1024*1024:
        raise ValueError('The source update exceeds the app limit.')
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / 'latest.json'
    package = directory / ('LiveTranslate-' + release + '.json')
    with feed_lock(directory):
        if manifest.exists():
            old = json.loads(manifest.read_bytes())
            if old.get('product') != 'LiveTranslate' or version(old['version']) > v:
                raise ValueError('The existing manifest belongs to another product or a newer version.')
        if package.exists():
            if digest(package.read_bytes()) != digest(payload):
                raise ValueError('This release number already has different content. Use a new version.')
        else:
            commit(package, payload)
        commit(manifest, encode(dict(schema=1, product='LiveTranslate', version=release,
                                     package=package.name, size=len(payload), sha256=digest(payload))))
    print(f'Published {release} ({len(payload):,} bytes) to {manifest}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True, help='Complete release source directory')
    parser.add_argument('--version', required=True)
    parser.add_argument('--feed', type=Path, required=True)
    args = parser.parse_args()
    publish(args.app, args.version, args.feed)
