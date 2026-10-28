"""Offline provenance checks for libraries built by build_bsp.py (not attestation)."""
from pathlib import Path
import ast
import hashlib
import json

ROOT = Path(__file__).resolve().parent
POLICY_FILES = ('patch_network_bsp.py', 'network_phy_policy.inc')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def policy_hashes(root=ROOT):
    return {name: digest(root / name) for name in POLICY_FILES}


def require_current_phy(path, root=ROOT):
    """Compare actual detector + speed policy with patch literals, never run CLI."""
    tree = ast.parse((root / 'patch_network_bsp.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'patch_phy')
    detector = next(n.value.value for n in function.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'b' for t in n.targets)
                    and isinstance(n.value, ast.Constant))
    policy = (root / 'network_phy_policy.inc').read_text()
    text = Path(path).read_text()
    try:
        start = text.index('void detect_phy(XEmacPs *xemacpsp)')
        end = text.index('\nu32_t phy_setup_emacps', start)
    except ValueError as exc:
        raise ValueError('BSP lacks current PHY patch anchors; regenerate and patch BSP') from exc
    if text[start:end] != detector or text.count(policy) != 1:
        raise ValueError('BSP PHY source differs from current addr1/broadcast0 policy; repatch/rebuild BSP')


def local_file(base, name):
    path = (base / name).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError('BSP manifest path escapes output directory')
    return path


def archive_members(path):
    """Read regular GNU ar, including its long filename table; reject thin ar."""
    data = Path(path).read_bytes()
    if data[:8] != b'!<arch>\n':
        raise ValueError('Expected regular ar archive (thin archives unsupported)')
    offset = 8
    names = b''
    members = {}
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[58:] != b'`\n':
            raise ValueError('Malformed ar member header')
        size = int(header[48:58].decode('ascii').strip())
        start = offset + 60
        body = data[start:start + size]
        if size < 0 or len(body) != size:
            raise ValueError('Truncated ar member')
        name = header[:16].decode('ascii').strip()
        if name == '//':
            names = body
        elif name not in ('/', '/SYM64/'):
            if name.startswith('/') and name[1:].isdigit():
                index = int(name[1:])
                end = names.find(b'/\n', index)
                if index >= len(names) or end < 0:
                    raise ValueError('Invalid ar long filename')
                name = names[index:end].decode('ascii')
            else:
                name = name.rstrip('/')
            if not name or name in members:
                raise ValueError('Empty or duplicate ar member')
            members[name] = hashlib.sha256(body).hexdigest()
        offset = start + size + size % 2
    if offset != len(data):
        raise ValueError('Malformed ar alignment')
    return members


def verify_bsp(base, root=ROOT):
    """Bind policy -> actual compile sources -> objects -> exact archive bytes."""
    base = Path(base).resolve()
    manifest = json.loads((base / 'manifest.json').read_text())
    rebuild = 'Rebuild with current build_bsp.py --bsp <current patched ps7_cortexa9_0> --out <new directory>'
    if manifest.get('schema') != 'ADDA_BSP_BUILD_V2':
        raise ValueError('Legacy/unbound BSP manifest rejected. ' + rebuild)
    if manifest.get('network_policy') != policy_hashes(root):
        raise ValueError('BSP policy fingerprints differ from repository. ' + rebuild)
    frozen_files = manifest.get('frozen_files', {})
    if not frozen_files:
        raise ValueError('Missing frozen local-header/source tree. ' + rebuild)
    actual_frozen = {p.relative_to(base).as_posix() for p in (base / 'compiled_sources').rglob('*') if p.is_file()}
    if actual_frozen != set(frozen_files):
        raise ValueError('Frozen source/header file set mismatch')
    for name, expected in frozen_files.items():
        if digest(local_file(base, name)) != expected:
            raise ValueError('Frozen source/local-header hash mismatch: ' + name)
    for name, expected in manifest['headers'].items():
        if digest(local_file(base / 'include', name)) != expected:
            raise ValueError('BSP header hash mismatch: ' + name)
    bindings = manifest['compile_bindings']
    if not bindings or set(bindings) != set(manifest['objects']):
        raise ValueError('Missing compiled source/object bindings. ' + rebuild)
    expected_members = {'libxil.a': {}, 'liblwip4.a': {}}
    phy_count = 0
    for name, binding in bindings.items():
        source = local_file(base, binding['source'])
        if frozen_files.get(binding['source']) != binding['source_sha256']:
            raise ValueError('Compile source absent from frozen tree manifest: ' + name)
        if digest(source) != binding['source_sha256']:
            raise ValueError('Compiled source hash mismatch: ' + name)
        if digest(local_file(base, name)) != manifest['objects'][name]:
            raise ValueError('Compiled object hash mismatch: ' + name)
        expected_members[binding['library']][name] = manifest['objects'][name]
        if source.name == 'xemacpsif_physpeed.c':
            require_current_phy(source, root)
            if binding['library'] != 'liblwip4.a':
                raise ValueError('PHY object bound to wrong archive')
            phy_count += 1
    if phy_count != 1:
        raise ValueError('Exactly one compiled current PHY source required')
    if set(manifest['libraries']) != set(expected_members):
        raise ValueError('Unexpected BSP library set')
    for name, members in expected_members.items():
        archive = local_file(base, name)
        if not members or digest(archive) != manifest['libraries'][name]:
            raise ValueError('BSP archive hash mismatch: ' + name)
        if archive_members(archive) != members:
            raise ValueError('BSP archive members do not match bound objects: ' + name)
    return {'schema': manifest['schema'], 'network_policy': manifest['network_policy'],
            'manifest_sha256': digest(base / 'manifest.json'), 'libraries': manifest['libraries']}
