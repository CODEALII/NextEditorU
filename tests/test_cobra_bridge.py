import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.cobra_bridge import ROOT,run_bridge,validate_wmsc


def wmsc():
    return b'WMS0U130'+struct.pack('>7I',36,1,7,128,28,344,0)


class BridgeTests(unittest.TestCase):
    def test_argument_list_cwd_paths_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cobra=root/'Cobra checkout';cobra.mkdir()
            (cobra/'cobra.py').write_text('import os,sys\nprint(os.getcwd())\nprint(repr(sys.argv[1:]))\n')
            src=root/'inputs';src.mkdir()
            # Shell metacharacters are ordinary file-name characters.
            input_file=src/'source & $(injection).rpx';input_file.write_bytes(b'original')
            with patch('tools.cobra_bridge.upstream_commit',return_value='a'*40), patch('tools.cobra_bridge.local_diff',return_value=b''):
                report=run_bridge('analyze',[input_file],root/'new output',cobra)
            self.assertTrue(report['success'])
            self.assertEqual(report['command'][3],str(input_file.resolve()))
            self.assertEqual(report['cwd'],str(cobra.resolve()))
            self.assertIn(str(cobra.resolve()),(root/'new output/stdout.log').read_text())
            self.assertEqual(input_file.read_bytes(),b'original')
            saved=json.loads((root/'new output/provenance.json').read_text())
            self.assertEqual(saved['cobra_commit'],'a'*40)
            self.assertFalse(saved['deployed'])

    def test_no_overwrite_or_output_within_input_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cobra=root/'cobra';cobra.mkdir();(cobra/'cobra.py').write_text('')
            src=root/'source';src.mkdir();input_file=src/'game.rpx';input_file.write_bytes(b'original')
            output=root/'exists';output.mkdir();(output/'keep').write_text('keep')
            with patch('tools.cobra_bridge.subprocess.run') as run:
                with self.assertRaises(FileExistsError):run_bridge('analyze',[input_file],output,cobra)
                with self.assertRaisesRegex(ValueError,'outside'):run_bridge('analyze',[input_file],src/'new',cobra)
                with self.assertRaisesRegex(ValueError,'outside'):run_bridge('analyze',[input_file],cobra/'new',cobra)
                run.assert_not_called()
            self.assertEqual((output/'keep').read_text(),'keep')

    def test_failed_process_retains_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cobra=root/'cobra';cobra.mkdir()
            (cobra/'cobra.py').write_text('import sys\nprint("actual failure",file=sys.stderr)\nsys.exit(7)\n')
            src=root/'source';src.mkdir();input_file=src/'x';input_file.write_bytes(b'x')
            with patch('tools.cobra_bridge.upstream_commit',return_value='b'*40), patch('tools.cobra_bridge.local_diff',return_value=b''):
                with self.assertRaisesRegex(RuntimeError,'failed'):
                    run_bridge('analyze',[input_file],root/'failed',cobra)
            report=json.loads((root/'failed/provenance.json').read_text())
            self.assertFalse(report['success']);self.assertEqual(report['returncode'],7)
            self.assertIn('actual failure',(root/'failed/stderr.log').read_text())

    def test_independent_wmsc_validation(self):
        report=validate_wmsc(wmsc())
        self.assertEqual(report['script_ids'],[7])
        self.assertEqual(report['command_counts'],[1])
        malformed=bytearray(wmsc());struct.pack_into('>I',malformed,24,10000)
        with self.assertRaisesRegex(ValueError,'offset'):validate_wmsc(malformed)
        malformed=bytearray(wmsc());struct.pack_into('>I',malformed,28,343)
        with self.assertRaisesRegex(ValueError,'terminator'):validate_wmsc(malformed)
        with self.assertRaisesRegex(ValueError,'header'):validate_wmsc(b'WMS0Xall'+wmsc()[8:])


class LocalCobraTests(unittest.TestCase):
    def test_actual_rpx_export(self):
        source=ROOT/'NSMBU Modding Project/code/red-pro2.rpx'
        if not source.is_file() or not (ROOT/'external/Cobra/cobra.py').is_file():
            self.skipTest('User-provided RPX or independent Cobra checkout unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            report=run_bridge('export',[source],Path(tmp)/'events')
            analysis=report['analysis']
            self.assertEqual(analysis['game'],'nsmbu')
            self.assertEqual(analysis['game_variant'],'1.3.0_NSLU')
            self.assertEqual(analysis['table_addr'],0x100458b8)
            self.assertEqual(analysis['static_init_func_addr'],0x021e1ee0)
            self.assertEqual(analysis['table_length'],121)
            self.assertEqual(analysis['terminator_command'],344)

    def test_actual_export_encode_roundtrip(self):
        source=ROOT/'NSMBU Modding Project/code/red-pro2.rpx'
        if not source.is_file() or not (ROOT/'external/Cobra/cobra.py').is_file():
            self.skipTest('User-provided RPX or independent Cobra checkout unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            exported=run_bridge('export',[source],base/'events')
            encoded=run_bridge('encode',[base/'events/scripts.txt',base/'events/version.json'],base/'encoded')
            summary=encoded['wmsc']
            self.assertEqual(summary['script_ids'],list(range(121)))
            self.assertEqual(summary['size'],9412)
            self.assertEqual(sum(summary['command_counts']),993)
            self.assertEqual(summary['sha256'],'fdb8c2d86ba0acb56d16a5d00a24304e263ad5ced55bc7293e693427f868b45d')
            # Independently compare all exported command/argument pairs and priorities.
            scripts={};current=None
            for line in (base/'events/scripts.txt').read_text().splitlines():
                if not line.strip():continue
                if not line.startswith(' '):
                    name,priority=line[:-1].split(' [priority=')
                    current=0 if name=='null' else int(name.removeprefix('scr_'))
                    scripts[current]=(int(priority[:-1]),[])
                else:
                    parts=line.split();name=parts[0]
                    command=7 if name=='wait' else int(name.removeprefix('cmd_'))
                    argument=int(parts[1],0) if len(parts)>1 else 0
                    scripts[current][1].append((command,argument))
            binary=(base/'encoded/scripts.wmsc').read_bytes()
            for script_id,(priority,commands) in scripts.items():
                table=16+121*4+script_id*8
                actual_priority,start=struct.unpack_from('>II',binary,table)
                self.assertEqual(actual_priority,priority)
                actual=[struct.unpack_from('>II',binary,start+i*8) for i in range(len(commands))]
                self.assertEqual(actual,commands)
            # Inherited named terminators must be remapped 341 -> 342 -> 344.
            named=base/'named';named.mkdir()
            (named/'scripts.txt').write_text((base/'events/scripts.txt').read_text().replace('cmd_344','end'))
            named_report=run_bridge('encode',[named/'scripts.txt',base/'events/version.json'],base/'named-encoded')
            self.assertEqual(named_report['wmsc']['sha256'],summary['sha256'])
            self.assertFalse(encoded['deployed'])
            self.assertTrue(encoded['cobra_dirty'])
            self.assertEqual(encoded['cobra_diff_sha256'],exported['cobra_diff_sha256'])


if __name__=='__main__':unittest.main()
