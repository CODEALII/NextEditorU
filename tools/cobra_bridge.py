"""Run the separate GPL Cobra checkout safely, without importing/copying its code.

All output goes into a new directory outside source directories and the game
dump. The bridge never installs a script loader or deploys WMSC to the game.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys


ROOT=Path(__file__).resolve().parents[1]
DEFAULT_COBRA=ROOT/'external/Cobra'
MAX_CATALOG_TEXT_BYTES=16*1024*1024
MAX_CATALOG_VERSION_BYTES=64*1024
MAX_CATALOG_LINE_CHARS=64*1024
MAX_CATALOG_COMMANDS=1_000_000
SCRIPT_HEADER=re.compile(r'^(null|scr_(\d+)) \[priority=(\d+)\]:$')
SCRIPT_COMMAND=re.compile(r'cmd_(\d+)\Z')


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def variant_command_ids(variants, variant_name):
    """Resolve command IDs through Cobra variant additions and renumbering."""
    if (not isinstance(variants, dict) or not isinstance(variant_name, str) or
            not variant_name or variant_name not in variants):
        return None
    lineage = []
    seen = set()
    current = variant_name
    try:
        while current:
            if current in seen or current not in variants:
                return None
            seen.add(current)
            info = variants[current]
            if not isinstance(info, dict):
                return None
            lineage.append(info)
            current = info.get('parent')
            if current is not None and not isinstance(current, str):
                return None

        known = set()
        for info in reversed(lineage):
            commands = info.get('commands', {})
            if not isinstance(commands, dict):
                return None
            renumber = commands.get('renumber', {})
            additions = commands.get('add', {})
            deletions = commands.get('delete', [])
            if (not isinstance(renumber, dict) or not isinstance(additions, dict) or
                    not isinstance(deletions, list)):
                return None

            renumber_ranges = []
            for span, amount in renumber.items():
                if not isinstance(span, str) or '-' not in span:
                    return None
                start_text, end_text = span.split('-', 1)
                start = int(start_text)
                end = None if end_text == '*' else int(end_text)
                offset = int(amount)
                if start < 0 or (end is not None and end < start):
                    return None
                renumber_ranges.append((start, end, offset))

            transformed = set()
            for command_id in known:
                value = command_id
                for start, end, offset in renumber_ranges:
                    if start <= value and (end is None or value <= end):
                        value += offset
                if 0 <= value <= 0xFFFFFFFF:
                    transformed.add(value)
            known = transformed

            for command_id in deletions:
                if type(command_id) is not int or not 0 <= command_id <= 0xFFFFFFFF:
                    return None
                known.discard(command_id)
            for command_id in additions:
                value = int(command_id)
                if not 0 <= value <= 0xFFFFFFFF:
                    return None
                known.add(value)
        return known
    except (TypeError, ValueError, OverflowError):
        return None


def command_ids_for_version(cobra_root, version_info):
    """Load the local NSMBU command registry for a Cobra export variant."""
    if not isinstance(version_info, dict) or version_info.get('game') != 'nsmbu':
        return None
    variant_name = version_info.get('game_variant')
    try:
        path = Path(cobra_root) / 'data/nsmbu.json'
        variants = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    return variant_command_ids(variants, variant_name)


def catalog_exported_scripts(script_text, version_info, known_command_ids=None):
    """Inventory Cobra text-export structure without assigning command meaning."""
    if not isinstance(script_text,str):
        raise ValueError('Cobra script export must be UTF-8 text')
    if not isinstance(version_info,dict) or version_info.get('game')!='nsmbu':
        raise ValueError('Expected NSMBU Cobra version metadata')
    variant=version_info.get('game_variant')
    table_length=version_info.get('table_length')
    terminator=version_info.get('terminator_command')
    if (not isinstance(variant,str) or not variant or type(table_length) is not int or
            not 1<=table_length<=65535 or type(terminator) is not int or
            not 0<=terminator<=0xFFFFFFFF):
        raise ValueError('Invalid NSMBU Cobra version metadata')

    scripts=[]
    current=None
    seen_ids=set()
    command_occurrences=Counter()
    total_command_count=0

    def finish_script():
        if current is None:
            return
        if not current['terminated']:
            raise ValueError(
                f"Script {current['label']} must end with command {terminator}")
        scripts.append({
            'id':current['id'],
            'label':current['label'],
            'priority':current['priority'],
            'command_count':current['command_count'],
            'command_ids':sorted(current['command_ids']),
        })

    for line_number,line in enumerate(script_text.splitlines(),1):
        if len(line)>MAX_CATALOG_LINE_CHARS:
            raise ValueError(f'Line {line_number}: exceeds {MAX_CATALOG_LINE_CHARS} characters')
        if not line.strip():
            continue
        header=SCRIPT_HEADER.fullmatch(line)
        if header:
            finish_script()
            label=header.group(1)
            script_id=0 if label=='null' else int(header.group(2))
            priority=int(header.group(3))
            if script_id>0xFFFFFFFF or priority>0xFFFFFFFF:
                raise ValueError(f'Line {line_number}: script ID or priority is out of range')
            if script_id in seen_ids:
                raise ValueError(f'Line {line_number}: duplicate script ID {script_id}')
            seen_ids.add(script_id)
            current={'id':script_id,'label':label,'priority':priority,
                     'command_count':0,'command_ids':set(),'terminated':False}
            continue
        if current is None:
            raise ValueError(f'Line {line_number}: command appears before a script header')
        if not line.startswith('    '):
            raise ValueError(f'Line {line_number}: malformed script command indentation')
        parts=line[4:].split()
        if len(parts) not in (1,2):
            raise ValueError(f'Line {line_number}: expected a command and optional numeric argument')
        command=parts[0]
        if command=='wait':
            command_id=7
        else:
            match=SCRIPT_COMMAND.fullmatch(command)
            if not match:
                raise ValueError(f'Line {line_number}: unsupported Cobra command token {command!r}')
            command_id=int(match.group(1))
        if command_id>0xFFFFFFFF:
            raise ValueError(f'Line {line_number}: command ID is out of range')
        if current['terminated']:
            raise ValueError(f"Script {current['label']} contains an early terminator")
        if len(parts)==2:
            try:
                argument=int(parts[1],0)
            except ValueError:
                if re.fullmatch(r'[0-9]+',parts[1]):
                    argument=int(parts[1],10)
                else:
                    raise ValueError(f'Line {line_number}: command argument is not an integer')
            if not 0<=argument<=0xFFFFFFFF:
                raise ValueError(f'Line {line_number}: command argument is out of range')
        current['command_count']+=1
        current['command_ids'].add(command_id)
        if command_id==terminator:
            current['terminated']=True
        command_occurrences[command_id]+=1
        total_command_count+=1
        if total_command_count>MAX_CATALOG_COMMANDS:
            raise ValueError(f'Cobra script export exceeds {MAX_CATALOG_COMMANDS} commands')
    finish_script()

    if len(scripts)!=table_length:
        raise ValueError(
            f'Cobra export has {len(scripts)} scripts; version metadata declares {table_length}')
    scripts.sort(key=lambda item:item['id'])
    command_script_counts=Counter()
    priority_counts=Counter()
    for script in scripts:
        priority_counts[script['priority']]+=1
        for command_id in script['command_ids']:
            command_script_counts[command_id]+=1
    distinct_ids=sorted(command_occurrences)
    unrecognized=(sorted(set(distinct_ids)-known_command_ids)
                  if known_command_ids is not None else None)
    return {
        'format':'nsmbu-cobra-event-catalog-v1',
        'game':version_info['game'],
        'game_variant':variant,
        'declared_script_count':table_length,
        'script_count':len(scripts),
        'total_command_count':total_command_count,
        'distinct_command_id_count':len(distinct_ids),
        'priority_script_counts':[
            {'priority':priority,'script_count':count}
            for priority,count in sorted(priority_counts.items())],
        'command_id_usage':[
            {'command_id':command_id,
             'occurrences':command_occurrences[command_id],
             'scripts':command_script_counts[command_id]}
            for command_id in distinct_ids],
        'command_registry_checked':known_command_ids is not None,
        'unrecognized_command_ids':unrecognized,
        'scripts':scripts,
        'interpretation':(
            'Offline Cobra export inventory only. Numeric command IDs, priorities, and counts '
            'are listed without assigning command behavior or mapping scripts to world points, '
            'unlock conditions, or in-game execution.'),
        'game_verified':False,
        'deployed':False,
    }


def _read_bounded(path,limit,label):
    with Path(path).open('rb') as stream:
        data=stream.read(limit+1)
    if len(data)>limit:
        raise ValueError(f'{label} exceeds {limit} bytes')
    return data


def _catalog_command(inputs,cobra_root,output):
    if len(inputs)!=2:
        raise ValueError('catalog requires scripts.txt and version.json')
    paths=[Path(path).resolve(strict=True) for path in inputs]
    if any(not path.is_file() for path in paths):
        raise ValueError('catalog inputs must be files')
    script_data=_read_bounded(paths[0],MAX_CATALOG_TEXT_BYTES,'Cobra script export')
    version_data=_read_bounded(paths[1],MAX_CATALOG_VERSION_BYTES,'Cobra version metadata')
    try:
        script_text=script_data.decode('utf-8')
        version_info=json.loads(version_data.decode('utf-8'))
    except (UnicodeDecodeError,json.JSONDecodeError) as error:
        raise ValueError('catalog inputs must be valid UTF-8 text and JSON') from error
    report=catalog_exported_scripts(
        script_text,version_info,command_ids_for_version(cobra_root,version_info))
    report['inputs']=[{'path':str(path),'size':len(data),
                       'sha256':hashlib.sha256(data).hexdigest()}
                      for path,data in zip(paths,(script_data,version_data))]
    if output is not None:
        output=Path(output).resolve()
        protected=(ROOT/'NSMBU Modding Project').resolve()
        cobra_root=Path(cobra_root).resolve()
        if (output.exists() or output.is_relative_to(protected) or
                output.is_relative_to(cobra_root) or
                any(output.is_relative_to(path.parent) for path in paths)):
            raise ValueError('Catalog output must be a new file outside input, game dump, and Cobra directories')
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('x',encoding='utf-8') as stream:
            json.dump(report,stream,indent=2)
            stream.write('\n')
    return report


def validate_wmsc(data, known_command_ids=None):
    """Independently validate WMSC structure and optionally lint command IDs."""
    if len(data)<16 or data[:8]!=b'WMS0U130':
        raise ValueError('Expected NSMBU v1.3 WMS0U130 header')
    size,count=struct.unpack_from('>II',data,8)
    if size!=len(data) or count>65535 or 16+12*count>size:
        raise ValueError('Invalid WMSC length or table count')
    ids=list(struct.unpack_from('>'+str(count)+'I',data,16))
    if ids!=sorted(set(ids)):
        raise ValueError('WMSC script IDs must be sorted and unique')
    table=16+4*count
    starts=[];priorities=[]
    for i in range(count):
        priority,start=struct.unpack_from('>II',data,table+8*i)
        if start<16+12*count or start>size-8 or (start-(16+12*count))%8!=0:
            raise ValueError('Invalid WMSC command offset')
        priorities.append(priority);starts.append(start)
    if starts!=sorted(set(starts)):
        raise ValueError('WMSC scripts must occupy separate ordered command ranges')
    command_counts=[];command_ids=set()
    for start,end in zip(starts,starts[1:]+[size]):
        if end<=start or (end-start)%8:
            raise ValueError('Invalid WMSC command range')
        commands=[struct.unpack_from('>II',data,p) for p in range(start,end,8)]
        if commands[-1][0]!=344 or any(command==344 for command,_ in commands[:-1]):
            raise ValueError('WMSC script must end with the v1.3 terminator 344')
        command_ids.update(command for command,_ in commands)
        command_counts.append(len(commands))
    return {'format':'WMS0U130','size':size,'script_count':count,'script_ids':ids,
            'priorities':priorities,'command_counts':command_counts,
            'command_registry_checked':known_command_ids is not None,
            'unrecognized_command_ids':(sorted(command_ids-known_command_ids)
                                        if known_command_ids is not None else None),
            'command_registry_warning':(
                'Unrecognized command IDs remain encoded as numeric IDs; they were not changed.'
                if known_command_ids is not None and command_ids-known_command_ids else None),
            'sha256':hashlib.sha256(data).hexdigest(),'game_verified':False}


def upstream_commit(cobra_root):
    proc=subprocess.run(['git','-C',str(cobra_root),'rev-parse','HEAD'],
                        capture_output=True,text=True,check=False)
    commit=proc.stdout.strip()
    if proc.returncode or len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Cobra must be a Git checkout so provenance can be recorded')
    return commit


def local_diff(cobra_root):
    proc=subprocess.run(['git','-C',str(cobra_root),'diff','--binary','--no-ext-diff','HEAD','--'],
                        capture_output=True,check=False)
    if proc.returncode:
        raise ValueError('Unable to record Cobra tracked working-tree patch')
    return proc.stdout


def run_bridge(operation,inputs,output,cobra_root=DEFAULT_COBRA,timeout=120):
    if operation not in ('analyze','export','encode'):
        raise ValueError('Unsupported Cobra operation')
    inputs=[Path(p).resolve(strict=True) for p in inputs]
    expected=2 if operation=='encode' else 1
    if len(inputs)!=expected or any(not p.is_file() for p in inputs):
        raise ValueError(f'{operation} requires {expected} input file(s)')
    cobra_root=Path(cobra_root).resolve(strict=True)
    script=cobra_root/'cobra.py'
    if not script.is_file():
        raise ValueError('Cobra checkout missing cobra.py')
    output=Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'Output directory already exists: {output}')
    protected=(ROOT/'NSMBU Modding Project').resolve()
    if output.is_relative_to(protected) or output.is_relative_to(cobra_root) or any(output.is_relative_to(p.parent) for p in inputs):
        raise ValueError('Output must be outside the game dump, Cobra checkout and input directories')
    commit=upstream_commit(cobra_root)
    diff=local_diff(cobra_root)
    source_info=[{'path':str(p),'sha256':sha256(p),'size':p.stat().st_size} for p in inputs]
    output.mkdir(parents=True,exist_ok=False)
    if diff:
        with (output/'cobra-local.patch').open('xb') as stream:stream.write(diff)
    command=[sys.executable,str(script),operation,*map(str,inputs)]
    if operation=='export':command.extend([str(output/'scripts.txt'),str(output/'version.json')])
    elif operation=='encode':command.append(str(output/'scripts.wmsc'))
    metadata={'operation':operation,'cobra_url':'https://github.com/RoadrunnerWMC/Cobra',
              'cobra_commit':commit,'cwd':str(cobra_root),'command':command,
              'cobra_dirty':bool(diff),'cobra_diff_sha256':hashlib.sha256(diff).hexdigest(),
              'cobra_python_sha256':{p.name:sha256(p) for p in sorted(cobra_root.glob('*.py'))},
              'inputs':source_info,'success':False,'deployed':False}
    try:
        proc=subprocess.run(command,cwd=cobra_root,capture_output=True,text=True,
                            encoding='utf-8',errors='replace',timeout=timeout,check=False)
        (output/'stdout.log').write_text(proc.stdout,encoding='utf-8')
        (output/'stderr.log').write_text(proc.stderr,encoding='utf-8')
        metadata['returncode']=proc.returncode
        if proc.returncode:
            raise RuntimeError(f'Cobra {operation} failed; see {output / "stderr.log"}')
        if operation=='export':
            if not (output/'scripts.txt').is_file() or not (output/'version.json').is_file():
                raise ValueError('Cobra export did not produce both expected files')
            metadata['analysis']=json.loads((output/'version.json').read_text(encoding='utf-8'))
        elif operation=='encode':
            version_info=json.loads(inputs[1].read_text(encoding='utf-8'))
            known_command_ids=command_ids_for_version(cobra_root,version_info)
            metadata['wmsc']=validate_wmsc((output/'scripts.wmsc').read_bytes(),
                                           known_command_ids)
        if any(sha256(p)!=info['sha256'] for p,info in zip(inputs,source_info)):
            raise RuntimeError('Source file changed during Cobra invocation')
        metadata['outputs']={p.name:{'sha256':sha256(p),'size':p.stat().st_size}
                             for p in output.iterdir() if p.is_file()}
        metadata['success']=True
    except Exception as exc:
        metadata['error']=str(exc)
        raise
    finally:
        with (output/'provenance.json').open('x',encoding='utf-8') as stream:
            json.dump(metadata,stream,indent=2)
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['analyze','export','encode','catalog'])
    parser.add_argument('inputs',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,help='New output directory/file; existing paths are refused')
    parser.add_argument('--cobra-root',type=Path,default=DEFAULT_COBRA)
    args=parser.parse_args()
    if args.operation=='catalog':
        result=_catalog_command(args.inputs,args.cobra_root,args.output)
    else:
        if args.output is None:
            parser.error('--output is required for analyze, export, and encode')
        result=run_bridge(args.operation,args.inputs,args.output,args.cobra_root)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
