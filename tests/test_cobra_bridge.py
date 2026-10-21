import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.cobra_bridge import (ROOT,catalog_exported_scripts,command_ids_for_version,
                                run_bridge,validate_wmsc,variant_command_ids)


def wmsc_commands(commands):
    size=28+len(commands)*8
    return (b'WMS0U130'+struct.pack('>II',size,1)+struct.pack('>III',7,128,28)+
            b''.join(struct.pack('>II',command,argument) for command,argument in commands))


def wmsc():
    return wmsc_commands([(344,0)])


class BridgeTests(unittest.TestCase):
    def test_catalog_counts_numeric_commands_without_assigning_meaning(self):
        text=(
            'null [priority=255]:\n'
            '    cmd_344\n\n'
            'scr_001 [priority=128]:\n'
            '    wait        30\n'
            '    cmd_007 0x10\n'
            '    cmd_344\n')
        report=catalog_exported_scripts(text,{
            'game':'nsmbu','game_variant':'1.3.0_NSLU',
            'table_length':2,'terminator_command':344,
        },{7,344})
        self.assertEqual(report['script_count'],2)
        self.assertEqual(report['total_command_count'],4)
        self.assertEqual(report['distinct_command_id_count'],2)
        self.assertEqual(report['command_id_usage'],[
            {'command_id':7,'occurrences':2,'scripts':1},
            {'command_id':344,'occurrences':2,'scripts':2},
        ])
        self.assertEqual(report['unrecognized_command_ids'],[])
        self.assertFalse(report['game_verified'])
        self.assertFalse(report['deployed'])
        self.assertIn('without assigning command behavior',report['interpretation'])

    def test_catalog_rejects_malformed_or_unverifiable_exports(self):
        version={'game':'nsmbu','game_variant':'1.3.0_NSLU',
                 'table_length':1,'terminator_command':344}
        for text,message in (
                ('    cmd_344\n','before a script header'),
                ('null [priority=1]:\n    cmd_344\n'
                 'scr_000 [priority=1]:\n    cmd_344\n','duplicate script ID'),
                ('null [priority=1]:\n    cmd_344\n    cmd_001\n','early terminator'),
                ('null [priority=1]:\n    cmd_001\n','must end with command'),
                ('null [priority=1]:\n    cmd_344\n','declares 2'),
                ('null [priority=1]:\n    cmd_001 hello\n    cmd_344\n','not an integer'),
                ('null [priority=1]:\n    '+'x'*(64*1024+1),'exceeds 65536 characters'),
        ):
            declared={**version,'table_length':2 if message=='declares 2' else 1}
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError,message):
                    catalog_exported_scripts(text,declared)

    def test_catalog_cli_writes_new_hashed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);inputs=root/'inputs';inputs.mkdir()
            scripts=inputs/'scripts.txt'
            scripts.write_text('null [priority=255]:\n    cmd_344\n',encoding='utf-8')
            version=inputs/'version.json'
            version.write_text(json.dumps({
                'game':'nsmbu','game_variant':'1.3.0_NSLU',
                'table_length':1,'terminator_command':344,
            }),encoding='utf-8')
            output=root/'catalog.json'
            result=subprocess.run([
                sys.executable,str(ROOT/'tools/cobra_bridge.py'),'catalog',
                str(scripts),str(version),'--cobra-root',str(root/'missing-cobra'),
                '--output',str(output),
            ],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['script_count'],1)
            self.assertEqual(report['inputs'][0]['size'],scripts.stat().st_size)
            self.assertFalse(report['command_registry_checked'])
            previous=output.read_bytes()
            repeated=subprocess.run([
                sys.executable,str(ROOT/'tools/cobra_bridge.py'),'catalog',
                str(scripts),str(version),'--cobra-root',str(root/'missing-cobra'),
                '--output',str(output),
            ],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
            self.assertNotEqual(repeated.returncode,0)
            self.assertEqual(output.read_bytes(),previous)

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
        self.assertFalse(report['command_registry_checked'])
        self.assertIsNone(report['unrecognized_command_ids'])
        self.assertIsNone(report['command_registry_warning'])
        malformed=bytearray(wmsc());struct.pack_into('>I',malformed,24,10000)
        with self.assertRaisesRegex(ValueError,'offset'):validate_wmsc(malformed)
        malformed=bytearray(wmsc());struct.pack_into('>I',malformed,28,343)
        with self.assertRaisesRegex(ValueError,'terminator'):validate_wmsc(malformed)
        with self.assertRaisesRegex(ValueError,'header'):validate_wmsc(b'WMS0Xall'+wmsc()[8:])

    def test_variant_command_registry_inherits_renumbered_ids(self):
        variants={
            'base':{'commands':{'add':{'2':{},'3':{}}}},
            'middle':{'parent':'base','commands':{'renumber':{'3-*':'+2'},'add':{'3':{}}}},
            'target':{'parent':'middle','commands':{'renumber':{'5-*':'+1'},'add':{'5':{}}}},
        }
        self.assertEqual(variant_command_ids(variants,'target'),{2,3,5,6})
        self.assertIsNone(variant_command_ids(variants,'missing'))
        self.assertIsNone(variant_command_ids(variants,''))
        self.assertIsNone(variant_command_ids({'a':{'parent':'b'},'b':{'parent':'a'}},'a'))
        self.assertIsNone(variant_command_ids({'a':{'commands':{'renumber':{3:'+1'}}}},'a'))

    def test_real_cobra_variant_command_sets_apply_deletes_after_renumbering(self):
        variants=json.loads((ROOT/'external/Cobra/data/nsmbu.json').read_text(encoding='utf-8'))
        self.assertEqual(variant_command_ids(variants,'1.3.0_NSLU'),set(range(345)))
        self.assertEqual(variant_command_ids(variants,'DX'),set(range(344))-{311})

    def test_unknown_numeric_command_is_advisory_and_encode_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cobra=root/'Cobra';(cobra/'data').mkdir(parents=True)
            (cobra/'cobra.py').write_text('')
            (cobra/'data/nsmbu.json').write_text(json.dumps({
                'base':{'commands':{'add':{'344':{}}}},
                'target':{'parent':'base','commands':{'add':{'1':{}}}},
            }),encoding='utf-8')
            inputs=root/'inputs';inputs.mkdir()
            scripts=inputs/'scripts.txt';scripts.write_text('cmd_999\n',encoding='utf-8')
            version=inputs/'version.json';version.write_text(json.dumps({
                'game':'nsmbu','game_variant':'target',
            }),encoding='utf-8')
            encoded_bytes=wmsc_commands([(999,0),(344,0)])

            def fake_encode(command,**kwargs):
                Path(command[-1]).write_bytes(encoded_bytes)
                return subprocess.CompletedProcess(command,0,'encoded','')

            output=root/'encoded'
            with patch('tools.cobra_bridge.upstream_commit',return_value='a'*40), \
                    patch('tools.cobra_bridge.local_diff',return_value=b''), \
                    patch('tools.cobra_bridge.subprocess.run',side_effect=fake_encode):
                report=run_bridge('encode',[scripts,version],output,cobra)
            self.assertTrue(report['success'])
            self.assertTrue(report['wmsc']['command_registry_checked'])
            self.assertEqual(report['wmsc']['unrecognized_command_ids'],[999])
            self.assertIn('numeric IDs',report['wmsc']['command_registry_warning'])
            self.assertEqual((output/'scripts.wmsc').read_bytes(),encoded_bytes)


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
            catalog=catalog_exported_scripts(
                (base/'events/scripts.txt').read_text(encoding='utf-8'),
                json.loads((base/'events/version.json').read_text(encoding='utf-8')),
                command_ids_for_version(ROOT/'external/Cobra',
                    json.loads((base/'events/version.json').read_text(encoding='utf-8'))))
            self.assertEqual(catalog['script_count'],121)
            self.assertEqual(catalog['total_command_count'],993)
            self.assertTrue(catalog['command_registry_checked'])
            self.assertEqual(catalog['unrecognized_command_ids'],[])
            encoded=run_bridge('encode',[base/'events/scripts.txt',base/'events/version.json'],base/'encoded')
            summary=encoded['wmsc']
            self.assertEqual(summary['script_ids'],list(range(121)))
            self.assertEqual(summary['size'],9412)
            self.assertEqual(sum(summary['command_counts']),993)
            self.assertEqual(summary['sha256'],'fdb8c2d86ba0acb56d16a5d00a24304e263ad5ced55bc7293e693427f868b45d')
            self.assertTrue(summary['command_registry_checked'])
            self.assertEqual(summary['unrecognized_command_ids'],[])
            self.assertIsNone(summary['command_registry_warning'])
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
