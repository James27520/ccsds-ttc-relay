"""Pure offline tests: synthetic archives only; no compiler, sockets or board."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from build_bsp_guard import ROOT, archive_members, digest, policy_hashes, require_current_phy, verify_bsp


def write_archive(path, members):
    data = bytearray(b'!<arch>\n')
    long_names = b''
    names = {}
    for name in members:
        if len(name) > 15:
            names[name] = '/' + str(len(long_names))
            long_names += name.encode() + b'/\n'
        else:
            names[name] = name + '/'
    records = ([('//', long_names)] if long_names else []) + [(names[n], b) for n, b in members.items()]
    for name, body in records:
        header = f'{name:<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(body):<10}`\n'.encode()
        assert len(header) == 60
        data.extend(header + body + (b'\n' if len(body) % 2 else b''))
    path.write_bytes(data)


def current_phy():
    # Minimal patch anchors; the authoritative repository function fills bodies.
    import ast
    tree = ast.parse((ROOT / 'patch_network_bsp.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'patch_phy')
    scope = {'ROOT': ROOT}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<test fixture>', 'exec'), scope)
    return scope['patch_phy']('void detect_phy(XEmacPs *xemacpsp)\n{}\nu32_t phy_setup_emacps()\n{}\nstatic u32_t get_Realtek_phy_speed()\n{}\n#endif\n')


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'library'
        self.base.mkdir()
        (self.base / 'include').mkdir()
        (self.base / 'include/xparameters.h').write_text('ADDA platform fixture')
        self.manifest = {'schema': 'ADDA_BSP_BUILD_V2', 'network_policy': policy_hashes(),
                         'headers': {'xparameters.h': digest(self.base / 'include/xparameters.h')},
                         'frozen_files': {},'objects': {}, 'libraries': {}, 'compile_bindings': {}}
        for name, library, text in [('xil_000_boot.o', 'libxil.a', 'startup'),
                                    ('lwip_031_xemacpsif_physpeed.o', 'liblwip4.a', current_phy())]:
            source = self.base / 'compiled_sources' / ('xemacpsif_physpeed.c' if library == 'liblwip4.a' else 'startup.S')
            source.parent.mkdir(exist_ok=True)
            source.write_text(text)
            (self.base / name).write_bytes(('object:' + name).encode())
            self.manifest['objects'][name] = digest(self.base / name)
            self.manifest['compile_bindings'][name] = {'source': source.relative_to(self.base).as_posix(),
                                                      'source_sha256': digest(source), 'library': library}
            write_archive(self.base / library, {name: (self.base / name).read_bytes()})
            self.manifest['libraries'][library] = digest(self.base / library)
        (self.base / 'compiled_sources/local_policy.h').write_text('#define PHY_ADDR 1\n')
        self.manifest['frozen_files'] = {p.relative_to(self.base).as_posix():digest(p)
                                         for p in (self.base / 'compiled_sources').rglob('*') if p.is_file()}
        self.save()

    def save(self):
        (self.base / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_valid_and_relocated(self):
        self.assertEqual(verify_bsp(self.base)['schema'], 'ADDA_BSP_BUILD_V2')
        moved = self.base.parent / 'relocated'
        shutil.copytree(self.base, moved)
        shutil.rmtree(self.base)
        self.assertEqual(verify_bsp(moved)['libraries'], self.manifest['libraries'])

    def test_legacy_and_snapshot_only_rejected(self):
        self.manifest.pop('schema')
        (self.base / 'source_snapshot.zip').write_bytes(b'not compiled provenance')
        self.save()
        with self.assertRaisesRegex(ValueError, 'Legacy/unbound'):
            verify_bsp(self.base)

    def test_policy_change_rejected(self):
        self.manifest['network_policy']['network_phy_policy.inc'] = '0' * 64
        self.save()
        with self.assertRaisesRegex(ValueError, 'fingerprints'):
            verify_bsp(self.base)

    def test_old_phy_even_with_updated_source_hash_rejected(self):
        binding = self.manifest['compile_bindings']['lwip_031_xemacpsif_physpeed.o']
        source = self.base / binding['source']
        source.write_text(source.read_text().replace('map[1]=TRUE;', 'map[0]=TRUE;'))
        binding['source_sha256'] = digest(source)
        self.manifest['frozen_files'][binding['source']] = digest(source)
        self.save()
        with self.assertRaisesRegex(ValueError, 'current addr1'):
            verify_bsp(self.base)

    def test_modified_source_object_header_and_archive_rejected(self):
        for relative in ['compiled_sources/xemacpsif_physpeed.c', 'xil_000_boot.o',
                         'include/xparameters.h', 'liblwip4.a']:
            with self.subTest(relative=relative):
                path = self.base / relative
                before = path.read_bytes()
                path.write_bytes(before + b'changed')
                with self.assertRaises(ValueError):
                    verify_bsp(self.base)
                path.write_bytes(before)

    def test_stale_archive_rehashed_still_rejected(self):
        write_archive(self.base / 'liblwip4.a', {'lwip_031_xemacpsif_physpeed.o': b'OLD PHY object'})
        self.manifest['libraries']['liblwip4.a'] = digest(self.base / 'liblwip4.a')
        self.save()
        with self.assertRaisesRegex(ValueError, 'archive members'):
            verify_bsp(self.base)

    def test_missing_binding_and_traversal_rejected(self):
        before = copy.deepcopy(self.manifest)
        self.manifest['compile_bindings'].pop('xil_000_boot.o')
        self.save()
        with self.assertRaisesRegex(ValueError, 'bindings'):
            verify_bsp(self.base)
        self.manifest = before
        self.manifest['compile_bindings']['xil_000_boot.o']['source'] = '../escape.S'
        self.save()
        with self.assertRaisesRegex(ValueError, 'escapes'):
            verify_bsp(self.base)

    def test_local_quoted_header_changed_removed_or_added_rejected(self):
        header = self.base / 'compiled_sources/local_policy.h'
        before = header.read_bytes()
        header.write_text('#define PHY_ADDR 0\n')
        with self.assertRaisesRegex(ValueError, 'local-header hash'):
            verify_bsp(self.base)
        header.unlink()
        with self.assertRaisesRegex(ValueError, 'file set'):
            verify_bsp(self.base)
        header.write_bytes(before)
        added = header.parent / 'unexpected.h'
        added.write_text('#define OVERRIDE 1\n')
        with self.assertRaisesRegex(ValueError, 'file set'):
            verify_bsp(self.base)
        added.unlink()
        self.assertEqual(verify_bsp(self.base)['schema'], 'ADDA_BSP_BUILD_V2')

    def test_malformed_thin_duplicate_archives_rejected(self):
        path = self.base / 'bad.a'
        for raw in [b'!<thin>\n', b'!<arch>\ntruncated']:
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                archive_members(path)
        original = (self.base / 'libxil.a').read_bytes()
        path.write_bytes(original + original[8:])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            archive_members(path)
        source = self.base / 'compiled_sources/xemacpsif_physpeed.c'
        require_current_phy(source)

    def test_platform_rejects_before_creating_output_or_invoking_compiler(self):
        self.manifest.pop('schema')
        self.save()
        fake_bin = self.base.parent / 'compiler'
        fake_bin.mkdir()
        # Discovery checks existence; any accidental compiler execution fails.
        (fake_bin / 'arm-none-eabi-gcc.exe').write_bytes(b'not executable')
        output = self.base.parent / 'must_not_exist'
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'build_platform.py'),
                                 '--bsp', str(self.base), '--out', str(output),
                                 '--arm-bin', str(fake_bin)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Legacy/unbound BSP manifest rejected', result.stderr)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
